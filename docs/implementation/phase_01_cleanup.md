# Phase 1 — Remove Stitcher / Upscaler

**Objective:** Strip out all video stitching and image processing code. Media files download and export exactly as received — untouched. ZIP export is the only output path.

**Constraint:** No stubs. No dead imports. App must start clean with no warnings about missing modules.

---

## Files Changed

| Action | File |
|--------|------|
| DELETE | `backend/services/stitcher.py` |
| DELETE | `backend/services/upscaler.py` |
| EDIT | `backend/routers/export.py` |
| EDIT | `backend/routers/sessions.py` |
| EDIT | `backend/session_state.py` |
| EDIT | `backend/routers/settings.py` |
| EDIT | `frontend/src/api.js` |
| EDIT | `frontend/src/pages/Dashboard.jsx` |

---

## Implementation Steps

### Step 1 — Delete stitcher.py and upscaler.py

Delete both files entirely. Do not leave empty files or stubs.

```
D:\yt_vids\automation ecosystem\BRollGen\backend\services\stitcher.py   → DELETE
D:\yt_vids\automation ecosystem\BRollGen\backend\services\upscaler.py   → DELETE
```

### Step 2 — `backend/session_state.py`

**Remove** from `DownloadResult` dataclass:
- `needs_upscale: bool = False`
- `upscale_applied: Literal["none", "lanczos", "realesrgan"] = "none"`

**Remove** from `Session.status` Literal:
- `"stitching"`
- `"sweeping"`

After change the `Session.status` Literal must be exactly:
```python
status: Literal["analyzing", "downloading", "awaiting_review", "done", "error"] = "analyzing"
```

### Step 3 — `backend/routers/sessions.py`

**Remove** these two routes entirely (including their async def bodies):
- `POST /sessions/{session_id}/sweep`
- `GET /sessions/{session_id}/sweep-progress`

**Remove** from `_result_dict()`:
- `"needs_upscale": r.needs_upscale,`
- `"upscale_applied": r.upscale_applied,`

**Remove** unused import if present: `from services.upscaler import run_sweep`

### Step 4 — `backend/routers/export.py`

**Remove** these two routes entirely:
- `POST /sessions/{session_id}/export/video` (the stitch trigger)
- `GET /sessions/{session_id}/export/video/download`

**Remove** unused imports:
- `from pydantic import BaseModel` — only needed for `ExportOptions`; remove both
- `class ExportOptions(BaseModel): ...` — delete entirely

**In the `_build_zip()` inner function inside `export_zip`**, remove the `_processed` file lookup. The current code checks:
```python
if item.media_type == "image":
    processed = item.file_path.parent / f"{item.file_path.stem}_processed{ext}"
    src = processed if processed.exists() else item.file_path
else:
    src = item.file_path
```
Replace with simply:
```python
src = item.file_path
```

**Remove** unused import: `from db.models import NicheProfile` (no longer needed in export.py after video route removal). Verify no other route in the file uses it before removing.

**Remove** the `DbDep` type alias if no remaining route uses it:
```python
DbDep = Annotated[Session, Depends(get_db)]
```

### Step 5 — `backend/routers/settings.py`

**Remove** the entire `POST /settings/test-realesrgan` endpoint (lines containing `@router.post("/settings/test-realesrgan")` through the closing `return` statement).

**Remove** `import subprocess` at the top of the file (used only by test-realesrgan). Confirm it's not used elsewhere in the file.

**Remove** `realesrgan_path` from `SettingsUpdate`:
```python
class SettingsUpdate(BaseModel):
    ffmpeg_path: str | None = None
    tmp_path: str | None = None
    # realesrgan_path REMOVED
    analysis_method: str | None = None
```

**Remove** from `update_app_settings()`:
```python
if body.realesrgan_path is not None:
    s.realesrgan_path = body.realesrgan_path or None
```

**Keep** `realesrgan_path` in `_settings_dict()` return value — it remains a DB column and the GET endpoint can still surface it (harmless read). Actually, remove it from `_settings_dict` too for a clean API. Removing it from the dict means the frontend can't accidentally display a stale value.

### Step 6 — `frontend/src/api.js`

**Remove** from `sessionsApi`:
- `triggerSweep: (id) => api.post(...)`
- `exportVideo: (id, opts) => api.post(...)`
- `downloadVideo: (id) => ...`

**Remove** from `settingsApi`:
- `testRealesrgan: () => api.post('/settings/test-realesrgan')...`

### Step 7 — `frontend/src/pages/Dashboard.jsx`

**Gut the `StepExport` component.** Replace the current implementation with a stripped-down version:

```jsx
function StepExport({ session }) {
  return (
    <div className="max-w-xl">
      <h2 className="text-2xl font-bold mb-6">Export</h2>
      <div className="card space-y-5">
        <p className="text-sm text-gray-400">
          {session.download_results?.filter(r => r.kept !== false).length ?? 0} items ready for export.
        </p>
        <a
          href={sessionsApi.exportZip(session.session_id)}
          download
          className="btn-secondary w-full text-center block"
        >
          📦 Download ZIP
        </a>
      </div>
    </div>
  )
}
```

Remove all state (`imageDuration`, `stitching`, `done`), remove `startStitch` mutation, remove `sessionsApi.exportVideo` and `sessionsApi.downloadVideo` call sites.

---

## Test Suite

Save as `backend/tests/phase_01/test_cleanup.py`

```python
"""
Phase 1 — E2E test suite: verify stitcher/upscaler are gone and ZIP still works.

Run from backend/ directory:
    pytest tests/phase_01/ -v
"""
import dataclasses
import importlib
import io
import zipfile

import pytest
from fastapi.testclient import TestClient

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(scope="module")
def client():
    """Create a TestClient against the FastAPI app."""
    import sys, pathlib
    sys.path.insert(0, str(pathlib.Path(__file__).parent.parent.parent / "backend"))
    from main import app
    with TestClient(app) as c:
        yield c


@pytest.fixture()
def live_session(client, tmp_path):
    """
    Create a session with one fake download result injected directly into
    app.state so ZIP export can run without needing a real internet connection.
    """
    import uuid, shutil
    from session_state import Session, Tag, DownloadResult

    # Create a small real image file in tmp so ZipFile can actually read it
    fake_img = tmp_path / "fake.jpg"
    # Minimal valid JPEG bytes (1x1 white pixel)
    fake_img.write_bytes(
        b"\xff\xd8\xff\xe0\x00\x10JFIF\x00\x01\x01\x00\x00\x01\x00\x01\x00\x00"
        b"\xff\xdb\x00C\x00\x08\x06\x06\x07\x06\x05\x08\x07\x07\x07\t\t"
        b"\x08\n\x0c\x14\r\x0c\x0b\x0b\x0c\x19\x12\x13\x0f\x14\x1d\x1a"
        b"\x1f\x1e\x1d\x1a\x1c\x1c $.' \",#\x1c\x1c(7),01444\x1f'9=82<.342\x1e\xff\xc0"
        b"\x00\x0b\x08\x00\x01\x00\x01\x01\x01\x11\x00\xff\xc4\x00\x1f\x00"
        b"\x00\x01\x05\x01\x01\x01\x01\x01\x01\x00\x00\x00\x00\x00\x00\x00"
        b"\x00\x01\x02\x03\x04\x05\x06\x07\x08\t\n\x0b\xff\xc4\x00\xb5\x10"
        b"\x00\x02\x01\x03\x03\x02\x04\x03\x05\x05\x04\x04\x00\x00\x01}"
        b"\x01\x02\x03\x00\x04\x11\x05\x12!1A\x06\x13Qa\x07\"q\x142\x81\x91"
        b"\xa1\x08#B\xb1\xc1\x15R\xd1\xf0$3br\x82\t\n\x16\x17\x18\x19\x1a"
        b"%&'()*456789:CDEFGHIJSTUVWXYZcdefghijstuvwxyz\x83\x84\x85\x86\x87"
        b"\x88\x89\x8a\x92\x93\x94\x95\x96\x97\x98\x99\x9a\xa2\xa3\xa4\xa5"
        b"\xa6\xa7\xa8\xa9\xaa\xb2\xb3\xb4\xb5\xb6\xb7\xb8\xb9\xba\xc2\xc3"
        b"\xc4\xc5\xc6\xc7\xc8\xc9\xca\xd2\xd3\xd4\xd5\xd6\xd7\xd8\xd9\xda"
        b"\xe1\xe2\xe3\xe4\xe5\xe6\xe7\xe8\xe9\xea\xf1\xf2\xf3\xf4\xf5\xf6"
        b"\xf7\xf8\xf9\xfa\xff\xda\x00\x08\x01\x01\x00\x00?\x00\xfb\xd4P\x00"
        b"\x00\x00\x00\x1f\xff\xd9"
    )

    sid = str(uuid.uuid4())
    sess_tmp = tmp_path / sid
    sess_tmp.mkdir()
    # Copy fake image into session tmp dir
    img_path = sess_tmp / "abc12345.jpg"
    shutil.copy(fake_img, img_path)

    tag = Tag(word="emperor", source="manual", occurrence_index=0)
    result = DownloadResult(
        tag=tag,
        tag_occurrence_index=0,
        source_id=1,
        source_name="test_source",
        file_path=img_path,
        media_type="image",
        width=1,
        height=1,
        file_size_bytes=img_path.stat().st_size,
        quality_score=1.0,
        kept=True,
    )

    sess = Session(
        session_id=sid,
        profile_id=1,
        script_text="",
        item_count=1,
        tmp_dir=sess_tmp,
        status="awaiting_review",
    )
    sess.extracted_tags = [tag]
    sess.download_results = [result]

    # Inject into app state
    client.app.state.sessions[sid] = sess
    yield sid
    # Cleanup
    client.app.state.sessions.pop(sid, None)


# ---------------------------------------------------------------------------
# Tests: deleted modules
# ---------------------------------------------------------------------------

def test_stitcher_module_deleted():
    """services.stitcher must not be importable — file should be deleted."""
    with pytest.raises(ModuleNotFoundError):
        importlib.import_module("services.stitcher")


def test_upscaler_module_deleted():
    """services.upscaler must not be importable — file should be deleted."""
    with pytest.raises(ModuleNotFoundError):
        importlib.import_module("services.upscaler")


# ---------------------------------------------------------------------------
# Tests: removed API routes
# ---------------------------------------------------------------------------

def test_video_export_route_gone(client, live_session):
    """POST /sessions/{id}/export/video must be 404 or 405."""
    r = client.post(f"/api/sessions/{live_session}/export/video", json={"image_duration": 5})
    assert r.status_code in (404, 405), f"Expected 404/405, got {r.status_code}: {r.text}"


def test_video_download_route_gone(client, live_session):
    """GET /sessions/{id}/export/video/download must be 404 or 405."""
    r = client.get(f"/api/sessions/{live_session}/export/video/download")
    assert r.status_code in (404, 405), f"Expected 404/405, got {r.status_code}: {r.text}"


def test_sweep_route_gone(client, live_session):
    """POST /sessions/{id}/sweep must be 404 or 405."""
    r = client.post(f"/api/sessions/{live_session}/sweep")
    assert r.status_code in (404, 405), f"Expected 404/405, got {r.status_code}: {r.text}"


def test_sweep_progress_route_gone(client, live_session):
    """GET /sessions/{id}/sweep-progress must be 404 or 405."""
    r = client.get(f"/api/sessions/{live_session}/sweep-progress")
    assert r.status_code in (404, 405), f"Expected 404/405, got {r.status_code}: {r.text}"


def test_realesrgan_test_route_gone(client):
    """POST /settings/test-realesrgan must be 404 or 405."""
    r = client.post("/api/settings/test-realesrgan")
    assert r.status_code in (404, 405), f"Expected 404/405, got {r.status_code}: {r.text}"


# ---------------------------------------------------------------------------
# Tests: session_state.py dataclass changes
# ---------------------------------------------------------------------------

def test_session_status_excludes_stitching_sweeping():
    """Status Literal must not contain 'stitching' or 'sweeping'."""
    import typing
    from session_state import Session
    hints = typing.get_type_hints(Session)
    status_args = typing.get_args(hints["status"])
    assert "stitching" not in status_args, "'stitching' must be removed from status Literal"
    assert "sweeping" not in status_args, "'sweeping' must be removed from status Literal"


def test_download_result_has_no_upscale_fields():
    """DownloadResult must not have needs_upscale or upscale_applied."""
    from session_state import DownloadResult
    field_names = {f.name for f in dataclasses.fields(DownloadResult)}
    assert "needs_upscale" not in field_names, "needs_upscale must be removed from DownloadResult"
    assert "upscale_applied" not in field_names, "upscale_applied must be removed from DownloadResult"


def test_download_result_still_has_core_fields():
    """DownloadResult must still have all required core fields."""
    from session_state import DownloadResult
    required = {"tag", "tag_occurrence_index", "source_id", "source_name",
                "file_path", "media_type", "width", "height",
                "file_size_bytes", "quality_score", "kept"}
    field_names = {f.name for f in dataclasses.fields(DownloadResult)}
    missing = required - field_names
    assert not missing, f"DownloadResult is missing fields: {missing}"


# ---------------------------------------------------------------------------
# Tests: ZIP export still works correctly
# ---------------------------------------------------------------------------

def test_zip_export_returns_200(client, live_session):
    """GET /sessions/{id}/export/zip must return 200."""
    r = client.get(f"/api/sessions/{live_session}/export/zip")
    assert r.status_code == 200, f"ZIP export failed: {r.text}"


def test_zip_export_content_type(client, live_session):
    """ZIP export Content-Type must be application/zip."""
    r = client.get(f"/api/sessions/{live_session}/export/zip")
    assert "application/zip" in r.headers.get("content-type", "")


def test_zip_contains_original_file_not_processed(client, live_session):
    """ZIP must contain the original downloaded file, not a _processed variant."""
    r = client.get(f"/api/sessions/{live_session}/export/zip")
    with zipfile.ZipFile(io.BytesIO(r.content)) as zf:
        names = zf.namelist()
    assert len(names) == 1
    assert "_processed" not in names[0], f"ZIP should not contain _processed file, got: {names}"


def test_zip_naming_uses_zero_padding(client, live_session):
    """Regular ZIP export must still use 001_ zero-padded prefix."""
    r = client.get(f"/api/sessions/{live_session}/export/zip")
    with zipfile.ZipFile(io.BytesIO(r.content)) as zf:
        names = zf.namelist()
    assert names[0].startswith("001_"), f"Expected '001_' prefix, got: {names[0]}"


def test_session_dict_no_upscale_fields(client, live_session):
    """GET /sessions/{id} response must not include needs_upscale or upscale_applied."""
    r = client.get(f"/api/sessions/{live_session}")
    assert r.status_code == 200
    data = r.json()
    results = data.get("download_results", [])
    assert len(results) > 0
    for item in results:
        assert "needs_upscale" not in item, "needs_upscale must not appear in API response"
        assert "upscale_applied" not in item, "upscale_applied must not appear in API response"


def test_settings_put_ignores_realesrgan(client):
    """PUT /settings with realesrgan_path field must not crash — field silently ignored."""
    r = client.put("/api/settings", json={"realesrgan_path": "/some/path"})
    # Should succeed (200) or be silently stripped — not 422 or 500
    assert r.status_code in (200, 422), f"Unexpected status: {r.status_code}"
    # If 200: realesrgan_path should not appear in response
    if r.status_code == 200:
        assert "realesrgan_path" not in r.json() or r.json().get("realesrgan_path") is None
```

---

## Terminal Command

Run from the `backend/` directory (with venv activated):

```bat
cd /d "D:\yt_vids\automation ecosystem\BRollGen\backend"
python -m pytest tests/phase_01/ -v --tb=short 2>&1
```

---

## Pass Criteria

All 16 tests green. Additionally verify manually:

- `python -c "from services import stitcher"` → raises `ModuleNotFoundError`
- `python -c "from services import upscaler"` → raises `ModuleNotFoundError`
- App starts with `uvicorn main:app --port 7420` and shows no import errors in console
- Navigating to Step 5 (Export) in the browser shows only "Download ZIP" button — no video controls

---

## Rollback Plan

If tests fail mid-way:
1. `git diff` to see current state
2. `git stash` to revert all changes
3. Re-read this plan and restart from the failing step
