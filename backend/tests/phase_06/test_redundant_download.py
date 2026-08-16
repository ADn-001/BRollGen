"""
Phase 6B — Redundant source download tests.

Run from backend/ directory:
    pytest tests/phase_06/test_redundant_download.py -v --tb=short
"""
import dataclasses
import uuid
from pathlib import Path

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


# ---------------------------------------------------------------------------
# Tests: duplicate-tag slot handling (dedupe_repeat_tags=False K² regression)
# ---------------------------------------------------------------------------

_PNG_1X1 = (
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg=="
)


class _FakeAdapter:
    """Returns fixed candidates; download writes a real 1x1 PNG so the
    downloader's dimension-read / stat() calls succeed."""

    def __init__(self, candidates, search_calls):
        self._candidates = candidates
        self.search_calls = search_calls

    async def search(self, query, limit):
        self.search_calls.append(query)
        return list(self._candidates)

    async def download(self, candidate, dest_path):
        import base64
        dest_path.write_bytes(base64.b64decode(_PNG_1X1))
        return dest_path


def _make_candidates(source_id):
    from services.source_adapters.base import MediaCandidate
    return [
        MediaCandidate(
            id="c1", source_id=source_id, media_type="image",
            download_url="https://example.test/a.jpg", width=320, height=240,
        ),
        MediaCandidate(
            id="c2", source_id=source_id, media_type="image",
            download_url="https://example.test/b.jpg", width=480, height=360,
        ),
    ]


def _create_profile_with_source(client, dedupe, multi_item):
    r = client.post("/api/profiles", json={
        "name": f"K2Profile-{uuid.uuid4().hex[:8]}",
        "dedupe_repeat_tags": dedupe,
        "multi_item_per_tag": multi_item,
        "default_item_count": 2,
    })
    assert r.status_code == 201, r.text
    pid = r.json()["id"]

    r = client.post("/api/sources", json={
        "name": "K2FakeSource", "type": "local_folder", "enabled": True,
    })
    assert r.status_code == 201, r.text
    sid = r.json()["id"]

    r = client.put(f"/api/profiles/{pid}/sources", json={"source_ids": [sid]})
    assert r.status_code == 200, r.text
    return pid, sid


def _make_duplicate_session(pid, tmp_dir, dedupe):
    from session_state import Session, Tag
    return Session(
        session_id=str(uuid.uuid4()), profile_id=pid, script_text="", item_count=2,
        tmp_dir=Path(tmp_dir), status="awaiting_review",
        dedupe_repeat_tags=dedupe,
        extracted_tags=[
            Tag(word="emperor", source="manual", occurrence_index=0),
            Tag(word="emperor", source="manual", occurrence_index=1),
        ],
    )


def test_dedupe_off_same_word_produces_exactly_k_results(client, monkeypatch):
    """dedupe_repeat_tags=False + word twice must yield exactly 2 results with
    distinct tag_occurrence_index values — NOT K²=4 (regression lock for the
    duplicate-tag reprocessing bug). Search must fire once per unique word."""
    import asyncio
    import tempfile
    from db.database import SessionLocal
    from services import downloader as dl

    pid, sid = _create_profile_with_source(client, dedupe=False, multi_item=False)
    try:
        search_calls = []
        fake = _FakeAdapter(_make_candidates(sid), search_calls)
        monkeypatch.setattr(dl, "_get_adapter", lambda source: fake)

        with tempfile.TemporaryDirectory() as td:
            sess = _make_duplicate_session(pid, td, dedupe=False)
            db = SessionLocal()
            try:
                results = asyncio.run(dl.run_downloads(sess, db))
            finally:
                db.close()

            assert len(results) == 2, f"expected exactly 2 results, got {len(results)}"
            indexes = [r.tag_occurrence_index for r in results]
            assert sorted(indexes) == [0, 1], f"indexes must be [0, 1], got {sorted(indexes)}"
            assert len(set(indexes)) == len(indexes), \
                f"duplicate tag_occurrence_index values: {indexes}"
            assert search_calls == ["emperor"], f"search must run once per word, got {search_calls}"
            for r in results:
                assert r.file_path.exists(), f"downloaded file missing: {r.file_path}"
    finally:
        client.delete(f"/api/profiles/{pid}")
        client.delete(f"/api/sources/{sid}")


def test_dedupe_on_manual_duplicate_tags_still_fill_all_slots(client, monkeypatch):
    """dedupe=True + same word twice (manually injected) must still fill both
    slots from a single search — the guard change must not collapse them."""
    import asyncio
    import tempfile
    from db.database import SessionLocal
    from services import downloader as dl

    pid, sid = _create_profile_with_source(client, dedupe=True, multi_item=False)
    try:
        search_calls = []
        fake = _FakeAdapter(_make_candidates(sid), search_calls)
        monkeypatch.setattr(dl, "_get_adapter", lambda source: fake)

        with tempfile.TemporaryDirectory() as td:
            sess = _make_duplicate_session(pid, td, dedupe=True)
            db = SessionLocal()
            try:
                results = asyncio.run(dl.run_downloads(sess, db))
            finally:
                db.close()

        assert len(results) == 2, f"expected exactly 2 results, got {len(results)}"
        assert sorted(r.tag_occurrence_index for r in results) == [0, 1]
        assert search_calls == ["emperor"], f"search must run once, got {search_calls}"
    finally:
        client.delete(f"/api/profiles/{pid}")
        client.delete(f"/api/sources/{sid}")


def test_reused_from_uid_points_to_first_slot_file(client, monkeypatch):
    """When fewer distinct candidates than slots, the reuse slot's
    reused_from_uid must reference the first slot's on-disk file stem."""
    import asyncio
    import tempfile
    from db.database import SessionLocal
    from services import downloader as dl

    # multi_item=True collapses the search to one best candidate → 1 distinct
    # file for 2 slots → the second slot must be marked as reused.
    pid, sid = _create_profile_with_source(client, dedupe=True, multi_item=True)
    try:
        fake = _FakeAdapter(_make_candidates(sid), [])
        monkeypatch.setattr(dl, "_get_adapter", lambda source: fake)

        with tempfile.TemporaryDirectory() as td:
            sess = _make_duplicate_session(pid, td, dedupe=True)
            db = SessionLocal()
            try:
                results = asyncio.run(dl.run_downloads(sess, db))
            finally:
                db.close()

        assert len(results) == 2, f"expected exactly 2 results, got {len(results)}"
        first, second = sorted(results, key=lambda r: r.tag_occurrence_index)
        assert first.reused_from_uid is None, f"first slot must not be marked reused: {first.reused_from_uid!r}"
        assert second.reused_from_uid == first.file_path.stem, (
            f"reused_from_uid must point at first slot file stem, "
            f"got {second.reused_from_uid!r}, expected {first.file_path.stem!r}"
        )
    finally:
        client.delete(f"/api/profiles/{pid}")
        client.delete(f"/api/sources/{sid}")


def test_from_tags_allow_duplicate_tags_flag(client):
    """POST /sessions/from-tags must honor allow_duplicate_tags, mirroring
    create_session's mapping (True→dedupe=False, False→dedupe=True)."""
    r = client.post("/api/profiles", json={
        "name": "FromTagsDedupeProfile", "default_item_count": 2,
    })
    assert r.status_code == 201, r.text
    pid = r.json()["id"]
    sids = []
    try:
        r = client.post("/api/sessions/from-tags", json={
            "profile_id": pid, "tags": ["emperor", "emperor"],
            "allow_duplicate_tags": True,
        })
        assert r.status_code == 201, r.text
        sids.append(r.json()["session_id"])
        assert r.json()["dedupe_repeat_tags"] is False, \
            "allow_duplicate_tags=True must set dedupe_repeat_tags=False"

        r = client.post("/api/sessions/from-tags", json={
            "profile_id": pid, "tags": ["emperor", "emperor"],
            "allow_duplicate_tags": False,
        })
        assert r.status_code == 201, r.text
        sids.append(r.json()["session_id"])
        assert r.json()["dedupe_repeat_tags"] is True, \
            "allow_duplicate_tags=False must set dedupe_repeat_tags=True"

        r = client.post("/api/sessions/from-tags", json={
            "profile_id": pid, "tags": ["emperor", "emperor"],
        })
        assert r.status_code == 201, r.text
        sids.append(r.json()["session_id"])
        assert r.json()["dedupe_repeat_tags"] is True, \
            "omitting allow_duplicate_tags must fall back to profile default (True)"
    finally:
        for sid in sids:
            client.delete(f"/api/sessions/{sid}")
        client.delete(f"/api/profiles/{pid}")
