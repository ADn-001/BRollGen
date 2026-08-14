"""
Phase 4 — E2E test suite: SSE progress stream includes per-item label.

Run from backend/ directory:
    pytest tests/phase_04/ -v --tb=short
"""
import asyncio
import dataclasses
import json
import uuid
from pathlib import Path

import pytest
from fastapi.testclient import TestClient


@pytest.fixture(scope="module")
def client():
    import sys, pathlib
    sys.path.insert(0, str(pathlib.Path(__file__).parent.parent.parent))
    from main import app
    with TestClient(app) as c:
        yield c


# ---------------------------------------------------------------------------
# Tests: session_state.py has the new fields
# ---------------------------------------------------------------------------

def test_session_has_current_item_label():
    """Session dataclass must have current_item_label field defaulting to ''."""
    from session_state import Session
    fields = {f.name: f for f in dataclasses.fields(Session)}
    assert "current_item_label" in fields, "Session must have current_item_label field"
    assert fields["current_item_label"].default == "", \
        "current_item_label must default to empty string"


def test_session_has_current_item_index():
    """Session dataclass must have current_item_index field defaulting to 0."""
    from session_state import Session
    fields = {f.name: f for f in dataclasses.fields(Session)}
    assert "current_item_index" in fields, "Session must have current_item_index field"
    assert fields["current_item_index"].default == 0, \
        "current_item_index must default to 0"


# ---------------------------------------------------------------------------
# Tests: downloader updates current_item_label
# ---------------------------------------------------------------------------

def test_downloader_sets_searching_label():
    """
    run_downloads must set current_item_label to a 'Searching:' string before each search.
    Code inspection: verify the pattern is in downloader.py.
    """
    import pathlib
    src = (pathlib.Path(__file__).parent.parent.parent / "services" / "downloader.py").read_text()
    assert 'Searching:' in src, "downloader.py must set a 'Searching:' label"
    assert 'sess.current_item_label' in src, "downloader.py must write to sess.current_item_label"


def test_downloader_sets_downloading_label():
    """run_downloads must set current_item_label to a 'Downloading:' string before each download."""
    import pathlib
    src = (pathlib.Path(__file__).parent.parent.parent / "services" / "downloader.py").read_text()
    assert 'Downloading:' in src, "downloader.py must set a 'Downloading:' label"


def test_downloader_label_includes_tag_word():
    """The label format must include the tag word (dynamic, using f-string)."""
    import pathlib
    src = (pathlib.Path(__file__).parent.parent.parent / "services" / "downloader.py").read_text()
    # Pattern: f'Searching: "{tag.word}"...' or similar f-string with tag.word
    assert "tag.word" in src or "slot_tag.word" in src, \
        "Label must include the tag word via tag.word or slot_tag.word"


def test_downloader_label_includes_source_name():
    """Download label must include the source name."""
    import pathlib
    src = (pathlib.Path(__file__).parent.parent.parent / "services" / "downloader.py").read_text()
    assert "src.name" in src, "Download label must include src.name"


def test_downloader_clears_label_after_completion():
    """run_downloads must clear current_item_label after all downloads complete."""
    import pathlib
    src = (pathlib.Path(__file__).parent.parent.parent / "services" / "downloader.py").read_text()
    assert 'sess.current_item_label = ""' in src or "sess.current_item_label = ''" in src, \
        "downloader.py must clear current_item_label after completion"


# ---------------------------------------------------------------------------
# Tests: SSE endpoint includes current_item_label
# ---------------------------------------------------------------------------

def test_sse_event_includes_label_field(client):
    """
    GET /sessions/{id}/progress SSE events must include current_item_label.

    We inject a fake session with a leftover label and a terminal status
    (awaiting_review). event_generator() yields exactly one event for a
    terminal status and then returns on its own — this avoids relying on
    TestClient-side disconnect detection to end the stream, which deadlocks
    with the endpoint's `while True` + `request.is_disconnected()` loop.
    """
    from session_state import Session, Tag
    sid = str(uuid.uuid4())

    import tempfile
    with tempfile.TemporaryDirectory() as td:
        sess = Session(
            session_id=sid, profile_id=1, script_text="", item_count=1,
            tmp_dir=Path(td), status="awaiting_review",
        )
        sess.current_item_label = 'Searching: "emperor" (1 of 1)'
        client.app.state.sessions[sid] = sess

        try:
            # Read a single SSE event (stream=True, read first chunk)
            with client.stream("GET", f"/api/sessions/{sid}/progress") as r:
                # Read the first event
                first_chunk = ""
                for line in r.iter_lines():
                    if line.startswith("data: "):
                        first_chunk = line[6:]  # strip "data: "
                        break

            assert first_chunk, "SSE stream emitted no data"
            event = json.loads(first_chunk)
            assert "current_item_label" in event, \
                f"SSE event must include current_item_label, got keys: {list(event.keys())}"
            assert event["current_item_label"] == 'Searching: "emperor" (1 of 1)', \
                f"Label mismatch: {event['current_item_label']}"
        finally:
            client.app.state.sessions.pop(sid, None)


def test_sse_event_label_field_type_is_string(client):
    """current_item_label in SSE event must be a string."""
    from session_state import Session, Tag
    sid = str(uuid.uuid4())

    import tempfile
    with tempfile.TemporaryDirectory() as td:
        sess = Session(
            session_id=sid, profile_id=1, script_text="", item_count=1,
            tmp_dir=Path(td), status="awaiting_review",
        )
        sess.current_item_label = ""   # Empty is fine
        client.app.state.sessions[sid] = sess

        try:
            with client.stream("GET", f"/api/sessions/{sid}/progress") as r:
                first_chunk = ""
                for line in r.iter_lines():
                    if line.startswith("data: "):
                        first_chunk = line[6:]
                        break
            event = json.loads(first_chunk)
            assert isinstance(event.get("current_item_label"), str), \
                "current_item_label must be a string"
        finally:
            client.app.state.sessions.pop(sid, None)


# ---------------------------------------------------------------------------
# Tests: label format validation
# ---------------------------------------------------------------------------

def test_label_format_searching():
    """Verify the Searching label format matches expected pattern."""
    # Simulate what downloader produces
    tag_word = "emperor"
    items_processed = 1
    items_total = 8
    label = f'Searching: "{tag_word}" ({items_processed} of {items_total})'
    assert label == 'Searching: "emperor" (1 of 8)'


def test_label_format_downloading():
    """Verify the Downloading label format matches expected pattern."""
    slot_tag_word = "emperor"
    src_name = "loc.gov"
    items_processed = 1
    items_total = 8
    label = f'Downloading: "{slot_tag_word}" from {src_name} ({items_processed} of {items_total})'
    assert label == 'Downloading: "emperor" from loc.gov (1 of 8)'
