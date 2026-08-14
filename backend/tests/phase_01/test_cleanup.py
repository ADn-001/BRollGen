"""
Phase 1 — E2E test suite: verify stitcher/upscaler are gone and ZIP still works.

Run from backend/ directory:
    pytest tests/phase_01/ -v --tb=short
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
    sys.path.insert(0, str(pathlib.Path(__file__).parent.parent.parent))
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

    # Minimal valid JPEG bytes (1x1 white pixel)
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

    sid = str(uuid.uuid4())
    sess_tmp = tmp_path / sid
    sess_tmp.mkdir()
    img_path = sess_tmp / "abc12345.jpg"
    img_path.write_bytes(_JPEG_1X1)

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

    client.app.state.sessions[sid] = sess
    yield sid
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


def test_settings_put_realesrgan_field_rejected_or_ignored(client):
    """PUT /settings with realesrgan_path must return 200 or 422 — not 500."""
    r = client.put("/api/settings", json={"realesrgan_path": "/some/path"})
    assert r.status_code in (200, 422), f"Unexpected status: {r.status_code}: {r.text}"
    if r.status_code == 200:
        assert "realesrgan_path" not in r.json(), \
            "realesrgan_path must not appear in settings response"
