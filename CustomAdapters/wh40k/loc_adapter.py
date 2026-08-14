"""
loc_adapter.py  —  B-Roll Engine Custom Adapter for loc.gov  v1.1
==================================================================
Library of Congress historical photos, prints, drawings and illustrations.
No API key required. Content is public domain.

ARCHITECTURE NOTE (v1.1):
  The LOC JSON API is a proper REST API (?fo=json on any loc.gov URL returns
  structured JSON). However, LOC now sits behind Cloudflare, which blocks
  plain requests.get() calls with 403. Playwright (headless Chromium) is
  required to pass the challenge — same approach as the 40k and artvee adapters.

  Once Playwright loads the page, we grab page.content() and parse the JSON
  directly from the rendered HTML — the page body IS the JSON response when
  ?fo=json is in the URL, so BeautifulSoup isn't needed; we parse with json.loads.

Search endpoint:  https://www.loc.gov/photos/?q=<query>&fo=json
  - /photos/ scopes to still images (photos, prints, drawings)
  - results[] contains: id, title, image_url[], date, contributor[], description[]
  - image_url[0] is a ~150px thumbnail — used as preview_url

Item endpoint:  https://www.loc.gov/item/<id>/?fo=json
  - Called at download time to get the full-res file list
  - resources[].files[][] — nested list of file objects with url/width/height/size
  - We pick the largest JPEG by pixel area, skipping TIFFs (70MB+)

CDN image downloads (cdn.loc.gov):
  - NOT behind Cloudflare — plain requests.get() works fine here
  - So only search + item metadata fetches need Playwright
  - The actual image binary download uses requests, keeping it fast

Run:
    pip install flask requests beautifulsoup4 playwright
    playwright install chromium
    python loc_adapter.py

Port: 3002  (40k=3000, artvee=3001, loc=3002)
"""

import atexit
import io
import json
import queue
import threading
import time
import logging
from concurrent.futures import Future, TimeoutError as FutureTimeoutError

import requests
from flask import Flask, jsonify, request, send_file, abort
from playwright.sync_api import sync_playwright, TimeoutError as PWTimeout

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------
BASE_URL        = "https://www.loc.gov"
PORT            = 3002
MAX_PAGES       = 4       # max search pages to paginate
RESULTS_PER_PG  = 25      # items per page (LOC default)
INTER_DELAY     = 1.0     # seconds between Playwright fetches
PAGE_TIMEOUT    = 25_000  # ms
SELECTOR_WAIT   = 8_000   # ms

DL_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept": "*/*",
}

app = Flask(__name__)
logging.basicConfig(level=logging.INFO, format="%(levelname)s  %(message)s")
log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Optional auth
# ---------------------------------------------------------------------------
AUTH_TOKEN = None

def _check_auth():
    if AUTH_TOKEN is None:
        return
    if request.headers.get("Authorization", "") != f"Bearer {AUTH_TOKEN}":
        abort(401, description="Unauthorized")


# ---------------------------------------------------------------------------
# Persistent Playwright browser (dedicated worker thread) with stateless
# fallback. See the identical pattern + rationale in 40k_adapter.py: sync
# Playwright pins a Browser/Context to the thread that created it, so a
# persistent browser must be owned by exactly one dedicated thread — Flask
# request threads submit jobs to it via a queue and block on a Future.
# ---------------------------------------------------------------------------

_browser_lock = threading.Lock()          # guards worker-thread startup only
_job_queue: "queue.Queue" = queue.Queue()
_worker_thread: threading.Thread | None = None
_browser_init_failed = False              # True disables persistence for this process
_pw_instance = None
_browser = None

WORKER_JOB_TIMEOUT = 45.0   # seconds — ceiling per job before falling back to fresh


def _launch_or_reuse_browser():
    """Runs ONLY on the worker thread. Returns the shared Browser or raises."""
    global _pw_instance, _browser
    if _browser is not None and _browser.is_connected():
        return _browser
    try:
        if _browser:
            _browser.close()
    except Exception:
        pass
    try:
        if _pw_instance:
            _pw_instance.stop()
    except Exception:
        pass
    _pw_instance = None
    _browser = None

    _pw_instance = sync_playwright().start()
    _browser = _pw_instance.chromium.launch(headless=True)
    log.info("Persistent Playwright browser launched on worker thread.")
    return _browser


def _browser_worker_loop():
    """Runs forever on the dedicated worker thread, processing one job at a time."""
    global _browser_init_failed, _browser, _pw_instance
    while True:
        task_fn, fut = _job_queue.get()
        if task_fn is None:   # shutdown sentinel
            try:
                if _browser:
                    _browser.close()
            except Exception:
                pass
            try:
                if _pw_instance:
                    _pw_instance.stop()
            except Exception:
                pass
            log.info("Persistent browser shut down cleanly.")
            break
        try:
            browser = _launch_or_reuse_browser()
        except Exception as exc:
            log.error(
                "Failed to launch persistent browser: %s — disabling persistence for this process.", exc
            )
            _browser_init_failed = True
            if not fut.cancelled():
                fut.set_result(None)
            continue
        try:
            result = task_fn(browser)
        except Exception as exc:
            log.warning("Persistent browser task failed: %s", exc)
            result = None
        if not fut.cancelled():
            fut.set_result(result)


def _ensure_worker_started():
    global _worker_thread
    if _worker_thread is not None and _worker_thread.is_alive():
        return
    with _browser_lock:
        if _worker_thread is not None and _worker_thread.is_alive():
            return
        t = threading.Thread(target=_browser_worker_loop, daemon=True, name="pw-persistent-worker")
        t.start()
        _worker_thread = t


def _run_on_persistent_browser(task_fn, timeout: float = WORKER_JOB_TIMEOUT):
    """
    Submit task_fn(browser) to the worker thread that owns the persistent
    browser. Returns task_fn's result, or None if persistence is disabled,
    the launch failed, or the job timed out — callers treat None as "fall
    back to a fresh browser for this call."
    """
    if _browser_init_failed:
        return None
    _ensure_worker_started()
    fut: Future = Future()
    _job_queue.put((task_fn, fut))
    try:
        return fut.result(timeout=timeout)
    except FutureTimeoutError:
        log.warning("Persistent browser worker timed out — falling back to fresh browser for this call.")
        fut.cancel()
        return None


def _fetch_json_with_browser(browser, url: str) -> dict | None:
    """Fetch a ?fo=json URL using the shared persistent browser."""
    context = None
    try:
        context = browser.new_context(
            viewport={"width": 1280, "height": 900},
            user_agent=DL_HEADERS["User-Agent"],
            locale="en-US",
        )
        page = context.new_page()
        log.info("Persistent browser → %s", url)
        page.goto(url, wait_until="domcontentloaded", timeout=PAGE_TIMEOUT)
        try:
            page.wait_for_function(
                "() => document.title !== 'Just a moment...'",
                timeout=SELECTOR_WAIT,
            )
        except PWTimeout:
            log.warning("Cloudflare challenge may not have resolved for %s", url)
        page.wait_for_timeout(1500)
        body_text = page.inner_text("body").strip()
        return json.loads(body_text)
    except json.JSONDecodeError as exc:
        log.warning("Persistent browser JSON parse failed for %s: %s", url, exc)
        return None
    except Exception as exc:
        log.warning("Persistent browser fetch failed for %s: %s", url, exc)
        return None
    finally:
        try:
            if context:
                context.close()
        except Exception:
            pass


def _fetch_json_fresh(url: str) -> dict | None:
    """
    Original implementation: launches a fresh Playwright browser per call.
    Used as fallback when the persistent browser is unavailable or fails.
    """
    pw = browser = None
    try:
        pw = sync_playwright().start()
        browser = pw.chromium.launch(headless=True)
        context = browser.new_context(
            viewport={"width": 1280, "height": 900},
            user_agent=DL_HEADERS["User-Agent"],
            locale="en-US",
        )
        page = context.new_page()
        log.info("Fresh browser → %s", url)

        page.goto(url, wait_until="domcontentloaded", timeout=PAGE_TIMEOUT)

        # Wait for Cloudflare challenge to resolve and real content to appear.
        # The challenge page has <title>Just a moment...</title>.
        # We wait until that's gone or a timeout occurs.
        try:
            page.wait_for_function(
                "() => document.title !== 'Just a moment...'",
                timeout=SELECTOR_WAIT,
            )
        except PWTimeout:
            log.warning("Cloudflare challenge may not have resolved for %s", url)

        # Extra settle time for JS to finish rendering the JSON
        page.wait_for_timeout(1500)

        # The page body text IS the JSON when ?fo=json is used
        body_text = page.inner_text("body")

        # Strip any whitespace/BOM
        body_text = body_text.strip()

        data = json.loads(body_text)
        return data

    except json.JSONDecodeError as exc:
        # Body was HTML (Cloudflare block or error page), not JSON
        log.warning("JSON parse failed for %s — may still be blocked: %s", url, exc)
        return None
    except Exception as exc:
        log.warning("Browser fetch failed for %s: %s", url, exc)
        return None
    finally:
        try:
            if browser:
                browser.close()
        except Exception:
            pass
        try:
            if pw:
                pw.stop()
        except Exception:
            pass


def _fetch_json(url: str) -> dict | None:
    """
    Fetch a loc.gov ?fo=json URL, return parsed JSON (or None).
    Tries the persistent browser first; falls back to a fresh browser-per-
    call if the persistent browser is unavailable or fails.
    """
    time.sleep(INTER_DELAY)

    data = _run_on_persistent_browser(lambda browser: _fetch_json_with_browser(browser, url))
    if data is not None:
        return data

    return _fetch_json_fresh(url)


def _shutdown_browser():
    if _worker_thread is not None and _worker_thread.is_alive():
        _job_queue.put((None, None))
        _worker_thread.join(timeout=10)


atexit.register(_shutdown_browser)


# ---------------------------------------------------------------------------
# Parsing helpers
# ---------------------------------------------------------------------------
def _parse_results(data: dict) -> list[dict]:
    """Parse the results array from a LOC search API response."""
    results = []
    for item in data.get("results", []):
        try:
            item_id = (item.get("id") or "").strip().rstrip("/")
            if not item_id:
                continue

            # id uses http:// historically — normalise
            item_id = item_id.replace("http://", "https://")
            slug = item_id.rstrip("/").split("/")[-1]

            title = (item.get("title") or "").strip() or slug
            date  = (item.get("date") or "").strip()

            contributors = item.get("contributor") or []
            if isinstance(contributors, str):
                contributors = [contributors]

            image_urls  = item.get("image_url") or []
            preview_url = image_urls[0] if image_urls else None

            results.append({
                "id":               slug,
                "title":            f"{title} ({date})" if date else title,
                "media_type":       "image",
                "preview_url":      preview_url,
                "download_url":     f"http://127.0.0.1:{PORT}/download?id={slug}",
                "width":            None,
                "height":           None,
                "duration_seconds": None,
                "file_size_bytes":  None,
                "source_page_url":  f"https://www.loc.gov/item/{slug}/",
                "_item_url":        f"{BASE_URL}/item/{slug}/?fo=json",
            })
        except Exception as exc:
            log.warning("Skipped result: %s", exc)
    return results


def _best_image_file(resources: list) -> dict | None:
    """
    Find the best full-res image file from a LOC item's resources list.

    resources[].files is a nested list (list of lists) of file objects.
    Each file has: url, mimetype, width, height, size.

    Strategy: pick the largest JPEG by pixel area, skipping TIFFs.
    """
    candidates = []
    for resource in resources:
        for file_group in (resource.get("files") or []):
            if not isinstance(file_group, list):
                file_group = [file_group]
            for f in file_group:
                url  = (f.get("url") or "").strip()
                mime = (f.get("mimetype") or "").lower()
                if not url:
                    continue
                if "tiff" in mime or url.lower().endswith((".tif", ".tiff")):
                    continue
                if "image" in mime or url.lower().endswith((".jpg", ".jpeg", ".png")):
                    w    = f.get("width")  or 0
                    h    = f.get("height") or 0
                    size = f.get("size")   or 0
                    candidates.append({
                        "url": url, "width": w, "height": h,
                        "size": size, "area": w * h,
                    })

    if not candidates:
        return None

    candidates.sort(key=lambda f: (f["area"], f["size"]), reverse=True)
    return candidates[0]


# ---------------------------------------------------------------------------
# Slug → item URL cache
# ---------------------------------------------------------------------------
_slug_cache: dict[str, str] = {}


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@app.route("/health")
def health():
    return jsonify({
        "status":      "ok",
        "name":        "Library of Congress Adapter",
        "version":     "1.1",
        "description": (
            "Historical photos, prints, drawings and illustrations "
            "from the Library of Congress (loc.gov). No API key required."
        ),
    })


@app.route("/search")
def search():
    _check_auth()

    q          = request.args.get("q", "").strip()
    limit      = min(int(request.args.get("limit", 10)), 50)
    media_type = request.args.get("media_type", "any")

    if not q:
        return jsonify({"results": [], "error": "Query parameter 'q' is required"}), 400
    if media_type == "video":
        return jsonify({"results": []})

    results = []
    page    = 1

    while len(results) < limit and page <= MAX_PAGES:
        url  = f"{BASE_URL}/photos/"
        # Build URL with all params including fo=json
        full_url = (
            f"{url}?q={requests.utils.quote(q)}"
            f"&c={RESULTS_PER_PG}&sp={page}&fo=json"
        )
        log.info("Searching page %d: %s", page, full_url)

        data = _fetch_json(full_url)
        if not data:
            break

        page_results = _parse_results(data)
        if not page_results:
            log.info("No results on page %d — stopping", page)
            break

        results.extend(page_results)

        pagination = data.get("pagination") or {}
        if not pagination.get("next"):
            break

        page += 1

    # Cache and strip internal fields
    for r in results:
        item_url = r.pop("_item_url", None)
        if item_url:
            _slug_cache[r["id"]] = item_url

    results = results[:limit]
    log.info("Returning %d results for '%s'", len(results), q)
    return jsonify({"results": results})


@app.route("/download")
def download():
    _check_auth()

    item_id = request.args.get("id", "").strip()
    if not item_id:
        return jsonify({"error": "Missing 'id' parameter"}), 400

    item_url = _slug_cache.get(item_id, f"{BASE_URL}/item/{item_id}/?fo=json")
    log.info("Fetching item metadata for '%s' from %s", item_id, item_url)

    data = _fetch_json(item_url)
    if not data:
        return jsonify({"error": f"Could not fetch item metadata for '{item_id}'"}), 404

    resources = data.get("resources") or []
    if not resources:
        return jsonify({"error": f"No downloadable resources for '{item_id}'"}), 404

    best = _best_image_file(resources)
    if not best:
        return jsonify({"error": f"No suitable image file found for '{item_id}'"}), 404

    image_url = best["url"]
    log.info(
        "Downloading: %s  (%sx%s, %s bytes)",
        image_url, best["width"], best["height"], best["size"],
    )

    # Image CDN (cdn.loc.gov) is NOT behind Cloudflare — plain requests works
    try:
        resp = requests.get(image_url, headers=DL_HEADERS, timeout=60, stream=True)
        resp.raise_for_status()

        content_type = resp.headers.get("Content-Type", "image/jpeg")
        if "text/html" in content_type:
            return jsonify({"error": "CDN returned HTML instead of image"}), 502

        ext = image_url.rsplit(".", 1)[-1].split("?")[0].lower()
        if ext not in ("jpg", "jpeg", "png"):
            ext = "jpg"

        return send_file(
            io.BytesIO(resp.content),
            mimetype=content_type,
            download_name=f"{item_id}.{ext}",
        )
    except Exception as exc:
        log.error("Image download failed: %s", exc)
        return jsonify({"error": str(exc)}), 502


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    print("=" * 58)
    print("  Library of Congress Adapter  v1.1")
    print(f"  http://localhost:{PORT}")
    print("=" * 58)
    print()
    print("  Test with:")
    print(f"    curl http://localhost:{PORT}/health")
    print(f'    curl "http://localhost:{PORT}/search?q=ancient+persia&limit=5"')
    print(f'    curl "http://localhost:{PORT}/download?id=<id from search>" -o out.jpg')
    print()
    app.run(host="0.0.0.0", port=PORT, debug=False, threaded=True)