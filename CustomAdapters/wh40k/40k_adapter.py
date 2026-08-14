import atexit
import io
import queue
import re
import threading
import time
import logging
from concurrent.futures import Future, TimeoutError as FutureTimeoutError

import requests
from bs4 import BeautifulSoup
from flask import Flask, jsonify, request, send_file, abort
from playwright.sync_api import sync_playwright, TimeoutError as PWTimeout

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------
BASE_URL    = "https://40k.gallery"
ARTWORK_CDN = "https://artwork.40k.gallery"

# Used only for direct CDN image downloads (no Cloudflare there)
DL_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "en-US,en;q=0.9",
}

REQUEST_TIMEOUT  = 20_000   # ms — Playwright page.goto timeout
INTER_PAGE_DELAY = 1.0      # seconds between browser page loads (be polite)

app = Flask(__name__)
logging.basicConfig(level=logging.INFO, format="%(levelname)s  %(message)s")
log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Optional auth
# ---------------------------------------------------------------------------
AUTH_TOKEN = None   # set to a string to require a Bearer token

def _check_auth():
    if AUTH_TOKEN is None:
        return
    if request.headers.get("Authorization", "") != f"Bearer {AUTH_TOKEN}":
        abort(401, description="Unauthorized")


# ---------------------------------------------------------------------------
# Playwright browser
# ---------------------------------------------------------------------------
# IMPORTANT: Playwright's sync API is NOT thread-safe — a browser/context
# created on one thread cannot be used from another thread (it crashes with
# "greenlet.error: cannot switch to a different thread"). Flask's dev server
# (threaded=True, the default) hands each request to a fresh worker thread,
# so a persistent browser cannot simply be shared behind a lock — the lock
# would only serialise access, not pin execution to one thread.
#
# Fix: a single dedicated background thread owns the persistent browser
# exclusively. All Flask request threads submit "run this on the browser"
# jobs to it via a queue and block on a Future for the result — the browser
# itself is only ever touched from the one thread that created it. If the
# browser can't be launched at all, persistence is disabled for the rest of
# this process and every call falls back to the original fresh-browser-
# per-call path below.

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
    _browser = _pw_instance.chromium.launch(
        headless=True,
        args=["--no-sandbox", "--disable-blink-features=AutomationControlled"],
    )
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


def _fetch_html_with_browser(browser, url: str) -> str | None:
    """Fetch `url` using the shared persistent browser. Returns raw HTML or None."""
    context = None
    try:
        context = browser.new_context(
            viewport={"width": 1280, "height": 900},
            user_agent=(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/124.0.0.0 Safari/537.36"
            ),
            locale="en-US",
        )
        context.add_init_script(
            "Object.defineProperty(navigator, 'webdriver', {get: () => undefined})"
        )
        page = context.new_page()
        log.info("Persistent browser → %s", url)
        page.goto(url, wait_until="domcontentloaded", timeout=REQUEST_TIMEOUT)
        try:
            page.wait_for_selector("div.cog-post-box, div#main-content", timeout=8_000)
        except PWTimeout:
            pass
        return page.content()
    except Exception as exc:
        log.warning("Persistent browser fetch failed for %s: %s", url, exc)
        return None
    finally:
        try:
            if context:
                context.close()
        except Exception:
            pass


def _fetch_html_fresh(url: str):
    """
    Original implementation: launches a fresh Playwright browser per call,
    tears it down fully afterwards. Used as fallback when the persistent
    browser is unavailable or fails.
    """
    pw = None
    browser = None
    try:
        pw = sync_playwright().start()
        browser = pw.chromium.launch(
            headless=True,
            args=[
                "--no-sandbox",
                "--disable-blink-features=AutomationControlled",
            ],
        )
        context = browser.new_context(
            viewport={"width": 1280, "height": 900},
            user_agent=(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/124.0.0.0 Safari/537.36"
            ),
            locale="en-US",
        )
        # Hide navigator.webdriver — the flag Cloudflare checks to detect automation
        context.add_init_script(
            "Object.defineProperty(navigator, 'webdriver', {get: () => undefined})"
        )
        page = context.new_page()

        log.info("Fresh browser → %s", url)
        page.goto(url, wait_until="domcontentloaded", timeout=REQUEST_TIMEOUT)

        # Wait for artwork cards or a recognisable page element
        try:
            page.wait_for_selector("div.cog-post-box, div#main-content", timeout=8_000)
        except PWTimeout:
            pass  # page may still be usable

        html = page.content()
        return BeautifulSoup(html, "html.parser")

    except Exception as exc:
        log.warning("Browser fetch failed for %s: %s", url, exc)
        return None
    finally:
        try:
            if browser is not None:
                browser.close()
        except Exception:
            pass
        try:
            if pw is not None:
                pw.stop()
        except Exception:
            pass


def _fetch_html(url: str, params: dict = None):
    """
    Fetch `url`, return a BeautifulSoup of the rendered HTML (or None).
    Tries the persistent browser first; falls back to a fresh browser-per-
    call if the persistent browser is unavailable or fails.
    """
    if params:
        qs = "&".join(f"{k}={v}" for k, v in params.items())
        url = f"{url}?{qs}"

    time.sleep(INTER_PAGE_DELAY)

    html = _run_on_persistent_browser(lambda browser: _fetch_html_with_browser(browser, url))
    if html is not None:
        return BeautifulSoup(html, "html.parser")

    return _fetch_html_fresh(url)


def _shutdown_browser():
    if _worker_thread is not None and _worker_thread.is_alive():
        _job_queue.put((None, None))
        _worker_thread.join(timeout=10)


atexit.register(_shutdown_browser)


# ---------------------------------------------------------------------------
# Parsing helpers  (unchanged from original)
# ---------------------------------------------------------------------------

def _parse_dimensions_from_url(url: str):
    m = re.search(r"-(\d+)x(\d+)\.\w+$", url)
    return (int(m.group(1)), int(m.group(2))) if m else (None, None)


def _safe_int(val):
    try:
        return int(val)
    except (TypeError, ValueError):
        return None


def _parse_cards(soup: BeautifulSoup) -> list[dict]:
    results = []
    for card in soup.select("div.cog-post-box"):
        try:
            link_tag = card.select_one("a.cog-post-img-link")
            if not link_tag:
                continue
            page_url = link_tag.get("href", "").strip()
            slug     = page_url.rstrip("/").split("/")[-1]

            img_tag   = card.select_one("img")
            thumb_url = (img_tag.get("data-src") or img_tag.get("src") or "").strip()
            alt_text  = (img_tag.get("alt") or img_tag.get("title") or "").strip()

            title_tag = card.select_one(".cog-post-title, .cog-post-name, h2, h3")
            title     = (title_tag.get_text(strip=True) if title_tag else alt_text) or slug

            # The artist's name lives inside an <a> tag nested in
            # .cog-post-artist; the div itself also contains the literal
            # label text "Artist" before a <br>, so selecting the div
            # directly produces mangled names like "ArtistJohn Smith".
            artist_tag = card.select_one(".cog-post-artist a")
            artist     = artist_tag.get_text(strip=True) if artist_tag else ""

            results.append({
                "id":               slug,
                "title":            f"{title} — {artist}" if artist else title,
                "media_type":       "image",
                "preview_url":      thumb_url,
                "download_url":     f"http://127.0.0.1:3000/download?id={slug}",
                "width":            None,
                "height":           None,
                "duration_seconds": None,
                "file_size_bytes":  None,
                "source_page_url":  page_url,
                "_page_url":        page_url,   # stripped before returning to client
            })
        except Exception as exc:
            log.warning("Skipped card: %s", exc)
    return results


def _get_full_res_url(page_url: str):
    soup = _fetch_html(page_url)
    if not soup:
        return "", None, None

    lightbox = soup.select_one("a.et_pb_lightbox_image")
    if lightbox:
        full_url = lightbox.get("href", "").strip()
        img = lightbox.select_one("img")
        if img:
            return full_url, _safe_int(img.get("width")), _safe_int(img.get("height"))

    for img in soup.select("img"):
        src = img.get("src") or img.get("data-src") or ""
        if ARTWORK_CDN in src and "-150x150" not in src:
            return src, _safe_int(img.get("width")), _safe_int(img.get("height"))

    return "", None, None


def _total_pages(soup: BeautifulSoup) -> int:
    nums = []
    for tag in soup.select(".page-numbers:not(.next):not(.prev)"):
        try:
            nums.append(int(tag.get_text(strip=True)))
        except ValueError:
            pass
    return max(nums) if nums else 1


# ---------------------------------------------------------------------------
# Slug → page_url cache
# ---------------------------------------------------------------------------
_slug_cache: dict[str, str] = {}


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@app.route("/health")
def health():
    return jsonify({
        "status":      "ok",
        "name":        "40k.gallery Adapter",
        "version":     "2.1",
        "description": "Scrapes Warhammer 40K artwork from https://40k.gallery/",
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
    slug    = q.lower().replace(" ", "-")

    # Strategy 1 — keyword search
    log.info("Searching: /?s=%s", q)
    soup = _fetch_html(f"{BASE_URL}/", params={"s": q})
    if soup:
        results.extend(_parse_cards(soup))
        total = _total_pages(soup)
        page  = 2
        while len(results) < limit and page <= total and page <= 5:
            log.info("Fetching search page %d", page)
            s = _fetch_html(f"{BASE_URL}/page/{page}/", params={"s": q})
            if not s:
                break
            results.extend(_parse_cards(s))
            page += 1

    # Strategy 2 — category fallback
    if not results:
        log.info("Trying category: /category/%s/", slug)
        s = _fetch_html(f"{BASE_URL}/category/{slug}/")
        if s:
            results.extend(_parse_cards(s))

    # Strategy 3 — tag fallback
    if not results:
        log.info("Trying tag: /tag/%s/", slug)
        s = _fetch_html(f"{BASE_URL}/tag/{slug}/")
        if s:
            results.extend(_parse_cards(s))

    # Cache & clean internal field
    for r in results:
        pu = r.pop("_page_url", None)
        if pu:
            _slug_cache[r["id"]] = pu

    results = results[:limit]
    log.info("Returning %d results for '%s'", len(results), q)
    return jsonify({"results": results})


@app.route("/download")
def download():
    _check_auth()

    item_id = request.args.get("id", "").strip()
    if not item_id:
        return jsonify({"error": "Missing 'id' parameter"}), 400

    page_url = _slug_cache.get(item_id, f"{BASE_URL}/{item_id}/")
    log.info("Fetching full-res for '%s' from %s", item_id, page_url)

    full_url, w, h = _get_full_res_url(page_url)
    if not full_url:
        # NOTE: this branch previously could be silently bypassed because
        # an unhandled exception inside _get_full_res_url (the cross-thread
        # Playwright crash) would skip straight to Flask's generic 500
        # handler instead of returning here. Now that _fetch_html always
        # cleans up and returns None on failure rather than raising, this
        # 404 path is reachable and correctly reports the real problem.
        return jsonify({"error": f"Could not find full-res image for '{item_id}'"}), 404

    log.info("Downloading full-res: %s (%sx%s)", full_url, w, h)
    try:
        resp = requests.get(full_url, headers=DL_HEADERS, timeout=20, stream=True)
        resp.raise_for_status()
        ext      = full_url.rsplit(".", 1)[-1].split("?")[0].lower()
        filename = f"{item_id}.{ext}"
        return send_file(
            io.BytesIO(resp.content),
            mimetype=resp.headers.get("Content-Type", "image/jpeg"),
            download_name=filename,
        )
    except Exception as exc:
        log.error("Download failed: %s", exc)
        return jsonify({"error": str(exc)}), 502


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    print("=" * 55)
    print("  40k.gallery B-Roll Engine Adapter  v2.1")
    print("  http://localhost:3000")
    print("=" * 55)
    print()
    print("  Test with:")
    print("    curl http://localhost:3000/health")
    print('    curl "http://localhost:3000/search?q=ultramarines&limit=5"')
    print('    curl "http://localhost:3000/download?id=ultramarines-32" -o out.jpg')
    print()
    # threaded=True (Flask's default) is fine: the persistent browser is
    # only ever touched from its own dedicated worker thread (see
    # _browser_worker_loop above); request threads only submit jobs to it
    # via a queue and never touch the Browser/Context objects directly.
    app.run(host="0.0.0.0", port=3000, debug=False, threaded=True)
