"""
Phase 3 — E2E test suite: duplicate tags session toggle.

Run from backend/ directory:
    pytest tests/phase_03/ -v --tb=short
"""
import dataclasses
import inspect

import pytest
from fastapi.testclient import TestClient


@pytest.fixture(scope="module")
def client():
    import sys, pathlib
    sys.path.insert(0, str(pathlib.Path(__file__).parent.parent.parent))
    from main import app
    with TestClient(app) as c:
        yield c


@pytest.fixture(scope="module")
def profile_id(client):
    """Return the first existing profile ID, or create a minimal one."""
    r = client.get("/api/profiles")
    if r.status_code == 200 and r.json():
        return r.json()[0]["id"]
    r = client.post("/api/profiles", json={
        "name": "Phase3TestProfile",
        "dedupe_repeat_tags": True,
        "default_item_count": 5,
    })
    assert r.status_code == 201, r.text
    return r.json()["id"]


REPEAT_SCRIPT = "The emperor stood tall. The emperor raised his hand. The emperor spoke."


# ---------------------------------------------------------------------------
# Tests: session_state.py has dedupe_repeat_tags field
# ---------------------------------------------------------------------------

def test_session_dataclass_has_dedupe_field():
    """Session dataclass must have a dedupe_repeat_tags field."""
    from session_state import Session
    field_names = {f.name for f in dataclasses.fields(Session)}
    assert "dedupe_repeat_tags" in field_names, "Session must have dedupe_repeat_tags field"


def test_session_dedupe_default_is_true():
    """Session.dedupe_repeat_tags must default to True."""
    from session_state import Session
    for f in dataclasses.fields(Session):
        if f.name == "dedupe_repeat_tags":
            assert f.default is True, "dedupe_repeat_tags default must be True"


# ---------------------------------------------------------------------------
# Tests: API honors the allow_duplicate_tags flag
# ---------------------------------------------------------------------------

def test_session_create_accepts_allow_duplicate_tags(client, profile_id):
    """POST /sessions must accept allow_duplicate_tags without 422."""
    r = client.post("/api/sessions", json={
        "profile_id": profile_id,
        "script_text": REPEAT_SCRIPT,
        "item_count": 3,
        "analysis_method": "algorithmic",
        "allow_duplicate_tags": True,
    })
    assert r.status_code == 201, f"Expected 201, got {r.status_code}: {r.text}"
    sid = r.json()["session_id"]
    client.delete(f"/api/sessions/{sid}")


def test_session_dict_includes_dedupe_flag(client, profile_id):
    """GET /sessions/{id} response must include dedupe_repeat_tags."""
    r = client.post("/api/sessions", json={
        "profile_id": profile_id,
        "script_text": REPEAT_SCRIPT,
        "item_count": 3,
        "analysis_method": "algorithmic",
        "allow_duplicate_tags": False,
    })
    assert r.status_code == 201
    data = r.json()
    assert "dedupe_repeat_tags" in data, "Session response must include dedupe_repeat_tags"
    client.delete(f"/api/sessions/{data['session_id']}")


def test_allow_duplicate_false_maps_to_dedupe_true(client, profile_id):
    """allow_duplicate_tags=False → session.dedupe_repeat_tags=True."""
    r = client.post("/api/sessions", json={
        "profile_id": profile_id,
        "script_text": REPEAT_SCRIPT,
        "item_count": 3,
        "analysis_method": "algorithmic",
        "allow_duplicate_tags": False,
    })
    assert r.status_code == 201
    data = r.json()
    assert data.get("dedupe_repeat_tags") is True, \
        f"allow_duplicate_tags=False must set dedupe_repeat_tags=True, got: {data.get('dedupe_repeat_tags')}"
    client.delete(f"/api/sessions/{data['session_id']}")


def test_allow_duplicate_true_maps_to_dedupe_false(client, profile_id):
    """allow_duplicate_tags=True → session.dedupe_repeat_tags=False."""
    r = client.post("/api/sessions", json={
        "profile_id": profile_id,
        "script_text": REPEAT_SCRIPT,
        "item_count": 3,
        "analysis_method": "algorithmic",
        "allow_duplicate_tags": True,
    })
    assert r.status_code == 201
    data = r.json()
    assert data.get("dedupe_repeat_tags") is False, \
        f"allow_duplicate_tags=True must set dedupe_repeat_tags=False, got: {data.get('dedupe_repeat_tags')}"
    client.delete(f"/api/sessions/{data['session_id']}")


def test_omitting_flag_uses_profile_default(client, profile_id):
    """Omitting allow_duplicate_tags must use the profile's dedupe_repeat_tags value."""
    r_profile = client.get(f"/api/profiles/{profile_id}")
    profile_dedupe = r_profile.json().get("dedupe_repeat_tags", True)

    r = client.post("/api/sessions", json={
        "profile_id": profile_id,
        "script_text": REPEAT_SCRIPT,
        "item_count": 3,
        "analysis_method": "algorithmic",
        # allow_duplicate_tags intentionally omitted
    })
    assert r.status_code == 201
    data = r.json()
    assert data.get("dedupe_repeat_tags") == profile_dedupe, \
        f"When allow_duplicate_tags is omitted, session.dedupe_repeat_tags must match profile ({profile_dedupe})"
    client.delete(f"/api/sessions/{data['session_id']}")


# ---------------------------------------------------------------------------
# Tests: analyzer and downloader code inspection
# ---------------------------------------------------------------------------

def test_extract_tags_signature_accepts_dedupe_override():
    """extract_tags() must accept a dedupe_override keyword argument."""
    from services.analyzer import extract_tags
    sig = inspect.signature(extract_tags)
    assert "dedupe_override" in sig.parameters, \
        "extract_tags() must have a dedupe_override parameter"


def test_downloader_reads_sess_dedupe_not_profile():
    """
    downloader.py must reference sess.dedupe_repeat_tags, not profile.dedupe_repeat_tags.
    """
    import pathlib
    src = (pathlib.Path(__file__).parent.parent.parent / "services" / "downloader.py").read_text()
    assert "profile.dedupe_repeat_tags" not in src, \
        "downloader.py must not reference profile.dedupe_repeat_tags — use sess.dedupe_repeat_tags"
    assert "sess.dedupe_repeat_tags" in src, \
        "downloader.py must reference sess.dedupe_repeat_tags"
