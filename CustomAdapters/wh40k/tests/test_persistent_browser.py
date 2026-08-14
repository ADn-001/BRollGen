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


# ---------------------------------------------------------------------------
# Tests: code inspection — verify dedicated-worker-thread design
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("adapter_file", [
    "40k_adapter.py",
    "artvee_adapter.py",
    "loc_adapter.py",
])
def test_adapter_uses_dedicated_worker_thread(adapter_file):
    """
    The persistent browser must be owned by a single dedicated worker
    thread (jobs submitted via a queue), not touched directly from Flask's
    request threads. Playwright's sync API is not thread-safe — a
    lock-guarded-launch-only approach would still crash if a second
    request thread later calls browser.new_context() directly.
    """
    import pathlib
    src = (pathlib.Path(__file__).parent.parent / adapter_file).read_text()
    assert "_browser_worker_loop" in src, \
        f"{adapter_file} must run the persistent browser on a dedicated worker loop"
    assert "_job_queue" in src, \
        f"{adapter_file} must submit jobs to the persistent browser via a queue"


@pytest.mark.parametrize("adapter_file", [
    "40k_adapter.py",
    "artvee_adapter.py",
    "loc_adapter.py",
])
def test_adapter_handles_launch_failure(adapter_file):
    """Each adapter must permanently disable persistence if the browser launch fails."""
    import pathlib
    src = (pathlib.Path(__file__).parent.parent / adapter_file).read_text()
    assert "_browser_init_failed" in src, \
        f"{adapter_file} must track browser-launch failure to disable persistence"
