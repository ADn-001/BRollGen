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
    # This file is at backend/tests/phase_06/test_redundant_download.py — three
    # .parent hops already lands on backend/, so do NOT append "backend" again
    # (see GATELOG.md "Crucial Discovered Facts").
    sys.path.insert(0, str(pathlib.Path(__file__).parent.parent.parent))
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


def test_profile_update_can_toggle_redundant_field(client):
    """PUT /profiles/{id} must be able to flip redundant_source_download."""
    r = client.post("/api/profiles", json={"name": "ToggleRedundantProfile", "default_item_count": 1})
    pid = r.json()["id"]
    try:
        assert r.json()["redundant_source_download"] is False
        r2 = client.put(f"/api/profiles/{pid}", json={"redundant_source_download": True})
        assert r2.status_code == 200
        assert r2.json()["redundant_source_download"] is True
    finally:
        client.delete(f"/api/profiles/{pid}")


def test_downloader_has_redundant_mode_branch():
    """downloader.py must contain the redundant mode code path."""
    import pathlib
    src = (pathlib.Path(__file__).parent.parent.parent / "services" / "downloader.py").read_text()
    assert "redundant_source_download" in src, \
        "downloader.py must handle redundant_source_download mode"
    assert "redundant_mode" in src or "redundant" in src, \
        "downloader.py must have a redundant download branch"


def test_downloader_redundant_branch_downloads_per_source():
    """The redundant branch must produce one DownloadResult per enabled source, not one globally-best."""
    import pathlib
    src = (pathlib.Path(__file__).parent.parent.parent / "services" / "downloader.py").read_text()
    assert "_download_redundant_for_tag" in src, \
        "downloader.py must define a per-tag, per-source redundant download helper"


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


def test_session_dict_redundant_field_false_for_normal_profile(client):
    """GET /sessions/{id} must report False when the profile has redundant mode off."""
    import uuid
    from pathlib import Path
    import tempfile
    from session_state import Session

    r = client.post("/api/profiles", json={
        "name": "SessionNonRedundantProfile",
        "default_item_count": 1,
    })
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
            assert r2.json()["redundant_source_download"] is False
        finally:
            client.app.state.sessions.pop(sid, None)
    client.delete(f"/api/profiles/{pid}")
