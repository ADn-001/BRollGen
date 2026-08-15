"""
Phase 7 — Openverse adapter tests.

Run against the adapter processes directly. Start adapters first:
    cd CustomAdapters/wh40k
    python start_adapters.bat

Run:
    cd CustomAdapters/wh40k
    python -m pytest tests/test_openverse_adapters.py -v --tb=short

NOTE: these hit the live Openverse API. If every search test fails with a
502 "Openverse API error", Openverse's Cloudflare layer is rate-limiting
this IP (HTTP 429) — usually from a burst of anonymous requests. Wait a few
minutes and re-run, or run with credentials in .env (authenticated requests
get a much larger budget).
"""
import requests
import pytest

# (name, base_url, known-good query with a full result set)
ADAPTERS = [
    ("wikimedia", "http://localhost:3002", "ancient egypt"),
    ("nasa",      "http://localhost:3003", "saturn"),
    ("openverse", "http://localhost:3005", "ancient rome"),
]


@pytest.fixture(scope="module", autouse=True)
def require_adapters_running():
    for name, base_url, _ in ADAPTERS:
        try:
            r = requests.get(f"{base_url}/health", timeout=5)
            if r.status_code != 200:
                pytest.skip(f"Adapter {name} health check failed — start adapters first")
        except Exception as exc:
            pytest.skip(f"Adapter {name} unreachable: {exc} — start adapters first")


@pytest.mark.parametrize("name, base_url, query", ADAPTERS)
def test_health_ok(name, base_url, query):
    r = requests.get(f"{base_url}/health", timeout=5)
    assert r.status_code == 200, f"{name} health check failed: {r.text}"
    data = r.json()
    assert data.get("status") == "ok", f"{name} health status not 'ok': {data}"


@pytest.mark.parametrize("name, base_url, query", ADAPTERS)
def test_search_returns_wellformed_results(name, base_url, query):
    r = requests.get(f"{base_url}/search", params={"q": query, "limit": 5}, timeout=30)
    assert r.status_code == 200, f"{name} search failed: {r.text}"
    results = r.json().get("results", [])
    assert len(results) > 0, f"{name} returned no results for {query!r}"
    for item in results:
        assert item["id"], f"{name} result missing id: {item}"
        assert item["title"], f"{name} result missing title: {item}"
        assert item["thumbnail_url"], f"{name} result missing thumbnail_url: {item}"
        assert item["download_url"], f"{name} result missing download_url: {item}"
        assert item["download_url"].startswith(base_url), (
            f"{name} download_url not reachable: {item['download_url']}"
        )
        assert item["license"], f"{name} result missing license: {item}"


@pytest.mark.parametrize("name, base_url, query", ADAPTERS)
def test_search_honors_anonymous_pagination(name, base_url, query):
    """
    Anonymous access caps page_size at 20. Requesting limit=50 must paginate
    and return 20+ results, proving the multi-page loop in openverse_search
    works. The queries above are verified to have thousands of results.
    """
    r = requests.get(f"{base_url}/search", params={"q": query, "limit": 50}, timeout=60)
    assert r.status_code == 200, f"{name} search failed: {r.text}"
    results = r.json().get("results", [])
    assert 0 < len(results) <= 50, f"{name} pagination returned {len(results)} results"
    assert len(results) >= 20, (
        f"{name} anonymous pagination broken: only {len(results)} of 50 requested"
    )


@pytest.mark.parametrize("name, base_url, query", ADAPTERS)
def test_download_returns_image(name, base_url, query):
    search = requests.get(f"{base_url}/search", params={"q": query, "limit": 1}, timeout=30)
    assert search.status_code == 200, f"{name} search failed: {search.text}"
    item = search.json()["results"][0]

    r = requests.get(f"{base_url}/download", params={"id": item["id"]}, timeout=60)
    assert r.status_code == 200, f"{name} download failed: {r.text[:200]}"
    content_type = r.headers.get("Content-Type", "")
    assert content_type.startswith("image/"), (
        f"{name} download not an image: Content-Type={content_type}"
    )
    assert len(r.content) > 1_000, f"{name} downloaded body suspiciously small"


@pytest.mark.parametrize("name, base_url, query", ADAPTERS)
def test_video_media_type_returns_empty(name, base_url, query):
    r = requests.get(f"{base_url}/search", params={"q": query, "media_type": "video"}, timeout=30)
    assert r.status_code == 200
    assert r.json().get("results") == []
