# Phase 2 — VideoStitch Export Button + Adaptive Naming

**Prerequisite:** Phase 1 complete and all tests green.

**Objective:** Add an "Export for VideoStitch" button to the Export step. It produces a ZIP with no-zero-padding filenames (`1_emperor.jpg`, `10_space_marine.jpg`, `100_warpstorm.gif`). The regular "Download ZIP" button is unchanged — still uses `001_` zero-padded names.

**Context:** VideoStitch is an external application that expects filenames without zero-padding. The main ZIP format is preserved for users who prefer zero-padded names for filesystem sorting.

---

## Files Changed

| Action | File |
|--------|------|
| EDIT | `backend/routers/export.py` |
| EDIT | `frontend/src/api.js` |
| EDIT | `frontend/src/pages/Dashboard.jsx` |

---

## Implementation Steps

### Step 1 — `backend/routers/export.py`

Add a new route after the existing `export_zip` route:

```python
@router.get("/{session_id}/export/videostitch")
async def export_videostitch(session_id: str, request: Request):
    """
    Export ZIP with no-zero-padding naming for the VideoStitch application.
    Files are named: 1_emperor.jpg, 10_space_marine.png, 100_warpstorm.gif
    Ordering: chronological by tag_occurrence_index (script appearance order).
    Files are exported as-is — no processing, no upscale, no crop.
    """
    sess = _get_session(request, session_id)
    kept = [r for r in sess.download_results if r.kept]
    if not kept:
        raise HTTPException(400, detail="No kept items to export.")

    kept_sorted = sorted(kept, key=lambda r: r.tag_occurrence_index)
    zip_path = sess.tmp_dir / f"videostitch_{session_id[:8]}.zip"

    def _build_zip():
        with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
            for i, item in enumerate(kept_sorted, start=1):
                tag_slug = item.tag.word.replace(" ", "_").lower()
                ext = item.file_path.suffix.lower()
                dest_name = f"{i}_{tag_slug}{ext}"   # No zero-padding — adaptive width
                zf.write(item.file_path, dest_name)

    await asyncio.to_thread(_build_zip)

    return FileResponse(
        str(zip_path),
        media_type="application/zip",
        filename=zip_path.name,
    )
```

No new imports needed — `asyncio`, `zipfile`, `FileResponse`, `HTTPException`, `Request` are already imported.

### Step 2 — `frontend/src/api.js`

In the `sessionsApi` object, add after `exportZip`:

```js
exportVideoStitch: (id) => `/api/sessions/${id}/export/videostitch`,
```

### Step 3 — `frontend/src/pages/Dashboard.jsx`

In `StepExport`, add the VideoStitch button alongside the existing ZIP button:

```jsx
function StepExport({ session }) {
  return (
    <div className="max-w-xl">
      <h2 className="text-2xl font-bold mb-6">Export</h2>
      <div className="card space-y-5">
        <p className="text-sm text-gray-400">
          {session.download_results?.filter(r => r.kept !== false).length ?? 0} items ready for export.
        </p>

        <div className="space-y-3">
          <a
            href={sessionsApi.exportZip(session.session_id)}
            download
            className="btn-secondary w-full text-center block"
          >
            📦 Download ZIP
            <span className="block text-xs text-gray-500 mt-0.5">Standard format · 001_emperor.jpg</span>
          </a>

          <a
            href={sessionsApi.exportVideoStitch(session.session_id)}
            download
            className="btn-secondary w-full text-center block"
          >
            🎬 Export for VideoStitch
            <span className="block text-xs text-gray-500 mt-0.5">No zero-padding · 1_emperor.jpg</span>
          </a>
        </div>
      </div>
    </div>
  )
}
```

---

## Test Suite

Save as `backend/tests/phase_02/test_videostitch_export.py`

```python
"""
Phase 2 — E2E test suite: VideoStitch ZIP export with adaptive naming.

Run from backend/ directory:
    pytest tests/phase_02/ -v --tb=short
"""
import io
import zipfile
import uuid
import shutil
from pathlib import Path

import pytest
from fastapi.testclient import TestClient


# ---------------------------------------------------------------------------
# Minimal valid JPEG bytes (1x1 white pixel)
# ---------------------------------------------------------------------------
_JPEG_1X1 = (
    b"\xff\xd8\xff\xe0\x00\x10JFIF\x00\x01\x01\x00\x00\x01\x00\x01\x00\x00"
    b"\xff\xdb\x00C\x00\x08\x06\x06\x07\x06\x05\x08\x07\x07\x07\t\t"
    b"\x08\n\x0c\x14\r\x0c\x0b\x0b\x0c\x19\x12\x13\x0f\x14\x1d\x1a"
    b"\x1f\x1e\x1d\x1a\x1c\x1c $.' \",#\x1c\x1c(7),01444\x1f'9=82<.342\x1e\xff\xc0"
    b"\x00\x0b\x08\x00\x01\x00\x01\x01\x01\x11\x00\xff\xc4\x00\x1f\x00"
    b"\x00\x01\x05\x01\x01\x01\x01\x01\x01\x00\x00\x00\x00\x00\x00\x00"
    b"\x00\x01\x02\x03\x04\x05\x06\x07\x08\t\n\x0b\xff\xda\x00\x08\x01"
    b"\x01\x00\x00?\x00\xfb\xd4P\x00\x00\x00\x00\x1f\xff\xd9"
)


@pytest.fixture(scope="module")
def client():
    import sys, pathlib
    sys.path.insert(0, str(pathlib.Path(__file__).parent.parent.parent / "backend"))
    from main import app
    with TestClient(app) as c:
        yield c


def _make_session(client, tmp_path, tags_in_order):
    """
    Inject a session with N fake download results for the given tag list.
    tags_in_order: list of str tag words, in script appearance order.
    Returns session_id.
    """
    from session_state import Session, Tag, DownloadResult

    sid = str(uuid.uuid4())
    sess_tmp = tmp_path / sid
    sess_tmp.mkdir()

    tags = []
    results = []
    for i, word in enumerate(tags_in_order):
        tag = Tag(word=word, source="manual", occurrence_index=i)
        img_path = sess_tmp / f"file_{i:03d}.jpg"
        img_path.write_bytes(_JPEG_1X1)

        result = DownloadResult(
            tag=tag,
            tag_occurrence_index=i,
            source_id=1,
            source_name="test",
            file_path=img_path,
            media_type="image",
            width=1, height=1,
            file_size_bytes=len(_JPEG_1X1),
            quality_score=1.0,
            kept=True,
        )
        tags.append(tag)
        results.append(result)

    sess = Session(
        session_id=sid, profile_id=1, script_text="",
        item_count=len(tags), tmp_dir=sess_tmp, status="awaiting_review",
    )
    sess.extracted_tags = tags
    sess.download_results = results
    client.app.state.sessions[sid] = sess
    return sid


@pytest.fixture()
def session_5(client, tmp_path):
    sid = _make_session(client, tmp_path, ["emperor", "space marine", "chaos", "ultramarines", "warp storm"])
    yield sid
    client.app.state.sessions.pop(sid, None)


@pytest.fixture()
def session_10(client, tmp_path):
    tags = [f"tag_{i}" for i in range(1, 11)]
    sid = _make_session(client, tmp_path, tags)
    yield sid
    client.app.state.sessions.pop(sid, None)


@pytest.fixture()
def session_100(client, tmp_path):
    tags = [f"tag_{i}" for i in range(1, 101)]
    sid = _make_session(client, tmp_path, tags)
    yield sid
    client.app.state.sessions.pop(sid, None)


# ---------------------------------------------------------------------------
# Tests: VideoStitch route exists and returns valid ZIP
# ---------------------------------------------------------------------------

def test_videostitch_route_exists(client, session_5):
    r = client.get(f"/api/sessions/{session_5}/export/videostitch")
    assert r.status_code == 200, f"Expected 200, got {r.status_code}: {r.text}"


def test_videostitch_content_type(client, session_5):
    r = client.get(f"/api/sessions/{session_5}/export/videostitch")
    assert "application/zip" in r.headers.get("content-type", "")


def test_videostitch_is_valid_zip(client, session_5):
    r = client.get(f"/api/sessions/{session_5}/export/videostitch")
    assert zipfile.is_zipfile(io.BytesIO(r.content)), "Response is not a valid ZIP file"


# ---------------------------------------------------------------------------
# Tests: adaptive naming — no zero-padding
# ---------------------------------------------------------------------------

def test_videostitch_single_digit_no_padding(client, session_5):
    """Items 1–9 use '1_', '2_', not '01_' or '001_'."""
    r = client.get(f"/api/sessions/{session_5}/export/videostitch")
    with zipfile.ZipFile(io.BytesIO(r.content)) as zf:
        names = sorted(zf.namelist(), key=lambda n: int(n.split("_")[0]))
    assert names[0].startswith("1_"), f"First file should start with '1_', got: {names[0]}"
    assert names[1].startswith("2_"), f"Second file should start with '2_', got: {names[1]}"
    assert not names[0].startswith("01_"), f"Must not have leading zero: {names[0]}"
    assert not names[0].startswith("001_"), f"Must not have two leading zeros: {names[0]}"


def test_videostitch_ten_items_no_padding(client, session_10):
    """Item 10 uses '10_' not '010_'."""
    r = client.get(f"/api/sessions/{session_10}/export/videostitch")
    with zipfile.ZipFile(io.BytesIO(r.content)) as zf:
        names = sorted(zf.namelist(), key=lambda n: int(n.split("_")[0]))
    assert len(names) == 10
    assert names[9].startswith("10_"), f"10th file should start with '10_', got: {names[9]}"
    assert not names[9].startswith("010_")


def test_videostitch_hundred_items_no_padding(client, session_100):
    """Item 100 uses '100_' not '100_' (correct — just verifying 3 digits for >=100)."""
    r = client.get(f"/api/sessions/{session_100}/export/videostitch")
    with zipfile.ZipFile(io.BytesIO(r.content)) as zf:
        names = sorted(zf.namelist(), key=lambda n: int(n.split("_")[0]))
    assert len(names) == 100
    # Item 100 should start with exactly "100_"
    assert names[99].startswith("100_"), f"100th file should start with '100_', got: {names[99]}"


# ---------------------------------------------------------------------------
# Tests: ordering must be chronological (script occurrence order)
# ---------------------------------------------------------------------------

def test_videostitch_chronological_order(client, session_5):
    """ZIP files must appear in script occurrence order."""
    expected_slugs = ["emperor", "space_marine", "chaos", "ultramarines", "warp_storm"]
    r = client.get(f"/api/sessions/{session_5}/export/videostitch")
    with zipfile.ZipFile(io.BytesIO(r.content)) as zf:
        names = sorted(zf.namelist(), key=lambda n: int(n.split("_")[0]))
    # Strip index prefix and extension to get slug
    actual_slugs = []
    for name in names:
        # "1_emperor.jpg" → "emperor"
        without_prefix = name.split("_", 1)[1]          # "emperor.jpg"
        without_ext = without_prefix.rsplit(".", 1)[0]   # "emperor"
        actual_slugs.append(without_ext)
    assert actual_slugs == expected_slugs, f"Order mismatch: {actual_slugs} vs {expected_slugs}"


# ---------------------------------------------------------------------------
# Tests: regular ZIP is unchanged (still uses 001_ padding)
# ---------------------------------------------------------------------------

def test_regular_zip_still_zero_padded(client, session_5):
    """Regular ZIP export must still produce 001_-style names."""
    r = client.get(f"/api/sessions/{session_5}/export/zip")
    assert r.status_code == 200
    with zipfile.ZipFile(io.BytesIO(r.content)) as zf:
        names = zf.namelist()
    assert names[0].startswith("001_"), f"Regular ZIP first file should be '001_', got: {names[0]}"


def test_regular_zip_and_videostitch_same_count(client, session_5):
    """Both exports must contain the same number of files."""
    r_zip = client.get(f"/api/sessions/{session_5}/export/zip")
    r_vs = client.get(f"/api/sessions/{session_5}/export/videostitch")
    with zipfile.ZipFile(io.BytesIO(r_zip.content)) as zf_zip:
        zip_count = len(zf_zip.namelist())
    with zipfile.ZipFile(io.BytesIO(r_vs.content)) as zf_vs:
        vs_count = len(zf_vs.namelist())
    assert zip_count == vs_count == 5


# ---------------------------------------------------------------------------
# Tests: empty session returns 400
# ---------------------------------------------------------------------------

def test_videostitch_no_kept_items_returns_400(client, tmp_path):
    from session_state import Session, Tag, DownloadResult
    sid = str(uuid.uuid4())
    sess_tmp = tmp_path / sid
    sess_tmp.mkdir()
    tag = Tag(word="emperor", source="manual", occurrence_index=0)
    img_path = sess_tmp / "abc.jpg"
    img_path.write_bytes(_JPEG_1X1)
    result = DownloadResult(
        tag=tag, tag_occurrence_index=0, source_id=1, source_name="test",
        file_path=img_path, media_type="image", width=1, height=1,
        file_size_bytes=len(_JPEG_1X1), quality_score=1.0,
        kept=False,  # ← all dropped
    )
    sess = Session(session_id=sid, profile_id=1, script_text="", item_count=1,
                   tmp_dir=sess_tmp, status="awaiting_review")
    sess.extracted_tags = [tag]
    sess.download_results = [result]
    client.app.state.sessions[sid] = sess
    try:
        r = client.get(f"/api/sessions/{sid}/export/videostitch")
        assert r.status_code == 400, f"Expected 400 for no kept items, got {r.status_code}"
    finally:
        client.app.state.sessions.pop(sid, None)
```

---

## Terminal Command

```bat
cd /d "D:\yt_vids\automation ecosystem\BRollGen\backend"
python -m pytest tests/phase_02/ -v --tb=short 2>&1
```

---

## Pass Criteria

- All 12 tests green
- Both `📦 Download ZIP` and `🎬 Export for VideoStitch` buttons appear in Step 5
- Regular ZIP download confirms `001_` prefix in filenames
- VideoStitch ZIP download confirms `1_` prefix with no leading zeros
- Item 10 in a 10-item session is named `10_…` not `010_…`
