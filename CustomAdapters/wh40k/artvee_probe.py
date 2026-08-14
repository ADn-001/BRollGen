"""
artvee_probe.py — Phase 1 probe for artvee.com
===============================================
Run this BEFORE building the real adapter. It:
  1. Connects to artvee.com and confirms the site is reachable
  2. Runs a keyword search for "persia" and dumps the rendered HTML
  3. Navigates to the first result's artwork page and dumps that HTML
  4. Attempts to download the full-res image from that artwork page
  5. Logs every step clearly so you can see exactly what happened

Outputs (all written to ./artvee_probe_output/):
  search_dump.html      — rendered HTML of the search results page
  artwork_dump.html     — rendered HTML of the first artwork's page
  console.log           — every browser console message captured
  out.<ext>             — the downloaded image (or a .txt error file)

Usage:
  pip install playwright requests beautifulsoup4
  playwright install chromium
  python artvee_probe.py
"""

import os
import re
import time
import logging
import requests
from pathlib import Path
from bs4 import BeautifulSoup
from playwright.sync_api import sync_playwright, TimeoutError as PWTimeout

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------
BASE_URL       = "https://artvee.com"
SEARCH_QUERY   = "persia"          # primary search term
FALLBACK_QUERY = "iran"            # tried if primary returns nothing
OUTPUT_DIR     = Path("./artvee_probe_output")
PAGE_TIMEOUT   = 25_000            # ms for page.goto
SELECTOR_WAIT  = 10_000            # ms for waiting on a key element
INTER_DELAY    = 1.5               # seconds between requests

UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/124.0.0.0 Safari/537.36"
)

DL_HEADERS = {
    "User-Agent": UA,
    "Accept-Language": "en-US,en;q=0.9",
}

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
console_messages = []   # collected browser console messages


def _make_browser_context(pw):
    browser = pw.chromium.launch(headless=True)
    context = browser.new_context(
        viewport={"width": 1280, "height": 900},
        user_agent=UA,
        locale="en-US",
    )
    return browser, context


def _attach_console_listener(page):
    """Capture every browser console message to console_messages list."""
    def on_console(msg):
        entry = f"[{msg.type.upper()}] {msg.text}"
        console_messages.append(entry)
        log.debug("BROWSER CONSOLE: %s", entry)
    page.on("console", on_console)


def _fetch_page(context, url, wait_selector=None):
    """
    Navigate to url in a new page, wait for wait_selector if given,
    return (page, soup). Caller is responsible for closing the page.
    """
    page = context.new_page()
    _attach_console_listener(page)
    log.info("→ Navigating to: %s", url)
    try:
        page.goto(url, wait_until="domcontentloaded", timeout=PAGE_TIMEOUT)
    except PWTimeout:
        log.warning("Page load timed out (domcontentloaded) — continuing anyway")

    if wait_selector:
        log.info("  Waiting for selector: %s", wait_selector)
        try:
            page.wait_for_selector(wait_selector, timeout=SELECTOR_WAIT)
            log.info("  Selector found ✓")
        except PWTimeout:
            log.warning("  Selector '%s' not found within timeout — page may be empty or structure differs", wait_selector)

    # Extra settle time for any lazy-load / JS rendering
    time.sleep(1.5)
    html = page.content()
    soup = BeautifulSoup(html, "html.parser")
    return page, soup


def _save_html(soup, filename):
    path = OUTPUT_DIR / filename
    path.write_text(str(soup), encoding="utf-8")
    log.info("  HTML saved → %s (%d bytes)", path, path.stat().st_size)
    return path


def _save_console_log():
    path = OUTPUT_DIR / "console.log"
    path.write_text("\n".join(console_messages) if console_messages else "(no console messages captured)", encoding="utf-8")
    log.info("Console log saved → %s (%d entries)", path, len(console_messages))


# ---------------------------------------------------------------------------
# Step 1 — health check
# ---------------------------------------------------------------------------
def step1_health_check():
    log.info("=" * 60)
    log.info("STEP 1 — Health check: can we reach artvee.com?")
    log.info("=" * 60)
    try:
        r = requests.get(BASE_URL, headers=DL_HEADERS, timeout=10)
        log.info("Plain HTTP GET %s → status %d", BASE_URL, r.status_code)
        if r.status_code == 200:
            log.info("  Site reachable via plain requests ✓")
            return True
        else:
            log.warning("  Non-200 status — site may require a real browser")
            return False
    except Exception as e:
        log.error("  Plain HTTP GET failed: %s", e)
        log.info("  Will still attempt with Playwright")
        return False


# ---------------------------------------------------------------------------
# Step 2 — search page
# ---------------------------------------------------------------------------
def step2_search(context, query):
    log.info("=" * 60)
    log.info("STEP 2 — Search for '%s'", query)
    log.info("=" * 60)

    # Artvee search URL — try the standard WordPress ?s= pattern first,
    # as well as the /search/ path some themes use
    search_url = f"{BASE_URL}/?s={query.replace(' ', '+')}"
    log.info("Trying search URL: %s", search_url)

    time.sleep(INTER_DELAY)
    page, soup = _fetch_page(context, search_url, wait_selector=None)

    # Dump the full rendered HTML regardless of what we find
    _save_html(soup, "search_dump.html")

    # Try to find result cards — log whatever class names / selectors exist
    # so Phase 2 can use them. We don't assume any particular structure.
    log.info("--- Inspecting search result page structure ---")

    # Check page title so we know if search redirected or showed results
    title = soup.find("title")
    log.info("  Page <title>: %s", title.get_text(strip=True) if title else "(none)")

    # Look for common gallery card patterns
    selectors_to_try = [
        "div.product",
        "li.product",
        "article",
        "div.product-grid-item",
        "div[class*='product']",
        "div[class*='artwork']",
        "div[class*='item']",
        "div[class*='card']",
        "div[class*='gallery']",
        "a[href*='/dl/']",           # Artvee download links
        "a[href*='/artwork/']",
        "figure",
    ]

    found_any = False
    for sel in selectors_to_try:
        hits = soup.select(sel)
        if hits:
            log.info("  Selector '%s' → %d match(es)", sel, len(hits))
            found_any = True
            # Print a snippet of the first match for inspection
            first_text = str(hits[0])[:300].replace("\n", " ")
            log.info("    First match snippet: %s ...", first_text)

    if not found_any:
        log.warning("  No known card selectors matched — site structure may be unusual. Check search_dump.html.")

    # Also log all unique class names in the page body for clues
    body = soup.find("body")
    if body:
        all_classes = set()
        for tag in body.find_all(True):
            for c in tag.get("class", []):
                all_classes.add(c)
        # Filter to classes that look like they might be product/artwork/gallery
        relevant = sorted(c for c in all_classes if any(
            kw in c.lower() for kw in ["product", "artwork", "item", "card", "gallery", "post", "thumb", "image", "dl", "download"]
        ))
        log.info("  Potentially relevant CSS classes found in body: %s", relevant)

    page.close()
    return soup


# ---------------------------------------------------------------------------
# Step 3 — find first result URL and load artwork page
# ---------------------------------------------------------------------------
def step3_artwork_page(context, search_soup):
    log.info("=" * 60)
    log.info("STEP 3 — Load the first artwork page")
    log.info("=" * 60)

    # Try to extract the first artwork link from the search results
    artwork_url = None

    # Common patterns for Artvee artwork links
    link_patterns = [
        ("a[href*='artvee.com/dl/']", "href"),
        ("a[href*='/dl/']", "href"),
        ("a.product-image-link", "href"),
        ("a.woocommerce-loop-product__link", "href"),
        ("div.product a", "href"),
        ("li.product a", "href"),
        ("article a", "href"),
        ("figure a", "href"),
    ]

    for sel, attr in link_patterns:
        tag = search_soup.select_one(sel)
        if tag and tag.get(attr):
            candidate = tag[attr].strip()
            # Skip thumbnail/image links, we want page links
            if not any(ext in candidate.lower() for ext in [".jpg", ".png", ".webp", ".jpeg"]):
                artwork_url = candidate
                log.info("Found artwork page link via selector '%s': %s", sel, artwork_url)
                break

    if not artwork_url:
        # Fallback: find any internal link that looks like an artwork slug
        for a in search_soup.find_all("a", href=True):
            href = a["href"]
            if "artvee.com" in href and "/dl/" in href:
                artwork_url = href
                log.info("Found artwork link via href scan: %s", artwork_url)
                break

    if not artwork_url:
        log.error("Could not find any artwork page link in search results. Check search_dump.html manually.")
        log.info("Falling back to a known Artvee artwork URL for structure inspection...")
        # Known Artvee artwork page to at least get the page structure
        artwork_url = "https://artvee.com/dl/ancient-persia/"
        log.info("Using fallback URL: %s", artwork_url)

    time.sleep(INTER_DELAY)
    page, soup = _fetch_page(context, artwork_url, wait_selector=None)
    _save_html(soup, "artwork_dump.html")

    log.info("--- Inspecting artwork page structure ---")

    title = soup.find("title")
    log.info("  Page <title>: %s", title.get_text(strip=True) if title else "(none)")

    # Look for the main/full-res image
    img_selectors = [
        "img.attachment-full",
        "img.wp-post-image",
        "div.product-images img",
        "div.woocommerce-product-gallery img",
        "figure img",
        "div[class*='image'] img",
        "div[class*='artwork'] img",
        "a[class*='download']",
        "a[href*='.jpg']",
        "a[href*='.png']",
        "a[href*='.jpeg']",
        "button[class*='download']",
        "a[download]",
    ]

    log.info("  Image / download element search:")
    for sel in img_selectors:
        tags = soup.select(sel)
        if tags:
            first = tags[0]
            src = first.get("href") or first.get("src") or first.get("data-src") or first.get("data-large_image") or "(no src/href)"
            log.info("    '%s' → %d match(es), first src/href: %s", sel, len(tags), src[:120])

    page.close()
    return soup, artwork_url


# ---------------------------------------------------------------------------
# Step 4 — attempt image download
# ---------------------------------------------------------------------------
def step4_download(context, artwork_soup, artwork_url):
    log.info("=" * 60)
    log.info("STEP 4 — Attempt full-res image download")
    log.info("=" * 60)

    image_url = None

    # Strategy A: look for a direct download link (anchor with href to image file)
    for a in artwork_soup.find_all("a", href=True):
        href = a["href"]
        if re.search(r"\.(jpg|jpeg|png|webp)(\?|$)", href, re.IGNORECASE):
            image_url = href
            log.info("Found image URL via <a href>: %s", image_url)
            break

    # Strategy B: look for the largest <img> src (not thumbnail)
    if not image_url:
        best_img = None
        best_size = 0
        for img in artwork_soup.find_all("img"):
            src = img.get("src") or img.get("data-src") or ""
            w = img.get("width") or img.get("data-width") or "0"
            h = img.get("height") or img.get("data-height") or "0"
            try:
                size = int(str(w)) * int(str(h))
            except (ValueError, TypeError):
                size = 0
            # Skip thumbnails and placeholders
            if src and "150x150" not in src and "placeholder" not in src.lower() and size >= best_size:
                best_size = size
                best_img = src
        if best_img:
            image_url = best_img
            log.info("Found image URL via largest <img>: %s", image_url)

    # Strategy C: look for a JS variable or meta tag containing the image
    if not image_url:
        for script in artwork_soup.find_all("script"):
            text = script.string or ""
            m = re.search(r'https://[^\s"\']+\.(jpg|jpeg|png|webp)', text, re.IGNORECASE)
            if m:
                image_url = m.group(0)
                log.info("Found image URL in <script> tag: %s", image_url)
                break

    if not image_url:
        log.error("Could not find a full-res image URL. Inspect artwork_dump.html manually.")
        (OUTPUT_DIR / "out.txt").write_text(
            "Image URL not found. Inspect artwork_dump.html.\n"
            f"Artwork page was: {artwork_url}\n",
            encoding="utf-8"
        )
        return

    # Attempt direct download
    log.info("Attempting download: %s", image_url)
    try:
        resp = requests.get(image_url, headers=DL_HEADERS, timeout=30, stream=True)
        resp.raise_for_status()
        content_type = resp.headers.get("Content-Type", "image/jpeg")
        ext = image_url.rsplit(".", 1)[-1].split("?")[0].lower()
        if ext not in ("jpg", "jpeg", "png", "webp"):
            ext = "jpg"
        out_path = OUTPUT_DIR / f"out.{ext}"
        out_path.write_bytes(resp.content)
        size_kb = out_path.stat().st_size // 1024
        log.info("Download SUCCESS ✓ → %s (%d KB)", out_path, size_kb)
        if size_kb < 5:
            log.warning("File is suspiciously small (%d KB) — may be a redirect page, not an image", size_kb)
    except Exception as e:
        log.error("Download FAILED: %s", e)
        (OUTPUT_DIR / "out.txt").write_text(
            f"Download failed: {e}\nAttempted URL: {image_url}\n",
            encoding="utf-8"
        )


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
def main():
    log.info("╔══════════════════════════════════════════════════╗")
    log.info("║   artvee_probe.py — Phase 1 site inspection     ║")
    log.info("╚══════════════════════════════════════════════════╝")
    log.info("Output directory: %s", OUTPUT_DIR.resolve())

    # Step 1: plain HTTP health check
    step1_health_check()

    pw = None
    browser = None
    try:
        pw = sync_playwright().start()
        browser, context = _make_browser_context(pw)
        log.info("Headless Chromium launched ✓")

        # Step 2: search
        search_soup = step2_search(context, SEARCH_QUERY)

        # Quick check — if zero results, retry with fallback query
        result_indicators = search_soup.select("div.product, li.product, article, div[class*='product']")
        if not result_indicators:
            log.info("No obvious results for '%s', retrying with '%s'", SEARCH_QUERY, FALLBACK_QUERY)
            search_soup = step2_search(context, FALLBACK_QUERY)

        # Step 3: artwork page
        artwork_soup, artwork_url = step3_artwork_page(context, search_soup)

        # Step 4: download
        step4_download(context, artwork_soup, artwork_url)

    finally:
        _save_console_log()
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
        log.info("")
        log.info("═" * 60)
        log.info("Probe complete. Files written to: %s", OUTPUT_DIR.resolve())
        log.info("Please share with the AI:")
        log.info("  • This terminal output (copy-paste it all)")
        log.info("  • artvee_probe_output/search_dump.html")
        log.info("  • artvee_probe_output/artwork_dump.html")
        log.info("  • artvee_probe_output/console.log")
        log.info("  • Whether out.jpg opened as a valid image or was broken")
        log.info("═" * 60)


if __name__ == "__main__":
    main()
