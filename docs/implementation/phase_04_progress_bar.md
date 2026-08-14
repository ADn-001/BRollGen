# Phase 4 — Real-Time Progress Bar with Per-Item Text

**Prerequisite:** None (independent).

**Objective:** The download progress screen shows inline text describing what is currently happening — "Searching: 'emperor' (1 of 8)" during the search phase, "Downloading: 'emperor' from loc.gov (1 of 8)" during the download phase. The progress bar fills based on completed items.

---

## Design

The SSE stream currently emits `{status, completed, total, missing_tags}`. We add `current_item_label` — a human-readable string written by `run_downloads()` before each search and before each download. The SSE generator reads it directly from `sess` every 0.5 s — no thread races because both `run_downloads` and the SSE generator run as coroutines on the same asyncio event loop.

Label format:
- During search: `Searching: "emperor" (1 of 8)`
- During download: `Downloading: "emperor" from loc.gov (1 of 8)`
- After completion: empty string (UI falls back to status text)

---

## Files Changed

| Action | File |
|--------|------|
| EDIT | `backend/session_state.py` |
| EDIT | `backend/services/downloader.py` |
| EDIT | `backend/routers/sessions.py` |
| EDIT | `frontend/src/pages/Dashboard.jsx` |

---

## Implementation Steps

### Step 1 — `backend/session_state.py`

Add two fields to the `Session` dataclass:

```python
@dataclass
class Session:
    # ... existing fields ...
    current_item_label: str = ""     # ← NEW: e.g. 'Searching: "emperor" (1 of 8)'
    current_item_index: int = 0      # ← NEW: 0-based index of the item being processed
```

### Step 2 — `backend/services/downloader.py`

**Add label updates inside `run_downloads()`.**

The outer loop processes each unique tag word group. Add a counter:

```python
async def run_downloads(sess: AppSession, db: Session) -> list[DownloadResult]:
    # ... existing setup code (profile, sources, etc.) ...

    items_total = len(sess.extracted_tags)    # ← NEW: total tag count for label
    items_processed = 0                        # ← NEW: counter

    # ... existing tag_groups setup ...

    for tag in sess.extracted_tags:
        word_key = tag.word.lower()
        if word_key in processed_words and sess.dedupe_repeat_tags:
            continue
        processed_words.add(word_key)

        items_processed += 1                   # ← NEW: increment before labeling
        sess.current_item_index = items_processed - 1    # ← NEW

        # ── Search label ──────────────────────────────────────────────────
        sess.current_item_label = f'Searching: "{tag.word}" ({items_processed} of {items_total})'
        # ─────────────────────────────────────────────────────────────────

        k = len(tag_groups[word_key])
        candidates_with_sources = await _search_tag(tag, sources, limit_per_source, multi_item)

        if not candidates_with_sources:
            logger.info("No results for tag '%s' across all sources.", tag.word)
            continue

        # ... existing distinct/slots/download_plan logic ...

        for slot_tag, cand, src, reused_from_uid in download_plan:
            uid = str(uuid.uuid4())[:8]
            ext = _infer_ext(cand.download_url, None)
            dest = sess.tmp_dir / f"{uid}{ext}"

            # ── Download label ────────────────────────────────────────────
            sess.current_item_label = (
                f'Downloading: "{slot_tag.word}" from {src.name} '
                f'({items_processed} of {items_total})'
            )
            # ─────────────────────────────────────────────────────────────

            try:
                await _apply_source_delay(src, last_download_time)
                # ... rest of existing download logic unchanged ...
```

After the outer loop completes, clear the label:
```python
    # After the loop, results are sorted and returned
    results.sort(key=lambda r: r.tag_occurrence_index)
    sess.current_item_label = ""          # ← NEW: clear on completion
    return results
```

### Step 3 — `backend/routers/sessions.py`

**In the `event_generator()` inside `download_progress_sse`**, add `current_item_label` to the JSON:

```python
async def event_generator():
    while True:
        if await request.is_disconnected():
            break
        data = json.dumps({
            "status": sess.status,
            "completed": len(sess.download_results),
            "total": sess.item_count,
            "missing_tags": sess.missing_tags,
            "current_item_label": sess.current_item_label,    # ← NEW
        })
        yield f"data: {data}\n\n"
        if sess.status not in ("downloading", "analyzing"):
            break
        await asyncio.sleep(0.5)
```

### Step 4 — `frontend/src/pages/Dashboard.jsx`

**In `StepDownload`**, update the progress state and render the label.

Update the `useState` initial value to include the new field:
```jsx
const [progress, setProgress] = useState({
  status: 'downloading',
  completed: 0,
  total: session.item_count,
  current_item_label: '',          // ← NEW
})
```

Add the label text in the progress card, below the progress bar:

```jsx
return (
  <div className="max-w-xl">
    <h2 className="text-2xl font-bold mb-6">Downloading Media</h2>
    <div className="card space-y-4">
      <div className="flex justify-between text-sm text-gray-400">
        <span>Progress</span>
        <span>{progress.completed} / {progress.total}</span>
      </div>
      <div className="w-full bg-gray-800 rounded-full h-3">
        <div
          className="bg-brand-600 h-3 rounded-full transition-all duration-300"
          style={{ width: `${pct}%` }}
        />
      </div>

      {/* ── Per-item label ── */}
      <p className="text-sm text-brand-300 font-mono min-h-[1.25rem]">
        {progress.current_item_label || (progress.status === 'downloading' ? 'Starting…' : '')}
      </p>

      <p className="text-xs text-gray-500 capitalize">
        {progress.status.replace(/_/g, ' ')}
      </p>
    </div>
  </div>
)
```

---

## Test Suite

Save as `backend/tests/phase_04/test_progress_label.py`

```python
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
    sys.path.insert(0, str(pathlib.Path(__file__).parent.parent.parent / "backend"))
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
    src = (pathlib.Path(__file__).parent.parent.parent / "backend" / "services" / "downloader.py").read_text()
    assert 'Searching:' in src, "downloader.py must set a 'Searching:' label"
    assert 'sess.current_item_label' in src, "downloader.py must write to sess.current_item_label"


def test_downloader_sets_downloading_label():
    """run_downloads must set current_item_label to a 'Downloading:' string before each download."""
    import pathlib
    src = (pathlib.Path(__file__).parent.parent.parent / "backend" / "services" / "downloader.py").read_text()
    assert 'Downloading:' in src, "downloader.py must set a 'Downloading:' label"


def test_downloader_label_includes_tag_word():
    """The label format must include the tag word (dynamic, using f-string)."""
    import pathlib
    src = (pathlib.Path(__file__).parent.parent.parent / "backend" / "services" / "downloader.py").read_text()
    # Pattern: f'Searching: "{tag.word}"...' or similar f-string with tag.word
    assert "tag.word" in src or "slot_tag.word" in src, \
        "Label must include the tag word via tag.word or slot_tag.word"


def test_downloader_label_includes_source_name():
    """Download label must include the source name."""
    import pathlib
    src = (pathlib.Path(__file__).parent.parent.parent / "backend" / "services" / "downloader.py").read_text()
    assert "src.name" in src, "Download label must include src.name"


def test_downloader_clears_label_after_completion():
    """run_downloads must clear current_item_label after all downloads complete."""
    import pathlib
    src = (pathlib.Path(__file__).parent.parent.parent / "backend" / "services" / "downloader.py").read_text()
    assert 'sess.current_item_label = ""' in src or "sess.current_item_label = ''" in src, \
        "downloader.py must clear current_item_label after completion"


# ---------------------------------------------------------------------------
# Tests: SSE endpoint includes current_item_label
# ---------------------------------------------------------------------------

def test_sse_event_includes_label_field(client):
    """
    GET /sessions/{id}/progress SSE events must include current_item_label.
    We inject a fake 'downloading' session and read one SSE event.
    """
    from session_state import Session, Tag
    sid = str(uuid.uuid4())

    import tempfile
    with tempfile.TemporaryDirectory() as td:
        sess = Session(
            session_id=sid, profile_id=1, script_text="", item_count=1,
            tmp_dir=Path(td), status="downloading",
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
            tmp_dir=Path(td), status="downloading",
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
```

---

## Terminal Command

```bat
cd /d "D:\yt_vids\automation ecosystem\BRollGen\backend"
python -m pytest tests/phase_04/ -v --tb=short 2>&1
```

---

## Pass Criteria

- All 11 tests green
- During a live download run in the browser: the label text updates in real-time showing the current tag being searched and downloaded
- Label clears after download completes and transitions to "awaiting_review"
- Progress bar still fills correctly based on `completed / total`
