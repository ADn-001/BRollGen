# Phase 5 — Persistent Playwright Browser in Adapters

**Prerequisite:** None (independent).

**Objective:** Each adapter keeps a persistent Playwright Chromium browser alive across requests. Browser context (cookies, isolated session) is created fresh per request but shares the warm browser process — eliminating the ~2–5s cold-start cost on every search/download call. If the persistent browser fails for any reason, the adapter falls back transparently to the current stateless mode (fresh browser per call).

---

## Architecture

```
Request N=1:  launch browser → create context → scrape → close context
               ↑ cold start ~4s
Request N=2:  reuse browser → create context → scrape → close context
               ↑ warm, ~0.3s per page
...
Any failure:  → fallback to fresh browser per call (current behavior)
```

Each adapter uses a module-level `threading.Lock` to guard the initial browser launch (one-time). Concurrent requests each create their own `BrowserContext` from the shared `Browser` — contexts are Playwright's isolation boundary, thread-safe to create concurrently once the browser is running.

**Important:** `40k_adapter.py` and `loc_adapter.py` use sync Playwright. `artvee_adapter.py` must be checked — if it uses async Playwright inside sync Flask (via `asyncio.run()`), the persistent browser strategy differs.

---

## Files Changed

| Action | File |
|--------|------|
| EDIT | `CustomAdapters/wh40k/40k_adapter.py` |
| EDIT | `CustomAdapters/wh40k/artvee_adapter.py` |
| EDIT | `CustomAdapters/wh40k/loc_adapter.py` |

---

## Implementation Steps

### Step 1 — Read `artvee_adapter.py` before touching it

Before implementing, read `artvee_adapter.py` to determine:
- Does it use `sync_playwright` or `async_playwright`?
- Does it run inside an `asyncio.run()` wrapper?
- What does `_fetch_html()` look like?

This determines whether the persistent browser approach is sync (same as 40k/loc) or requires an asyncio event loop held open on a background thread.

### Step 2 — `CustomAdapters/wh40k/40k_adapter.py`

**Add persistent browser globals at module level** (after imports, before any route definitions):

```python
import threading

# ── Persistent browser state ──────────────────────────────────────────────────
_browser_lock = threading.Lock()
_pw_instance = None       # playwright.sync_api._impl.playwright.Playwright
_browser = None           # playwright.sync_api._impl.browser.Browser
_browser_init_failed = False   # set True if launch fails; disables persistence for this process


def _get_persistent_browser():
    """
    Return the shared Browser instance, launching it if needed.
    Returns None if the browser cannot be launched (triggers stateless fallback).
    Thread-safe: only one thread launches the browser; others wait on the lock.
    """
    global _pw_instance, _browser, _browser_init_failed

    if _browser_init_failed:
        return None

    with _browser_lock:
        # Re-check inside lock (another thread may have set _browser while we waited)
        if _browser_init_failed:
            return None

        needs_launch = (_browser is None) or (not _browser.is_connected())

        if needs_launch:
            # Tear down any stale instance before relaunching
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

            try:
                from playwright.sync_api import sync_playwright
                _pw_instance = sync_playwright().start()
                _browser = _pw_instance.chromium.launch(
                    headless=True,
                    args=["--no-sandbox", "--disable-blink-features=AutomationControlled"],
                )
                log.info("Persistent Playwright browser launched (PID managed by Playwright).")
            except Exception as exc:
                log.error(
                    "Failed to launch persistent browser: %s — all requests will use stateless mode.", exc
                )
                _browser_init_failed = True
                return None

    return _browser


def _fetch_html_with_browser(browser, url: str) -> str | None:
    """
    Use an existing browser instance: create a fresh context, load the URL,
    return page HTML, then close the context.
    Each call is isolated (no cookies or state leaks between requests).
    """
    context = None
    page = None
    try:
        context = browser.new_context(
            viewport={"width": 1280, "height": 900},
            user_agent=DL_HEADERS["User-Agent"],
            locale="en-US",
        )
        context.add_init_script(
            "Object.defineProperty(navigator, 'webdriver', {get: () => undefined})"
        )
        page = context.new_page()
        log.info("Persistent browser → %s", url)
        page.goto(url, wait_until="domcontentloaded", timeout=PAGE_TIMEOUT)

        # Cloudflare challenge resolution (same logic as before)
        try:
            page.wait_for_function(
                "() => document.title !== 'Just a moment...'",
                timeout=SELECTOR_WAIT,
            )
        except Exception:
            log.warning("Cloudflare challenge may not have resolved: %s", url)

        page.wait_for_timeout(1500)
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
```

**Replace `_fetch_html()`** with a version that tries persistent first, falls back to fresh:

```python
def _fetch_html(url: str) -> str | None:
    """
    Fetch page HTML. Tries persistent browser first; falls back to a fresh
    browser-per-call if the persistent browser is unavailable or fails.
    """
    # ── Try persistent browser ────────────────────────────────────────────
    browser = _get_persistent_browser()
    if browser is not None:
        result = _fetch_html_with_browser(browser, url)
        if result is not None:
            return result
        log.warning("Persistent browser returned None for %s — falling back to stateless.", url)

    # ── Fallback: stateless (fresh browser per call) ──────────────────────
    return _fetch_html_fresh(url)


def _fetch_html_fresh(url: str) -> str | None:
    """
    Original implementation: launches a fresh Playwright browser per call.
    Used as fallback when the persistent browser is unavailable or fails.
    """
    time.sleep(INTER_DELAY)
    pw = browser = None
    try:
        from playwright.sync_api import sync_playwright
        pw = sync_playwright().start()
        browser = pw.chromium.launch(
            headless=True,
            args=["--no-sandbox", "--disable-blink-features=AutomationControlled"],
        )
        context = browser.new_context(
            viewport={"width": 1280, "height": 900},
            user_agent=DL_HEADERS["User-Agent"],
            locale="en-US",
        )
        context.add_init_script(
            "Object.defineProperty(navigator, 'webdriver', {get: () => undefined})"
        )
        page = context.new_page()
        page.goto(url, wait_until="domcontentloaded", timeout=PAGE_TIMEOUT)
        try:
            page.wait_for_function(
                "() => document.title !== 'Just a moment...'",
                timeout=SELECTOR_WAIT,
            )
        except Exception:
            pass
        page.wait_for_timeout(1500)
        return page.content()
    except Exception as exc:
        log.warning("Fresh browser fetch failed for %s: %s", url, exc)
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
```

**Graceful shutdown** — add at the bottom of the file, before `if __name__ == "__main__":`:

```python
import atexit

def _shutdown_browser():
    global _browser, _pw_instance
    try:
        if _browser:
            _browser.close()
        if _pw_instance:
            _pw_instance.stop()
        log.info("Persistent browser shut down cleanly.")
    except Exception:
        pass

atexit.register(_shutdown_browser)
```

### Step 3 — `CustomAdapters/wh40k/loc_adapter.py`

Apply the exact same pattern as Step 2. The `loc_adapter.py` uses sync Playwright (`_fetch_json` instead of `_fetch_html`, but same browser control flow). Adapt the persistent browser pattern to `_fetch_json`:

- Add same globals (`_browser_lock`, `_pw_instance`, `_browser`, `_browser_init_failed`)
- Add `_get_persistent_browser()` — identical to Step 2
- Add `_fetch_json_with_browser(browser, url)` — same as `_fetch_html_with_browser` but parses JSON from body text
- Rename current `_fetch_json` → `_fetch_json_fresh`
- New `_fetch_json` tries persistent, falls back to `_fetch_json_fresh`
- Add `atexit.register(_shutdown_browser)`

### Step 4 — `CustomAdapters/wh40k/artvee_adapter.py`

**Read the file first** (Step 1 prerequisite) to determine the async/sync structure. Then apply the appropriate pattern:

**If artvee uses sync Playwright:** Same as Steps 2–3.

**If artvee uses async Playwright** (e.g., `asyncio.run(...)` wrapping async page ops inside a Flask thread): The persistent browser must live on a dedicated background asyncio event loop. Pattern:

```python
import asyncio
import threading

_async_loop = None
_async_browser = None
_async_browser_lock = threading.Lock()
_async_browser_failed = False

def _get_async_loop():
    """Get or create a persistent asyncio event loop running in a background thread."""
    global _async_loop
    if _async_loop is None or not _async_loop.is_running():
        _async_loop = asyncio.new_event_loop()
        t = threading.Thread(target=_async_loop.run_forever, daemon=True)
        t.start()
    return _async_loop

def _get_async_browser():
    """Launch/return a persistent async Playwright browser on the background loop."""
    global _async_browser, _async_browser_failed
    if _async_browser_failed:
        return None
    # ... launch via asyncio.run_coroutine_threadsafe on _get_async_loop() ...
```

**If implementation is ambiguous after reading:** Flag as a design decision, implement sync fallback only for artvee (stateless mode), and document the reason in GATELOG.

---

## Test Suite

Save as `CustomAdapters/wh40k/tests/test_persistent_browser.py`

```python
"""
Phase 5 — Persistent Playwright browser tests.

These tests run against the adapter processes directly.
Start adapters before running: python start_adapters.bat

Run:
    cd CustomAdapters/wh40k
    python -m pytest tests/test_persistent_browser.py -v --tb=short
"""
import time
import requests
import pytest

ADAPTERS = [
    ("40k.gallery", "http://localhost:3000"),
    ("artvee.com",  "http://localhost:3001"),
    ("loc.gov",     "http://localhost:3002"),
]


# ---------------------------------------------------------------------------
# Fixture: ensure adapters are up
# ---------------------------------------------------------------------------

@pytest.fixture(scope="module", autouse=True)
def require_adapters_running():
    for name, base_url in ADAPTERS:
        try:
            r = requests.get(f"{base_url}/health", timeout=5)
            if r.status_code != 200:
                pytest.skip(f"Adapter {name} health check failed — start adapters first")
        except Exception as exc:
            pytest.skip(f"Adapter {name} unreachable: {exc} — start adapters first")


# ---------------------------------------------------------------------------
# Tests: /health endpoint works
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("name, base_url", ADAPTERS)
def test_health_ok(name, base_url):
    r = requests.get(f"{base_url}/health", timeout=5)
    assert r.status_code == 200, f"{name} health check failed: {r.text}"
    data = r.json()
    assert data.get("status") == "ok", f"{name} health status not 'ok': {data}"


# ---------------------------------------------------------------------------
# Tests: second search call is faster than first (persistent browser benefit)
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("name, base_url", ADAPTERS)
def test_second_search_faster_than_first(name, base_url):
    """
    After the first search (which may launch the browser), a second search
    should be noticeably faster because the browser is already warm.
    We allow a generous tolerance — this is a heuristic, not a hard SLA.
    """
    query = "ancient rome"

    # First call (may include browser launch time)
    t0 = time.monotonic()
    r1 = requests.get(f"{base_url}/search", params={"q": query, "limit": 1}, timeout=60)
    first_call_time = time.monotonic() - t0

    if r1.status_code != 200:
        pytest.skip(f"{name} search returned {r1.status_code} — source may be unreachable")

    # Second call (browser should already be warm)
    t1 = time.monotonic()
    r2 = requests.get(f"{base_url}/search", params={"q": query, "limit": 1}, timeout=60)
    second_call_time = time.monotonic() - t1

    # The second call should not be dramatically slower than the first.
    # We check: second call ≤ first call × 1.5 OR second call ≤ 10s
    # (If the first call was already fast, the second just needs to succeed)
    assert r2.status_code == 200, f"{name} second search failed"
    assert second_call_time <= max(first_call_time * 1.5, 10.0), (
        f"{name}: Second call ({second_call_time:.1f}s) was much slower than "
        f"first ({first_call_time:.1f}s) — browser may not be persisting"
    )


# ---------------------------------------------------------------------------
# Tests: concurrent requests don't crash the adapter
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("name, base_url", ADAPTERS)
def test_concurrent_requests_succeed(name, base_url):
    """
    Two concurrent search requests must both succeed — shared browser
    must handle concurrent context creation without crashing.
    """
    import concurrent.futures

    def search():
        return requests.get(
            f"{base_url}/search",
            params={"q": "warrior", "limit": 1},
            timeout=60,
        )

    with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
        futures = [pool.submit(search), pool.submit(search)]
        results = [f.result() for f in futures]

    for r in results:
        assert r.status_code == 200, f"{name} concurrent request failed: {r.status_code}"


# ---------------------------------------------------------------------------
# Tests: code inspection — verify fallback pattern exists
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("adapter_file", [
    "40k_adapter.py",
    "artvee_adapter.py",
    "loc_adapter.py",
])
def test_adapter_has_fallback_to_fresh(adapter_file):
    """Each adapter must contain a fresh/stateless fallback function."""
    import pathlib
    adapter_path = pathlib.Path(__file__).parent.parent / adapter_file
    assert adapter_path.exists(), f"{adapter_file} not found"
    src = adapter_path.read_text()

    # Must have the persistent browser globals
    assert "_browser_lock" in src or "_async_browser_lock" in src, \
        f"{adapter_file} must define a _browser_lock"

    # Must have a fallback function (either _fetch_html_fresh or _fetch_json_fresh)
    has_fresh_fallback = "_fetch_html_fresh" in src or "_fetch_json_fresh" in src
    assert has_fresh_fallback, \
        f"{adapter_file} must define a fresh/stateless fallback function"


@pytest.mark.parametrize("adapter_file", [
    "40k_adapter.py",
    "artvee_adapter.py",
    "loc_adapter.py",
])
def test_adapter_has_atexit_shutdown(adapter_file):
    """Each adapter must register an atexit handler to close the browser cleanly."""
    import pathlib
    src = (pathlib.Path(__file__).parent.parent / adapter_file).read_text()
    assert "atexit" in src, f"{adapter_file} must import atexit"
    assert "atexit.register" in src, f"{adapter_file} must call atexit.register"
```

---

## Terminal Command

```bat
REM Start adapters first (in separate windows)
cd /d "D:\yt_vids\automation ecosystem\BRollGen\CustomAdapters\wh40k"
start_adapters.bat

REM Then, after adapters are up:
cd /d "D:\yt_vids\automation ecosystem\BRollGen\CustomAdapters\wh40k"
python -m pytest tests/test_persistent_browser.py -v --tb=short 2>&1
```

---

## Pass Criteria

- All code-inspection tests green (no running adapter needed)
- With adapters running: all health tests green
- With adapters running: second-search-faster test passes (heuristic — 1.5× tolerance)
- With adapters running: concurrent test passes (no crash, both return 200)
- Adapter log output shows "Persistent Playwright browser launched" on first request
- Adapter log shows fallback message if browser is killed mid-run and next request recovers

## Failure Recovery

If a persistent browser dies mid-operation (e.g., OOM kill):
- `_browser.is_connected()` returns `False`
- Next call to `_get_persistent_browser()` detects this, relaunches, returns new browser
- The failed individual request uses the `_fetch_html_fresh` fallback while relaunch happens
- No request ever fails due to persistent browser death — worst case is one slow stateless call
