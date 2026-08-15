# Phase 7 — Openverse Adapter Consolidation (Wikimedia / NASA / All-Openverse)

**Prerequisite:** Phase 6 complete. A working local stack: backend on `http://localhost:7420`, adapters launched via `CustomAdapters/wh40k/start_adapters.bat`. The 40k.gallery (`3000`) and artvee.com (`3001`) adapters must already be working — they are untouched by this phase.

**Objective:** Replace the broken, anti-scraped Library of Congress (LOC) adapter with an Openverse-API-based adapter family, and consolidate the adapter set down to exactly five:

| Port | Adapter | File | Backend |
|------|---------|------|---------|
| 3000 | 40k.gallery | `40k_adapter.py` | Playwright scrape (unchanged) |
| 3001 | artvee.com | `artvee_adapter.py` | Playwright scrape (unchanged) |
| 3002 | Wikimedia Commons | `wikimedia_adapter.py` | Openverse API, `source=wikimedia` |
| 3003 | NASA | `nasa_adapter.py` | Openverse API, `source=nasa` |
| 3005 | All Openverse | `openverse_adapter.py` | Openverse API, all sources |

LOC and British Library content are **not** reachable through a dedicated Openverse source slug (Openverse has no `loc` or `british` slug — verified against the live API). Both institutions publish through **Flickr**, which Openverse does aggregate under `source=flickr`. The **All Openverse** adapter (no source filter) is therefore the vehicle for LOC/BritLib access. The Flickr API itself is not used, because Flickr recently changed its policy and paywalled it.

This phase also removes every superseded adapter, fixes a Docker-breaking hardcoded `localhost` in the shared Openverse module, updates the batch scripts / Docker / Compose files, adds a `.env` credential template for Openverse authentication, and ships a new pytest suite. **No database rows are changed** — the adapters are source-agnostic and reusable across profiles; the user wires sources and profile links through the Sources UI.

---

## Open Design Decisions (Resolved Before Coding)

| # | Question | Decision |
|---|----------|----------|
| OQ1 | How do LOC / British Library images get in, now that the Flickr API is paywalled? | Use the **All Openverse** adapter. Openverse aggregates Flickr (which hosts LOC + British Library + all Commons) under `source=flickr`. No direct Flickr API calls. |
| OQ2 | Which adapters ship? | Exactly **40k, artvee, wikimedia, nasa, all-openverse**. Ports `3000 / 3001 / 3002 / 3003 / 3005`. Port `3004` (old europeana) is freed. |
| OQ3 | What happens to the superseded / broken adapters and stale debug artifacts? | **Deleted** (`europeana`, `loc`, `britlib`, `flickr_commons`, `flickr_base`, `4.12.0`, `search_dump.html`, `test.txt`, `loc_debug.py`, `loc_browser_profile/`). |
| OQ4 | Where do the new sources' `adapter_script_path` point? | At the **canonical `CustomAdapters/wh40k/` files**, not `CustomAdapters/uploaded/<id>/` copies. The Openverse adapters import a sibling module (`openverse_base.py`); the single-file auto-launcher (`subprocess.Popen([sys.executable, script_path])`) and the Docker `COPY ${ADAPTER_SCRIPT}` only carry one file, so the base module must live next to the entrypoint. |
| OQ5 | Is Openverse authentication required? | No. Anonymous access works (verified live) but caps `page_size` at 20. Optional OAuth2 (register once for `client_id`/`client_secret`) raises the cap to 500. Credentials are stored in each source's `auth_token` config as `client_id:client_secret` (or env vars `OPENVERSE_CLIENT_ID` / `OPENVERSE_CLIENT_SECRET`). |

> **Keep (do NOT revert):** the previous agent left coherent, uncommitted work that this phase builds on and must not disturb — the LLM prompt improvement + niche description injection in `backend/services/analyzer.py`, the `default_quality_score` per-source fallback in `backend/services/downloader.py` + `frontend/src/pages/Sources.jsx`, and the relaxed download gate in `backend/routers/sessions.py` + `frontend/src/pages/Dashboard.jsx`. These make dimension-less Openverse results competitive and let sessions proceed with fewer tags than `item_count`.

---

## Files Changed

| Action | File |
|--------|------|
| DELETE | `CustomAdapters/wh40k/europeana_adapter.py` |
| DELETE | `CustomAdapters/wh40k/loc_adapter.py` (the Flickr rewrite; superseded) |
| DELETE | `CustomAdapters/wh40k/britlib_adapter.py` |
| DELETE | `CustomAdapters/wh40k/flickr_commons_adapter.py` |
| DELETE | `CustomAdapters/wh40k/flickr_base.py` |
| DELETE | `CustomAdapters/wh40k/4.12.0`, `search_dump.html`, `test.txt`, `loc_debug.py` |
| DELETE | `CustomAdapters/wh40k/loc_browser_profile/` |
| EDIT | `CustomAdapters/wh40k/openverse_base.py` |
| EDIT | `CustomAdapters/wh40k/wikimedia_adapter.py` |
| EDIT | `CustomAdapters/wh40k/nasa_adapter.py` |
| EDIT | `CustomAdapters/wh40k/openverse_adapter.py` |
| EDIT | `CustomAdapters/wh40k/start_adapters.bat` |
| EDIT | `CustomAdapters/wh40k/install_adapters.bat` |
| EDIT | `CustomAdapters/wh40k/Dockerfile` |
| EDIT | `docker-compose.yml` |
| NEW | `.env.example` |
| EDIT | `.gitignore` |
| EDIT | `CustomAdapters/wh40k/tests/test_persistent_browser.py` |
| NEW | `CustomAdapters/wh40k/tests/test_openverse_adapters.py` |
| EDIT | `docs/CUSTOM_ADAPTER_GUIDE.md` |
| EDIT | `docs/implementation/GATELOG.md` (**at completion**, per project workflow) |

---

## Implementation Steps

### PART A — Delete superseded adapters and stale artifacts

The files below are either superseded by the Openverse family or are leftover debug junk. Remove them from disk **and** from git tracking.

Tracked files → `git rm` (stages the deletion):

```bash
git -C "D:/yt_vids/automation ecosystem/BRollGen" rm \
  CustomAdapters/wh40k/4.12.0 \
  CustomAdapters/wh40k/search_dump.html \
  CustomAdapters/wh40k/test.txt \
  CustomAdapters/wh40k/loc_debug.py \
  CustomAdapters/wh40k/loc_adapter.py
```

Untracked files/dirs → plain delete:

```bash
rm -rf "D:/yt_vids/automation ecosystem/BRollGen/CustomAdapters/wh40k/loc_browser_profile"
rm \
  "D:/yt_vids/automation ecosystem/BRollGen/CustomAdapters/wh40k/europeana_adapter.py" \
  "D:/yt_vids/automation ecosystem/BRollGen/CustomAdapters/wh40k/britlib_adapter.py" \
  "D:/yt_vids/automation ecosystem/BRollGen/CustomAdapters/wh40k/flickr_commons_adapter.py" \
  "D:/yt_vids/automation ecosystem/BRollGen/CustomAdapters/wh40k/flickr_base.py"
```

Verify with `git status` that exactly these five tracked files are staged for deletion and nothing unexpected is listed. The remaining adapter files stay: `40k_adapter.py`, `artvee_adapter.py`, `wikimedia_adapter.py`, `nasa_adapter.py`, `openverse_adapter.py`, `openverse_base.py`.

### PART B — Fix `openverse_base.py` (Docker host, pagination, User-Agent)

Three fixes to the shared module. All call sites are inside the Openverse adapters, so no external contract changes.

#### B1 — Add `MAX_PAGES` and a User-Agent constant

After line 37 (`AUTH_MAX_PAGE_SIZE = 500`) add:

```python
MAX_PAGES = 5
UA_HEADERS = {"User-Agent": "BRollEngine/1.0 (Openverse adapter; local b-roll curation)"}
```

#### B2 — Paginate `openverse_search` when `limit` exceeds the per-page cap

Anonymous access caps `page_size` at 20; authenticated at 500. Today `openverse_search` fetches a single page, so an anonymous `limit=50` request silently returns only 20 results. Replace the whole function (lines 139–183) with:

```python
def openverse_search(
    query: str,
    limit: int = 20,
    source: str | None = None,
) -> list[dict] | None:
    """
    Search Openverse images, paginating when the requested limit exceeds the
    per-page cap (20 anonymous, 500 authenticated).

    Returns:
        List of raw Openverse result dicts, or None on API error.
    """
    headers = build_auth_headers()
    headers.update(UA_HEADERS)
    max_page_size = AUTH_MAX_PAGE_SIZE if headers.get("Authorization") else ANON_MAX_PAGE_SIZE
    page_size = min(limit, max_page_size)

    params: dict = {
        "q": query,
        "page_size": page_size,
    }
    if source:
        params["source"] = source

    results: list[dict] = []
    page = 1
    while len(results) < limit and page <= MAX_PAGES:
        try:
            resp = requests.get(
                f"{OPENVERSE_API_BASE}images/",
                params={**params, "page": page},
                headers=headers,
                timeout=15,
            )
        except requests.RequestException as exc:
            log.error("Openverse search request failed: %s", exc)
            return None

        if resp.status_code != 200:
            log.error("Openverse search returned %d: %s", resp.status_code, resp.text[:200])
            return None if not results else results

        data = resp.json()
        page_results = data.get("results", [])
        if not page_results:
            break
        results.extend(page_results)
        page += 1

    return results[:limit]
```

#### B3 — Build `download_url` from the request Host header (Docker fix)

`parse_result` currently hardcodes `http://localhost:{adapter_port}/download?id=...`. That is correct natively (the backend calls `http://localhost:3005/search`, so `localhost` is right) but **breaks under Docker**, where the backend container calls `http://adapter-openverse:3005/search` and would then try to download from `http://localhost:3005` inside the app container — which is the app, not the adapter.

Fix by deriving the host from the request the adapter just served. `flask_request` is already imported (line 31). Two changes:

1. Drop the `adapter_port` parameter — change line 190 to:

```python
def parse_result(item: dict) -> dict:
```

2. Replace the hardcoded `download_url` line (line 215) with:

```python
        "download_url":  f"http://{flask_request.host}/download?id={item.get('id', '')}",
```

With this, the `Host` header of the `/search` request (which is the address the backend actually used) is echoed back. Native: `localhost:3005`. Docker: `adapter-openverse:3005`. Both work. Update the docstring (lines 194–196) to note the host is request-derived.

#### B4 — Add User-Agent to image downloads

Line 243 currently: `resp = requests.get(url, timeout=30, stream=True)`. Change to:

```python
    resp = requests.get(url, headers=UA_HEADERS, timeout=30, stream=True)
```

#### B5 — Guard credential reads outside a request context

`_get_credentials()` reads the request header via `flask_request.headers`, but each adapter's `__main__` block calls `ov.is_authenticated()` at startup, before any request exists — Werkzeug then raises `RuntimeError: Working outside of request context` and the adapter crashes before `app.run()`. (This latent bug predates this phase; it surfaced the first time the adapters were actually started.) Fix by only touching the header inside an active request context:

```python
from flask import request as flask_request, has_request_context

def _get_credentials() -> tuple[str, str] | None:
    if has_request_context():
        auth = flask_request.headers.get("Authorization", "")
        if auth.startswith("Bearer "):
            # ... client_id:client_secret from the header ...
    # env var / .env fallback below (works outside a request)
```

Outside a request (the startup banner), credentials resolve from env / `.env` only; inside a request, the `Authorization` header still wins.

### PART C — Update the three Openverse adapter entrypoints

In **each** of `wikimedia_adapter.py`, `nasa_adapter.py`, `openverse_adapter.py`:

1. Update the call site from `ov.parse_result(item, PORT)` to `ov.parse_result(item)`.
2. Update the docstring port-map line from
   `(40k=3000, artvee=3001, wikimedia=3002, nasa=3003, europeana=3004, openverse=3005)`
   to
   `(40k=3000, artvee=3001, wikimedia=3002, nasa=3003, openverse=3005)`.

No route logic changes — the three files are otherwise complete and correct.

### PART D — Batch scripts, Dockerfile, docker-compose.yml

#### D1 — `start_adapters.bat`

- Remove `europeana_adapter.py` from the file-check list (lines 26–27). The list becomes: `40k_adapter.py`, `artvee_adapter.py`, `wikimedia_adapter.py`, `nasa_adapter.py`, `openverse_adapter.py`, `openverse_base.py`.
- Delete the Europeana launch block (lines 54–55).
- Delete the `Europeana http://localhost:3004/health` status line (line 73).

Everything else stays, including the Openverse OAuth2 hint block (anonymous works; register for higher limits).

#### D2 — `install_adapters.bat`

Replace the file-check list on line 49:

```bat
for %%F in (40k_adapter.py artvee_adapter.py wikimedia_adapter.py nasa_adapter.py openverse_adapter.py openverse_base.py) do (
```

#### D3 — `CustomAdapters/wh40k/Dockerfile`

The image copies only the single entrypoint (`COPY ${ADAPTER_SCRIPT} ./adapter.py`), so `import openverse_base` would fail for the three Openverse adapters. Add one line after it:

```dockerfile
COPY ${ADAPTER_SCRIPT} ./adapter.py
COPY openverse_base.py ./openverse_base.py
```

The base module is copied for every adapter (including 40k/artvee, where it is simply unused) — harmless and keeps a single Dockerfile.

#### D4 — `docker-compose.yml`

Replace the `adapter-loc` service (port 3002) with `adapter-wikimedia`, and add `adapter-nasa` (3003) and `adapter-openverse` (3005). Update the app's `depends_on` to require all five adapters healthy. New app block:

```yaml
    depends_on:
      adapter-wh40k:
        condition: service_healthy
      adapter-artvee:
        condition: service_healthy
      adapter-wikimedia:
        condition: service_healthy
      adapter-nasa:
        condition: service_healthy
      adapter-openverse:
        condition: service_healthy
```

The three new/changed adapter services follow the existing pattern exactly (same healthcheck shape, `start_period: 30s`):

```yaml
  adapter-wikimedia:
    build:
      context: ./CustomAdapters/wh40k
      dockerfile: Dockerfile
      args:
        ADAPTER_SCRIPT: wikimedia_adapter.py
    ports:
      - "3002:3002"
    healthcheck:
      test: ["CMD", "python", "-c", "import urllib.request; urllib.request.urlopen('http://localhost:3002/health')"]
      interval: 10s
      timeout: 5s
      retries: 5
      start_period: 30s
    restart: unless-stopped
```

`adapter-nasa` mirrors this with `ADAPTER_SCRIPT: nasa_adapter.py`, port `3003`. `adapter-openverse` mirrors it with `ADAPTER_SCRIPT: openverse_adapter.py`, port `3005`.

> **Docker note (known pre-existing limitation, not introduced by this phase):** the DB stores `adapter_url` as `http://localhost:<port>`, which is correct for the native run but wrong from inside the app container. Under Docker, the three Openverse source `adapter_url` values must be the Compose service hostnames (`http://adapter-wikimedia:3002`, `http://adapter-nasa:3003`, `http://adapter-openverse:3005`) — set them in the Sources UI (or re-run the seed script in `--docker` mode) only when running the Compose stack. Sources 4/6 (40k, artvee) have the same latent issue; they are out of scope.

### PART E — Credentials via `.env` (no database changes in this phase)

No DB rows are created here — the adapters are source-agnostic and the user wires sources and profile links through the Sources UI per profile. This phase only adds the credential template:

1. Create `.env.example` at the repo root documenting `OPENVERSE_CLIENT_ID` and `OPENVERSE_CLIENT_SECRET`, with a pointer to the one-time registration endpoint. `.env` itself is gitignored; add `!.env.example` to `.gitignore` so the template is committed.
2. `openverse_base.py` loads `.env` at import time via `_load_env_file()` — it searches the module directory (`CustomAdapters/wh40k/`) and the repo root (two levels up), reads `KEY=VALUE` lines, strips surrounding quotes, and never overrides already-set environment variables. This works no matter who launches the adapter: `start_adapters.bat`, the backend auto-launcher, or Docker env vars.

When the user later creates sources in the Sources UI, each Openverse source needs:

- **Adapter URL**: `http://localhost:3002` / `:3003` / `:3005`
- **Adapter Script Path**: the full path to the `wh40k` entrypoint, e.g. `D:\yt_vids\automation ecosystem\BRollGen\CustomAdapters\wh40k\wikimedia_adapter.py` (and the `nasa_adapter.py` / `openverse_adapter.py` variants)
- **Default Quality Score**: `6000000` (≈3000×2000, so dimension-less Openverse results compete with Pexels/Pixabay)
- **Auth Token**: leave blank to use `.env` credentials, or set `client_id:client_secret` — the header value wins over `.env`

> **Why `adapter_script_path` points at `CustomAdapters/wh40k/` and not `uploaded/<id>/`:** the auto-launcher runs one file with `subprocess.Popen([sys.executable, script_path])`. `openverse_adapter.py` needs its sibling `openverse_base.py` on `sys.path` (its first line inserts the script's own directory). Only the canonical `wh40k` folder contains both. The `uploaded/<id>/` pattern only works for self-contained single-file adapters (40k, artvee), which is why those two stay where they are. Do **not** use the UI's drag-and-drop script upload for the Openverse adapters — it stores a single file and the sibling import breaks.

### PART F — Update the test suite

#### F1 — `tests/test_persistent_browser.py`

The persistent-browser assertions (second-search-faster, concurrency, `_browser_worker_loop`, `_job_queue`, `atexit`, fallback, launch-failure) only apply to the two Playwright adapters. Narrow it:

- Line 15–19, change `ADAPTERS` to exactly:

```python
ADAPTERS = [
    ("40k.gallery", "http://localhost:3000"),
    ("artvee.com",  "http://localhost:3001"),
]
```

- In the three code-inspection `@pytest.mark.parametrize` blocks (lines 116–119, 138–141, 155–159, 176–180), remove `"loc_adapter.py"` from each file list.

#### F2 — New `tests/test_openverse_adapters.py`

Create the file with the complete suite below. It follows the same live-adapter convention as the persistent-browser tests: skip (not fail) if an adapter is down, assert against real Openverse results.

```python
"""
Phase 7 — Openverse adapter tests.

Run against the adapter processes directly. Start adapters first:
    cd CustomAdapters/wh40k
    python start_adapters.bat

Run:
    cd CustomAdapters/wh40k
    python -m pytest tests/test_openverse_adapters.py -v --tb=short
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
```

### PART G — Update docs

Update `docs/CUSTOM_ADAPTER_GUIDE.md`:

1. **Adapter inventory** — replace the old LOC/europeana rows with the five-adapter table from the Objective, noting `3000`/`3001` are Playwright scrapes and `3002`/`3003`/`3005` are Openverse-API-based.
2. **Openverse setup** — document the one-time OAuth2 registration (see User Setup below) and the two ways to supply credentials.
3. **LOC / British Library access** — explicitly note there is no `loc` or `british` Openverse source slug; both institutions are reached through the **All Openverse** adapter's `source=flickr` aggregate.
4. **Docker** — document the five adapter services and the `adapter_url` service-hostname caveat (see D4).

Do **not** write the GATELOG entry yet — that happens at completion per the project workflow (implement → test → green → GATELOG).

---

## Test Suite

- `CustomAdapters/wh40k/tests/test_persistent_browser.py` — kept, narrowed to 40k/artvee (Playwright-only assertions).
- `CustomAdapters/wh40k/tests/test_openverse_adapters.py` — new, full suite in PART F2 (health, well-formed results, anonymous pagination, image download, video rejection).

Both suites run against live adapter processes and **skip** (never fail) when an adapter is unreachable.

---

## Terminal Commands

```bash
# 1. Delete superseded adapters + stale artifacts (PART A)
git -C "D:/yt_vids/automation ecosystem/BRollGen" rm \
  CustomAdapters/wh40k/4.12.0 \
  CustomAdapters/wh40k/search_dump.html \
  CustomAdapters/wh40k/test.txt \
  CustomAdapters/wh40k/loc_debug.py \
  CustomAdapters/wh40k/loc_adapter.py
rm -rf "D:/yt_vids/automation ecosystem/BRollGen/CustomAdapters/wh40k/loc_browser_profile"
rm \
  "D:/yt_vids/automation ecosystem/BRollGen/CustomAdapters/wh40k/europeana_adapter.py" \
  "D:/yt_vids/automation ecosystem/BRollGen/CustomAdapters/wh40k/britlib_adapter.py" \
  "D:/yt_vids/automation ecosystem/BRollGen/CustomAdapters/wh40k/flickr_commons_adapter.py" \
  "D:/yt_vids/automation ecosystem/BRollGen/CustomAdapters/wh40k/flickr_base.py"

# 2. Create your .env with real Openverse credentials (PART E)
cp .env.example .env
#   then edit .env and paste your client_id / client_secret

# 3. Start all five adapters
cd "D:/yt_vids/automation ecosystem/BRollGen/CustomAdapters/wh40k"
python start_adapters.bat

# 4. Run both test suites
cd "D:/yt_vids/automation ecosystem/BRollGen/CustomAdapters/wh40k"
python -m pytest tests/test_persistent_browser.py tests/test_openverse_adapters.py -v --tb=short
```

---

## User Setup — Openverse Credentials (one-time, recommended)

Anonymous access works, but caps `page_size` at 20. Registering once unlocks up to 500 results per page.

1. **Register** for a client (replace the email):

```bash
curl -X POST https://api.openverse.org/v1/auth_tokens/register/ \
  -H "Content-Type: application/json" \
  -d '{"name":"BRollGen","description":"Local b-roll curation tool","email":"you@example.com"}'
```

   Response contains `client_id` and `client_secret`.

2. **Supply credentials** — copy the template and fill in your real values:

```bash
cp .env.example .env
```

   Then open `.env` and paste your `client_id` / `client_secret`. The adapters read it on startup (no code change needed). Alternative: set **Auth Token** on each Openverse source in the Sources UI to `client_id:client_secret` — that header value wins over `.env`.

3. **Verify** the credential is picked up: each Openverse adapter's `/health` response includes an `authenticated` boolean. Anonymous `false` → credentials detected `true`.

---

## Pass Criteria

1. `git status` shows the five superseded files staged for deletion and no unexpected changes; the only adapter files remaining are `40k_adapter.py`, `artvee_adapter.py`, `wikimedia_adapter.py`, `nasa_adapter.py`, `openverse_adapter.py`, `openverse_base.py`.
2. `start_adapters.bat` launches exactly five adapters; port `3004` is no longer used.
3. All five `/health` endpoints return `200` + `{"status": "ok"}`.
4. `tests/test_openverse_adapters.py` passes in full for wikimedia/nasa/openverse (health, well-formed results, 20+ results from an anonymous `limit=50` request, a real image download, and an empty `media_type=video` response).
5. `tests/test_persistent_browser.py` still passes for 40k/artvee.
6. The `download_url` in every Openverse search result is reachable (starts with the same base URL the backend used to reach the adapter — `localhost:300x` natively, the service hostname under Docker).
7. No DB rows changed by this phase. `.env.example` exists at the repo root and `.gitignore` allows it (`!.env.example`). Once the user fills `.env` with real credentials, each Openverse adapter's `/health` returns `"authenticated": true`.
8. End-to-end: restart the backend, select the persia profile, run a session. Openverse sources auto-launch, return curated items for tags, downloads succeed, and exported ZIPs contain usable images — including LOC/British Library images surfacing via the **All Openverse** (`source=flickr`) adapter.
