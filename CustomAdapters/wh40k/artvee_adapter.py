"""
artvee_adapter.py  —  B-Roll Engine Custom Adapter for artvee.com  v1.1
=======================================================================
Artvee hosts thousands of public domain artworks from major museums.
No API key or login required to browse or download.

Search URL:   https://artvee.com/?s=<query>
Category URL: https://artvee.com/c/<category>/
Topic URL:    https://artvee.com/topics/<slug>/

HTML structure (confirmed from live dump, 2026-06-25):
  Search results — <article> tags with rich CSS class metadata:
    - Slug/page URL: h3.entry-title a[href]
    - Title:         h3.entry-title a (text)
    - Artist:        CSS class pa_artist-<slug>
    - Category:      CSS class product_cat-<name>
    - Culture:       CSS class pa_culture-<name>
    NOTE: no thumbnail images present in search result card HTML.

  Artwork page (/dl/<slug>/):
    - Preview:       div.product-images img[src]  → mdl.artvee.com/sftb/<id>il.jpg
    - Download URL:  a.snax-action-add-to-collection-downloads[href]
                     → pre-signed S3 URL at mdl.artvee.com/sdl/
    - Artist link:   a[href*="/artist/"] (first match)
    - Title:         h1.product_title

  IMPORTANT — S3 signed URL must be fetched using the same Playwright browser
  context that loaded the page. Hitting it with a separate requests.get() call
  returns 403 Forbidden because S3 validates the Host header against the
  signature. _fetch_artwork_and_download() handles both steps in one session.

Run:
    pip install flask requests beautifulsoup4 playwright
    playwright install chromium
    python artvee_adapter.py

Port: 3001  (avoids conflict with 40k adapter on 3000)
"""

import atexit
import io
import queue
import threading
import time
import logging
from concurrent.futures import Future, TimeoutError as FutureTimeoutError

from bs4 import BeautifulSoup
from flask import Flask, jsonify, request, send_file, abort
from playwright.sync_api import sync_playwright, TimeoutError as PWTimeout

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------
BASE_URL  = "https://artvee.com"
PORT      = 3001

BROWSER_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/124.0.0.0 Safari/537.36"
)

PAGE_TIMEOUT  = 25_000   # ms
SELECTOR_WAIT =  8_000   # ms
INTER_DELAY   =    1.2   # seconds between page fetches
MAX_PAGES     =      5   # max search result pages to paginate

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
#
# artvee's download flow (_fetch_artwork_and_download) must navigate the
# page AND fetch the signed S3 URL through the SAME browser context (see
# the docstring below for why) — so the "job" submitted to the worker is a
# whole task function, not just a URL, letting both adapter operations
# (search-page fetch, page+download fetch) share the one worker/queue.
# ---------------------------------------------------------------------------

_browser_lock = threading.Lock()          # guards worker-thread startup only
_job_queue: "queue.Queue" = queue.Queue()
_worker_thread: threading.Thread | None = None
_browser_init_failed = False              # True disables persistence for this process
_pw_instance = None
_browser = None

WORKER_JOB_TIMEOUT = 45.0          # seconds — ceiling for a plain page fetch
DOWNLOAD_JOB_TIMEOUT = 90.0        # seconds — page nav + S3 download can take longer


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


def _make_context(pw):
    """Fresh-mode helper: launch a standalone browser+context (not the persistent one)."""
    browser = pw.chromium.launch(headless=True)
    context = browser.new_context(
        viewport={"width": 1280, "height": 900},
        user_agent=BROWSER_UA,
        locale="en-US",
    )
    return browser, context


def _fetch_html_with_browser(browser, url: str) -> str | None:
    """Fetch `url` using the shared persistent browser. Returns raw HTML or None."""
    context = None
    try:
        context = browser.new_context(
            viewport={"width": 1280, "height": 900},
            user_agent=BROWSER_UA,
            locale="en-US",
        )
        page = context.new_page()
        log.info("Persistent browser → %s", url)
        page.goto(url, wait_until="domcontentloaded", timeout=PAGE_TIMEOUT)
        try:
            page.wait_for_selector("article, h1.product_title", timeout=SELECTOR_WAIT)
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


def _fetch_html_fresh(url: str) -> BeautifulSoup | None:
    """Load url in a fresh browser, return BeautifulSoup. Used as fallback."""
    pw = browser = None
    try:
        pw = sync_playwright().start()
        browser, context = _make_context(pw)
        page = context.new_page()
        log.info("Fresh browser → %s", url)
        page.goto(url, wait_until="domcontentloaded", timeout=PAGE_TIMEOUT)
        try:
            page.wait_for_selector("article, h1.product_title", timeout=SELECTOR_WAIT)
        except PWTimeout:
            pass
        return BeautifulSoup(page.content(), "html.parser")
    except Exception as exc:
        log.warning("Browser fetch failed for %s: %s", url, exc)
        return None
    finally:
        try:
            if browser: browser.close()
        except Exception:
            pass
        try:
            if pw: pw.stop()
        except Exception:
            pass


def _fetch_html(url: str) -> BeautifulSoup | None:
    """
    Fetch `url`, return a BeautifulSoup of the rendered HTML (or None).
    Tries the persistent browser first; falls back to a fresh browser-per-
    call if the persistent browser is unavailable or fails.
    """
    time.sleep(INTER_DELAY)

    html = _run_on_persistent_browser(lambda browser: _fetch_html_with_browser(browser, url))
    if html is not None:
        return BeautifulSoup(html, "html.parser")

    return _fetch_html_fresh(url)


def _fetch_artwork_and_download_with_browser(browser, page_url: str) -> dict:
    """
    Same logic as _fetch_artwork_and_download_fresh, but uses a context
    created from the shared persistent browser. See that function's
    docstring for why page-load and S3 download must share one context.
    """
    context = None
    try:
        context = browser.new_context(
            viewport={"width": 1280, "height": 900},
            user_agent=BROWSER_UA,
            locale="en-US",
        )
        page = context.new_page()

        log.info("Persistent browser → %s", page_url)
        page.goto(page_url, wait_until="domcontentloaded", timeout=PAGE_TIMEOUT)
        try:
            page.wait_for_selector(
                "h1.product_title, a.snax-action-add-to-collection-downloads",
                timeout=SELECTOR_WAIT,
            )
        except PWTimeout:
            pass

        soup = BeautifulSoup(page.content(), "html.parser")

        dl_anchor = soup.select_one("a.snax-action-add-to-collection-downloads")
        full_url  = dl_anchor.get("href", "").strip() if dl_anchor else ""
        if not full_url:
            log.warning("No download anchor on %s", page_url)
            return {}

        preview_img = soup.select_one("div.product-images img")
        preview_url = preview_img.get("src", "").strip() if preview_img else ""

        artist_a  = soup.select_one('a[href*="/artist/"]')
        artist    = artist_a.get_text(strip=True) if artist_a else ""
        title_tag = soup.select_one("h1.product_title, h1.entry-title")
        title     = title_tag.get_text(strip=True) if title_tag else ""

        log.info("Downloading via browser context: %s ...", full_url[:80])
        api_resp = context.request.get(
            full_url,
            headers={"Referer": page_url},
            timeout=30_000,
        )

        if not api_resp.ok:
            log.error("S3 download returned HTTP %d", api_resp.status)
            return {}

        image_bytes  = api_resp.body()
        content_type = api_resp.headers.get("content-type", "image/jpeg")

        if image_bytes[:15].lstrip().startswith(b"<"):
            log.error("Download returned HTML, not an image")
            return {}

        ext = full_url.split("?")[0].rsplit(".", 1)[-1].lower()
        if ext not in ("jpg", "jpeg", "png", "webp"):
            ext = "jpg"

        log.info("Download OK — %d KB", len(image_bytes) // 1024)
        return {
            "image_bytes":  image_bytes,
            "content_type": content_type,
            "ext":          ext,
            "preview_url":  preview_url,
            "artist":       artist,
            "title":        title,
        }
    except Exception as exc:
        log.error("Persistent artwork fetch/download failed for %s: %s", page_url, exc)
        return {}
    finally:
        try:
            if context:
                context.close()
        except Exception:
            pass


def _fetch_artwork_and_download_fresh(page_url: str) -> dict:
    """
    Fetch an artwork page AND download the image in a single fresh browser
    session. Used as fallback when the persistent browser is unavailable
    or fails.

    WHY ONE SESSION: Artvee serves full-res images via AWS S3 pre-signed URLs.
    The signature covers the Host header (X-Amz-SignedHeaders=host). If we
    fetch the page with Playwright then download with a separate requests.get(),
    the request headers differ enough that S3 returns 403 Forbidden. Using
    context.request.get() inside the same Playwright context sends the same
    headers that were used when the page loaded, so the signature validates.

    Returns dict with keys: image_bytes, content_type, ext, preview_url,
    artist, title. Returns empty dict on any failure.
    """
    pw = browser = None
    try:
        pw = sync_playwright().start()
        browser, context = _make_context(pw)
        page = context.new_page()

        log.info("Fresh browser → %s", page_url)
        page.goto(page_url, wait_until="domcontentloaded", timeout=PAGE_TIMEOUT)
        try:
            page.wait_for_selector(
                "h1.product_title, a.snax-action-add-to-collection-downloads",
                timeout=SELECTOR_WAIT,
            )
        except PWTimeout:
            pass

        soup = BeautifulSoup(page.content(), "html.parser")

        # Signed S3 download URL
        dl_anchor = soup.select_one("a.snax-action-add-to-collection-downloads")
        full_url  = dl_anchor.get("href", "").strip() if dl_anchor else ""
        if not full_url:
            log.warning("No download anchor on %s", page_url)
            return {}

        # Preview thumbnail (no auth needed — different CDN path)
        preview_img = soup.select_one("div.product-images img")
        preview_url = preview_img.get("src", "").strip() if preview_img else ""

        # Artist and title
        artist_a  = soup.select_one('a[href*="/artist/"]')
        artist    = artist_a.get_text(strip=True) if artist_a else ""
        title_tag = soup.select_one("h1.product_title, h1.entry-title")
        title     = title_tag.get_text(strip=True) if title_tag else ""

        # Download using the browser's own request context so headers match
        log.info("Downloading via browser context: %s ...", full_url[:80])
        api_resp = context.request.get(
            full_url,
            headers={"Referer": page_url},
            timeout=30_000,
        )

        if not api_resp.ok:
            log.error("S3 download returned HTTP %d", api_resp.status)
            return {}

        image_bytes  = api_resp.body()
        content_type = api_resp.headers.get("content-type", "image/jpeg")

        # Guard against getting an HTML error page instead of image bytes
        if image_bytes[:15].lstrip().startswith(b"<"):
            log.error("Download returned HTML, not an image")
            return {}

        ext = full_url.split("?")[0].rsplit(".", 1)[-1].lower()
        if ext not in ("jpg", "jpeg", "png", "webp"):
            ext = "jpg"

        log.info("Download OK — %d KB", len(image_bytes) // 1024)
        return {
            "image_bytes":  image_bytes,
            "content_type": content_type,
            "ext":          ext,
            "preview_url":  preview_url,
            "artist":       artist,
            "title":        title,
        }

    except Exception as exc:
        log.error("Artwork fetch/download failed for %s: %s", page_url, exc)
        return {}
    finally:
        try:
            if browser: browser.close()
        except Exception:
            pass
        try:
            if pw: pw.stop()
        except Exception:
            pass


def _fetch_artwork_and_download(page_url: str) -> dict:
    """
    Fetch an artwork page and download the image. Tries the persistent
    browser first; falls back to a fresh browser-per-call session if the
    persistent browser is unavailable or fails.
    """
    time.sleep(INTER_DELAY)

    result = _run_on_persistent_browser(
        lambda browser: _fetch_artwork_and_download_with_browser(browser, page_url),
        timeout=DOWNLOAD_JOB_TIMEOUT,
    )
    if result is not None:
        return result

    return _fetch_artwork_and_download_fresh(page_url)


def _shutdown_browser():
    if _worker_thread is not None and _worker_thread.is_alive():
        _job_queue.put((None, None))
        _worker_thread.join(timeout=10)


atexit.register(_shutdown_browser)


# ---------------------------------------------------------------------------
# Parsing — search results
# ---------------------------------------------------------------------------
def _parse_cards(soup: BeautifulSoup) -> list[dict]:
    """
    Parse <article> tags from a search/category page.

    All metadata is in the article's CSS class attribute — no child-element
    parsing needed for artist/category/culture. No thumbnail URLs exist in
    search result HTML; preview_url is populated later at download time.
    """
    results = []
    for article in soup.select("article"):
        try:
            title_tag = article.select_one("h3.entry-title a, h2.entry-title a")
            if not title_tag:
                continue

            page_url = title_tag.get("href", "").strip()
            slug     = page_url.rstrip("/").split("/")[-1]
            title    = title_tag.get_text(strip=True)
            classes  = article.get("class", [])

            def _extract(prefix):
                matches = [c for c in classes if c.startswith(prefix)]
                return matches[0].replace(prefix, "").replace("-", " ").title() if matches else ""

            artist   = _extract("pa_artist-")
            category = _extract("product_cat-")

            results.append({
                "id":               slug,
                "title":            f"{title} — {artist}" if artist else title,
                "media_type":       "image",
                "preview_url":      None,   # populated on /download
                "download_url":     f"http://127.0.0.1:{PORT}/download?id={slug}",
                "width":            None,
                "height":           None,
                "duration_seconds": None,
                "file_size_bytes":  None,
                "source_page_url":  page_url,
                "_page_url":        page_url,
            })
        except Exception as exc:
            log.warning("Skipped card: %s", exc)
    return results


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
        "name":        "artvee.com Adapter",
        "version":     "1.1",
        "description": "Public domain artworks from artvee.com (museums, historical art, illustrations)",
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
    q_enc   = q.replace(" ", "+")

    # Strategy 1 — keyword search
    log.info("Searching: /?s=%s", q)
    soup = _fetch_html(f"{BASE_URL}/?s={q_enc}")
    if soup:
        results.extend(_parse_cards(soup))
        total = _total_pages(soup)
        pg = 2
        while len(results) < limit and pg <= total and pg <= MAX_PAGES:
            log.info("Search page %d / %d", pg, total)
            s = _fetch_html(f"{BASE_URL}/page/{pg}/?s={q_enc}")
            if not s:
                break
            results.extend(_parse_cards(s))
            pg += 1

    # Strategy 2 — category fallback
    if not results:
        log.info("Trying category: /c/%s/", slug)
        s = _fetch_html(f"{BASE_URL}/c/{slug}/")
        if s:
            results.extend(_parse_cards(s))

    # Strategy 3 — topic fallback
    if not results:
        log.info("Trying topic: /topics/%s/", slug)
        s = _fetch_html(f"{BASE_URL}/topics/{slug}/")
        if s:
            results.extend(_parse_cards(s))

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

    page_url = _slug_cache.get(item_id, f"{BASE_URL}/dl/{item_id}/")
    log.info("Fetching artwork for '%s' from %s", item_id, page_url)

    result = _fetch_artwork_and_download(page_url)
    if not result:
        return jsonify({"error": f"Could not fetch or download artwork for '{item_id}'"}), 404

    return send_file(
        io.BytesIO(result["image_bytes"]),
        mimetype=result["content_type"] or "image/jpeg",
        download_name=f"{item_id}.{result['ext']}",
    )


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    print("=" * 58)
    print("  artvee.com B-Roll Engine Adapter  v1.1")
    print(f"  http://localhost:{PORT}")
    print("=" * 58)
    print()
    print("  Test with:")
    print(f"    curl http://localhost:{PORT}/health")
    print(f'    curl "http://localhost:{PORT}/search?q=persia&limit=5"')
    print(f'    curl "http://localhost:{PORT}/download?id=persia-antiquity" -o out.jpg')
    print()
    app.run(host="0.0.0.0", port=PORT, debug=False, threaded=True)
