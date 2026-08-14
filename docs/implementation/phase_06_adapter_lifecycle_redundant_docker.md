# Phase 6 — Adapter Lifecycle Management + Redundant Source Download + Docker

**Prerequisite:** Phase 5 complete (persistent browser adapters must be working).

**Objective:** Three interconnected improvements:
1. **Adapter auto-launch**: when the user selects a profile, the app health-checks all custom_adapter sources linked to that profile and auto-starts any that aren't running.
2. **Redundant source download**: a new profile toggle that downloads the best result from EACH source per tag (instead of the globally best one), then groups them in the review step so the user can pick what they want.
3. **Docker Compose**: one container per adapter, one container for the main app.

---

## Open Design Decisions (Resolved Before Coding)

Before implementing Phase 6 code, confirm answers to these questions (stored in GATELOG):

| # | Question | Assumed Answer |
|---|----------|----------------|
| OQ1 | How many items downloaded per source per tag in redundant mode? | 1 (best quality per source) |
| OQ2 | If user keeps 2 "emperor" files from different sources, how numbered in ZIP? | Sequential: `1_emperor.jpg`, `2_emperor.jpg`, `3_space_marine.jpg` |
| OQ3 | `adapter_script_path` stored where? | In `MediaSource.config` JSON as `"adapter_script_path"` key |
| OQ4 | If adapter fails to start after 10s: blocking or warning-only? | Warning-only (non-blocking, session proceeds) |

---

## Files Changed

| Action | File |
|--------|------|
| EDIT | `backend/db/models.py` |
| NEW | `backend/db/versions/xxxx_add_redundant_source_download.py` (Alembic) |
| EDIT | `backend/routers/profiles.py` |
| EDIT | `backend/services/downloader.py` |
| EDIT | `backend/routers/sessions.py` |
| EDIT | `frontend/src/api.js` |
| EDIT | `frontend/src/pages/Dashboard.jsx` |
| EDIT | `frontend/src/pages/Profiles.jsx` |
| NEW | `docker-compose.yml` |
| NEW | `Dockerfile` |
| NEW | `CustomAdapters/wh40k/Dockerfile` |

---

## Implementation Steps

### PART A — Adapter Lifecycle Management

#### Step A1 — Add `adapter_script_path` to Sources UI

`MediaSource.config` is a JSON blob. The `custom_adapter` source type already has `adapter_url` and `auth_token` keys in its config. Add `adapter_script_path` as a new optional key — no DB migration needed (it's just a JSON key).

In `frontend/src/pages/Sources.jsx` (or wherever the custom_adapter form is rendered), add a text input for `adapter_script_path`. Label: "Adapter Script Path (for auto-launch)" with help text: "Full path to the adapter .py file. The app will launch it when this source's profile is selected."

Example: `D:\yt_vids\automation ecosystem\BRollGen\CustomAdapters\wh40k\40k_adapter.py`

#### Step A2 — New backend endpoint `POST /api/profiles/{id}/adapters/start`

Add to `backend/routers/profiles.py`:

```python
import asyncio
import sys
import subprocess

@router.post("/{profile_id}/adapters/start")
async def start_profile_adapters(profile_id: int, request: Request, db: DbDep):
    """
    For each custom_adapter source linked to this profile:
    1. Health-check the adapter_url.
    2. If healthy → already running, skip.
    3. If unhealthy + adapter_script_path configured → launch subprocess.
    4. Wait up to 10s for health check to pass.
    5. Return status for each adapter (non-blocking — failures are warnings only).
    """
    from db.models import ProfileSourceLink, MediaSource
    import httpx

    links = (
        db.query(ProfileSourceLink)
        .filter(ProfileSourceLink.profile_id == profile_id)
        .all()
    )
    custom_sources = [
        lnk.source for lnk in links
        if lnk.source and lnk.source.type == "custom_adapter" and lnk.source.enabled
    ]

    if not hasattr(request.app.state, "adapter_processes"):
        request.app.state.adapter_processes = {}

    results = []

    async def _health_check(adapter_url: str) -> bool:
        try:
            async with httpx.AsyncClient(timeout=3.0) as client:
                r = await client.get(f"{adapter_url.rstrip('/')}/health")
                return r.status_code == 200
        except Exception:
            return False

    for source in custom_sources:
        cfg = source.config or {}
        adapter_url = cfg.get("adapter_url", "").rstrip("/")
        script_path = cfg.get("adapter_script_path", "")

        if not adapter_url:
            results.append({
                "source": source.name,
                "status": "skipped",
                "reason": "no adapter_url configured",
            })
            continue

        # Check if already running
        if await _health_check(adapter_url):
            results.append({"source": source.name, "status": "already_running"})
            continue

        if not script_path:
            results.append({
                "source": source.name,
                "status": "not_running",
                "reason": "adapter_script_path not configured — start it manually",
            })
            continue

        # Launch the adapter subprocess
        try:
            proc = subprocess.Popen(
                [sys.executable, script_path],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                # Windows: don't create a new console window
                creationflags=subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0,
            )
            request.app.state.adapter_processes[adapter_url] = proc
        except Exception as exc:
            results.append({
                "source": source.name,
                "status": "launch_failed",
                "reason": str(exc),
            })
            continue

        # Wait up to 10s for health check to pass (non-blocking — 20 × 0.5s)
        started = False
        for _ in range(20):
            await asyncio.sleep(0.5)
            if await _health_check(adapter_url):
                started = True
                break

        results.append({
            "source": source.name,
            "status": "started" if started else "start_timeout",
        })

    return {"adapters": results}
```

#### Step A3 — Shutdown hook for adapter processes

In `backend/main.py`, extend the lifespan shutdown:

```python
@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup
    TMP_DIR.mkdir(parents=True, exist_ok=True)
    _sweep_old_tmp_folders()
    app.state.sessions: dict[str, object] = {}
    app.state.adapter_processes: dict[str, object] = {}   # ← NEW
    logger.info("B-Roll Engine started. Tmp dir: %s", TMP_DIR)
    yield
    # Shutdown
    for url, proc in getattr(app.state, "adapter_processes", {}).items():
        try:
            proc.terminate()
            logger.info("Terminated adapter process for %s", url)
        except Exception:
            pass
    logger.info("B-Roll Engine shutting down.")
```

#### Step A4 — Frontend: trigger adapter start on profile selection

In `frontend/src/api.js`, add to `profilesApi`:

```js
startAdapters: (id) => api.post(`/profiles/${id}/adapters/start`).then((r) => r.data),
```

In `frontend/src/pages/Dashboard.jsx`, update `handleProfileChange` in `StepSetup`:

```jsx
const handleProfileChange = (id) => {
    setProfileId(id)
    const p = profiles.find((p) => String(p.id) === id)
    if (p) {
        setItemCount(p.default_item_count)
        // Auto-start adapters for this profile (fire-and-forget — non-blocking)
        if (id) {
            profilesApi.startAdapters(id)
                .then((result) => {
                    const started = result.adapters?.filter(a => a.status === 'started') || []
                    const failed = result.adapters?.filter(
                        a => a.status === 'start_timeout' || a.status === 'launch_failed'
                    ) || []
                    if (started.length > 0) {
                        console.log(`Started adapters: ${started.map(a => a.source).join(', ')}`)
                    }
                    if (failed.length > 0) {
                        console.warn(`Adapter start issues: ${JSON.stringify(failed)}`)
                    }
                })
                .catch(() => {
                    // Non-fatal — adapters may already be running or user manages them manually
                })
        }
    }
}
```

---

### PART B — Redundant Source Download

#### Step B1 — DB model: add `redundant_source_download` to `NicheProfile`

In `backend/db/models.py`:

```python
class NicheProfile(Base):
    # ... existing columns ...
    redundant_source_download = Column(Boolean, nullable=False, default=False)  # ← NEW
```

#### Step B2 — Alembic migration

Run `alembic revision --autogenerate -m "add_redundant_source_download"` then verify the generated migration file. The migration must add:

```python
# In upgrade():
op.add_column(
    'niche_profiles',
    sa.Column('redundant_source_download', sa.Boolean(), nullable=False, server_default='0')
)

# In downgrade():
op.drop_column('niche_profiles', 'redundant_source_download')
```

Apply with: `alembic upgrade head`

#### Step B3 — Expose in profile CRUD

In `backend/routers/profiles.py`:
- Add `redundant_source_download: bool = False` to `ProfileCreate` and `ProfileUpdate` Pydantic models
- Add `"redundant_source_download": p.redundant_source_download` to `_profile_dict()`
- Apply in `create_profile()` and `update_profile()` handlers

#### Step B4 — Downloader: redundant mode

In `backend/services/downloader.py`, inside `run_downloads()`, add a new download path when `profile.redundant_source_download` is True:

```python
redundant_mode = profile.redundant_source_download   # ← read once

for tag in sess.extracted_tags:
    word_key = tag.word.lower()
    if word_key in processed_words and sess.dedupe_repeat_tags:
        continue
    processed_words.add(word_key)

    if redundant_mode:
        # ── Redundant mode: download best 1 per source ────────────────
        for source in sources:
            if not source.enabled:
                continue
            sess.current_item_label = f'Searching: "{tag.word}" from {source.name}'
            try:
                adapter = _get_adapter(source)
                candidates = await adapter.search(tag.word, 5)
                if not candidates:
                    continue
                for c in candidates:
                    c.quality_score = _compute_quality_score(c, c.media_type)
                best = max(candidates, key=lambda c: c.quality_score)

                uid = str(uuid.uuid4())[:8]
                ext = _infer_ext(best.download_url, None)
                dest = sess.tmp_dir / f"{uid}{ext}"

                sess.current_item_label = f'Downloading: "{tag.word}" from {source.name}'
                await _apply_source_delay(source, last_download_time)
                saved_path = await _download_candidate(adapter, best, dest)
                last_download_time[source.id] = time.monotonic()

                # .bin extension fix (same as non-redundant path)
                if saved_path.suffix.lower() == ".bin":
                    _BIN_EXT_MAP = {"jpeg": ".jpg", "png": ".png", "webp": ".webp",
                                    "gif": ".gif", "bmp": ".bmp"}
                    try:
                        with Image.open(saved_path) as _img:
                            _real_ext = _BIN_EXT_MAP.get((_img.format or "").lower())
                        if _real_ext:
                            _new_path = saved_path.with_suffix(_real_ext)
                            saved_path.rename(_new_path)
                            saved_path = _new_path
                    except Exception:
                        pass

                size_bytes = saved_path.stat().st_size
                w, h = best.width, best.height
                if best.media_type == "image":
                    img_w, img_h = _read_image_dimensions(saved_path)
                    if img_w and img_h:
                        w, h = img_w, img_h

                results.append(DownloadResult(
                    tag=tag,
                    tag_occurrence_index=tag.occurrence_index,
                    source_id=source.id,
                    source_name=source.name,
                    file_path=saved_path,
                    media_type=best.media_type,
                    width=w, height=h,
                    file_size_bytes=size_bytes,
                    quality_score=float(w * h) if (w and h) else float(size_bytes) * 0.001,
                    kept=True,
                ))
            except Exception as exc:
                logger.warning(
                    "Redundant download failed for tag '%s' from source '%s': %s",
                    tag.word, source.name, exc,
                )
        # end redundant_mode per-source loop
    else:
        # ── Standard mode: existing logic unchanged ────────────────────
        # ... all existing candidate selection / download_plan logic ...
```

#### Step B5 — Review UI: grouped curation when redundant mode

After a redundant download, `download_results` contains multiple items per tag (one per source). The curation step should group them.

In `backend/routers/sessions.py`, no change needed — all download results are already returned in `_session_dict`.

In `frontend/src/pages/Dashboard.jsx`, update `StepCuration` to detect redundant mode and render grouped:

```jsx
function StepCuration({ session, onProceed }) {
  const [items, setItems] = useState(
    (session.download_results || []).map((r) => ({ ...r, kept: true }))
  )

  const isRedundant = session.redundant_source_download   // ← from session dict (via profile)

  const toggle = (filePath) => setItems((its) =>
    its.map((r) => r.file_path === filePath ? { ...r, kept: !r.kept } : r)
  )

  const keptCount = items.filter(r => r.kept).length

  // Group items by tag_word for redundant mode display
  const grouped = items.reduce((acc, item) => {
    const key = item.tag_word
    if (!acc[key]) acc[key] = []
    acc[key].push(item)
    return acc
  }, {})

  // ... update/curation mutation stays the same ...

  if (isRedundant && Object.keys(grouped).length > 0) {
    return (
      <div>
        <div className="flex items-center justify-between mb-6">
          <div>
            <h2 className="text-2xl font-bold">Review Media</h2>
            <p className="text-gray-400 text-sm mt-1">
              {keptCount} of {items.length} items kept · {Object.keys(grouped).length} tags
            </p>
          </div>
          {/* Keep All / Drop All buttons */}
        </div>

        {/* Grouped view */}
        {Object.entries(grouped).map(([tagWord, tagItems]) => (
          <div key={tagWord} className="mb-8">
            <div className="flex items-center gap-2 mb-3">
              <span className="text-xs font-bold text-brand-400 uppercase tracking-wide">TAG</span>
              <h3 className="text-sm font-bold text-gray-200">{tagWord}</h3>
              <span className="text-xs text-gray-500">{tagItems.filter(i => i.kept).length} kept</span>
            </div>
            <div className="grid grid-cols-2 md:grid-cols-3 lg:grid-cols-4 gap-3">
              {tagItems.map((item, i) => (
                <ItemCard key={i} item={item} session={session} onToggle={toggle} />
              ))}
            </div>
          </div>
        ))}

        <button
          className="btn-primary mt-4"
          disabled={keptCount === 0 || updateCuration.isPending}
          onClick={() => updateCuration.mutate(items)}
        >
          {updateCuration.isPending ? 'Saving…' : 'Proceed to Export'}
        </button>
      </div>
    )
  }

  // Non-redundant: existing flat grid view (unchanged)
  return (/* existing JSX */)
}
```

Extract `ItemCard` as a shared subcomponent used by both flat and grouped views.

Note: `session.redundant_source_download` needs to be included in `_session_dict`. Add it to `sessions.py`:

```python
def _session_dict(s: Session) -> dict:
    from db.database import SessionLocal
    _db = SessionLocal()
    try:
        from db.models import NicheProfile
        profile = _db.get(NicheProfile, s.profile_id)
        redundant = profile.redundant_source_download if profile else False
    except Exception:
        redundant = False
    finally:
        _db.close()
    return {
        ...existing fields...,
        "redundant_source_download": redundant,    # ← NEW
    }
```

#### Step B6 — Profile UI: add redundant_source_download toggle

In `frontend/src/pages/Profiles.jsx`, in the profile editor form, add a toggle for `redundant_source_download` alongside the existing `multi_item_per_tag` and `dedupe_repeat_tags` toggles. Label: "Redundant Source Download" with description: "Download the best result from each source per tag. Shows all variants in review so you can pick the best or keep extras as additional B-roll."

---

### PART C — Docker Compose

#### Step C1 — Main app `Dockerfile`

Save as `D:\yt_vids\automation ecosystem\BRollGen\Dockerfile`:

```dockerfile
FROM python:3.11-slim

WORKDIR /app

# System deps for Playwright and Pillow
RUN apt-get update && apt-get install -y \
    libglib2.0-0 libnss3 libatk1.0-0 libatk-bridge2.0-0 \
    libcups2 libdrm2 libxkbcommon0 libxcomposite1 libxdamage1 \
    libxrandr2 libgbm1 libpango-1.0-0 libcairo2 libasound2 \
    libjpeg62-turbo libpng16-16 libwebp7 \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Install spaCy model
RUN python -m spacy download en_core_web_sm

COPY backend/ ./backend/
COPY frontend/dist/ ./frontend/dist/
COPY alembic.ini .
COPY alembic/ ./alembic/

WORKDIR /app/backend

# Run migrations then start the server
CMD ["sh", "-c", "alembic upgrade head && uvicorn main:app --host 0.0.0.0 --port 7420"]

EXPOSE 7420
```

#### Step C2 — Adapter `Dockerfile`

Save as `D:\yt_vids\automation ecosystem\BRollGen\CustomAdapters\wh40k\Dockerfile`:

```dockerfile
FROM python:3.11-slim

# Playwright system deps
RUN apt-get update && apt-get install -y \
    libglib2.0-0 libnss3 libatk1.0-0 libatk-bridge2.0-0 \
    libcups2 libdrm2 libxkbcommon0 libxcomposite1 libxdamage1 \
    libxrandr2 libgbm1 libpango-1.0-0 libcairo2 libasound2 \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /adapter

COPY requirements.txt .
RUN pip install --no-cache-dir flask requests beautifulsoup4 playwright

RUN playwright install chromium
RUN playwright install-deps chromium

# ADAPTER_SCRIPT is the entrypoint — set per-service in docker-compose.yml
ARG ADAPTER_SCRIPT=40k_adapter.py
COPY ${ADAPTER_SCRIPT} ./adapter.py

CMD ["python", "adapter.py"]
```

#### Step C3 — `docker-compose.yml`

Save as `D:\yt_vids\automation ecosystem\BRollGen\docker-compose.yml`:

```yaml
version: "3.9"

services:

  app:
    build:
      context: .
      dockerfile: Dockerfile
    ports:
      - "7420:7420"
    volumes:
      - ./tmp:/app/backend/tmp
      - ./broll.db:/app/backend/broll.db
    environment:
      - PYTHONUNBUFFERED=1
    depends_on:
      adapter-wh40k:
        condition: service_healthy
      adapter-artvee:
        condition: service_healthy
      adapter-loc:
        condition: service_healthy
    restart: unless-stopped

  adapter-wh40k:
    build:
      context: ./CustomAdapters/wh40k
      dockerfile: Dockerfile
      args:
        ADAPTER_SCRIPT: 40k_adapter.py
    ports:
      - "3000:3000"
    healthcheck:
      test: ["CMD", "python", "-c", "import urllib.request; urllib.request.urlopen('http://localhost:3000/health')"]
      interval: 10s
      timeout: 5s
      retries: 5
      start_period: 30s
    restart: unless-stopped

  adapter-artvee:
    build:
      context: ./CustomAdapters/wh40k
      dockerfile: Dockerfile
      args:
        ADAPTER_SCRIPT: artvee_adapter.py
    ports:
      - "3001:3001"
    healthcheck:
      test: ["CMD", "python", "-c", "import urllib.request; urllib.request.urlopen('http://localhost:3001/health')"]
      interval: 10s
      timeout: 5s
      retries: 5
      start_period: 30s
    restart: unless-stopped

  adapter-loc:
    build:
      context: ./CustomAdapters/wh40k
      dockerfile: Dockerfile
      args:
        ADAPTER_SCRIPT: loc_adapter.py
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

**Note for Docker usage:** In Docker, adapter URLs in the DB source configs must point to `http://adapter-wh40k:3000` (container name), not `http://localhost:3000`. For local Windows use, keep `localhost`. This is a DB configuration difference — document this in a `DOCKER_SETUP.md` file.

---

## Test Suite

Save as `backend/tests/phase_06/test_adapter_lifecycle.py`

```python
"""
Phase 6A — Adapter lifecycle management tests.

Run from backend/ directory (app must be running or use TestClient):
    pytest tests/phase_06/test_adapter_lifecycle.py -v --tb=short
"""
import pytest
from fastapi.testclient import TestClient


@pytest.fixture(scope="module")
def client():
    import sys, pathlib
    sys.path.insert(0, str(pathlib.Path(__file__).parent.parent.parent / "backend"))
    from main import app
    with TestClient(app) as c:
        yield c


@pytest.fixture(scope="module")
def profile_with_adapter(client):
    """Create a source + profile with a custom_adapter source that has adapter_script_path."""
    import pathlib
    adapter_script = str(
        pathlib.Path(__file__).parent.parent.parent.parent /
        "CustomAdapters" / "wh40k" / "loc_adapter.py"
    )
    # Create source
    r = client.post("/api/sources", json={
        "name": "Phase6TestAdapter",
        "type": "custom_adapter",
        "config": {
            "adapter_url": "http://localhost:3002",
            "adapter_script_path": adapter_script,
        },
        "enabled": True,
    })
    source_id = r.json()["id"]

    # Create profile
    r = client.post("/api/profiles", json={
        "name": "Phase6TestProfile",
        "default_item_count": 1,
    })
    profile_id = r.json()["id"]

    # Link source to profile
    client.put(f"/api/profiles/{profile_id}/sources", json={"source_ids": [source_id]})

    yield profile_id, source_id

    # Cleanup
    client.delete(f"/api/profiles/{profile_id}")
    client.delete(f"/api/sources/{source_id}")


def test_start_adapters_endpoint_exists(client, profile_with_adapter):
    profile_id, _ = profile_with_adapter
    r = client.post(f"/api/profiles/{profile_id}/adapters/start")
    assert r.status_code == 200, f"Expected 200, got {r.status_code}: {r.text}"


def test_start_adapters_returns_adapter_list(client, profile_with_adapter):
    profile_id, _ = profile_with_adapter
    r = client.post(f"/api/profiles/{profile_id}/adapters/start")
    data = r.json()
    assert "adapters" in data, "Response must contain 'adapters' key"
    assert isinstance(data["adapters"], list)


def test_start_adapters_result_has_source_name_and_status(client, profile_with_adapter):
    profile_id, _ = profile_with_adapter
    r = client.post(f"/api/profiles/{profile_id}/adapters/start")
    for adapter in r.json().get("adapters", []):
        assert "source" in adapter
        assert "status" in adapter
        assert adapter["status"] in (
            "already_running", "started", "start_timeout",
            "launch_failed", "not_running", "skipped"
        )


def test_start_adapters_profile_no_custom_sources(client):
    """Profile with no custom_adapter sources returns empty adapter list."""
    r = client.post("/api/profiles", json={"name": "NoAdapterProfile", "default_item_count": 1})
    pid = r.json()["id"]
    try:
        r2 = client.post(f"/api/profiles/{pid}/adapters/start")
        assert r2.status_code == 200
        assert r2.json().get("adapters") == []
    finally:
        client.delete(f"/api/profiles/{pid}")


def test_app_state_has_adapter_processes(client):
    """app.state must have adapter_processes dict after startup."""
    assert hasattr(client.app.state, "adapter_processes"), \
        "app.state must have adapter_processes dict"
    assert isinstance(client.app.state.adapter_processes, dict)
```

Save as `backend/tests/phase_06/test_redundant_download.py`

```python
"""
Phase 6B — Redundant source download tests.

Run from backend/ directory:
    pytest tests/phase_06/test_redundant_download.py -v --tb=short
"""
import dataclasses
import pytest
from fastapi.testclient import TestClient


@pytest.fixture(scope="module")
def client():
    import sys, pathlib
    sys.path.insert(0, str(pathlib.Path(__file__).parent.parent.parent / "backend"))
    from main import app
    with TestClient(app) as c:
        yield c


def test_niche_profile_has_redundant_field():
    """NicheProfile DB model must have redundant_source_download column."""
    from db.models import NicheProfile
    columns = {c.name for c in NicheProfile.__table__.columns}
    assert "redundant_source_download" in columns, \
        "NicheProfile must have redundant_source_download column"


def test_profile_crud_exposes_redundant_field(client):
    """POST /profiles and GET /profiles/{id} must include redundant_source_download."""
    r = client.post("/api/profiles", json={
        "name": "RedundantTestProfile",
        "redundant_source_download": True,
        "default_item_count": 1,
    })
    assert r.status_code == 201, r.text
    pid = r.json()["id"]
    try:
        assert "redundant_source_download" in r.json(), \
            "POST /profiles response must include redundant_source_download"
        assert r.json()["redundant_source_download"] is True

        r2 = client.get(f"/api/profiles/{pid}")
        assert r2.json()["redundant_source_download"] is True
    finally:
        client.delete(f"/api/profiles/{pid}")


def test_profile_redundant_default_is_false(client):
    """redundant_source_download must default to False."""
    r = client.post("/api/profiles", json={
        "name": "DefaultRedundantProfile",
        "default_item_count": 1,
    })
    assert r.status_code == 201
    pid = r.json()["id"]
    try:
        assert r.json().get("redundant_source_download") is False, \
            "redundant_source_download must default to False"
    finally:
        client.delete(f"/api/profiles/{pid}")


def test_downloader_has_redundant_mode_branch():
    """downloader.py must contain the redundant mode code path."""
    import pathlib
    src = (pathlib.Path(__file__).parent.parent.parent / "backend" / "services" / "downloader.py").read_text()
    assert "redundant_source_download" in src, \
        "downloader.py must handle redundant_source_download mode"
    assert "redundant_mode" in src or "redundant" in src, \
        "downloader.py must have a redundant download branch"


def test_session_dict_includes_redundant_field(client):
    """GET /sessions/{id} must include redundant_source_download from the profile."""
    import uuid
    from pathlib import Path
    import tempfile
    from session_state import Session, Tag

    # Create a profile with redundant=True
    r = client.post("/api/profiles", json={
        "name": "SessionRedundantProfile",
        "redundant_source_download": True,
        "default_item_count": 1,
    })
    assert r.status_code == 201
    pid = r.json()["id"]

    sid = str(uuid.uuid4())
    with tempfile.TemporaryDirectory() as td:
        sess = Session(
            session_id=sid, profile_id=pid, script_text="",
            item_count=1, tmp_dir=Path(td), status="awaiting_review",
        )
        client.app.state.sessions[sid] = sess
        try:
            r2 = client.get(f"/api/sessions/{sid}")
            assert r2.status_code == 200
            assert "redundant_source_download" in r2.json(), \
                "GET /sessions/{id} must include redundant_source_download"
            assert r2.json()["redundant_source_download"] is True
        finally:
            client.app.state.sessions.pop(sid, None)
    client.delete(f"/api/profiles/{pid}")
```

---

## Terminal Commands

```bat
REM Phase 6 tests
cd /d "D:\yt_vids\automation ecosystem\BRollGen\backend"
python -m pytest tests/phase_06/ -v --tb=short 2>&1

REM Alembic migration
cd /d "D:\yt_vids\automation ecosystem\BRollGen"
alembic revision --autogenerate -m "add_redundant_source_download"
alembic upgrade head

REM Docker build (requires Docker Desktop running)
cd /d "D:\yt_vids\automation ecosystem\BRollGen"
docker-compose build
docker-compose up
```

---

## Pass Criteria

- All Phase 6 backend tests green
- Alembic migration applies cleanly (`alembic upgrade head` exits 0)
- Selecting a profile in the UI triggers an adapter health check (observable in browser DevTools Network tab as a POST to `/api/profiles/{id}/adapters/start`)
- Profile editor shows "Redundant Source Download" toggle
- With redundant mode ON and 2 sources: a download session produces 2 `DownloadResult` entries per tag (one per source)
- Review page shows grouped view when redundant mode is active
- `docker-compose build` completes without error for all 4 services
- `docker-compose up`: all 4 containers start; `docker-compose ps` shows all healthy
