# Phase 3 — Duplicate Tags Session Toggle

**Prerequisite:** None (independent of Phases 1 and 2).

**Objective:** Add an "Allow Duplicate Tags" toggle to the Script Analysis input mode. When ON, the same word appearing K times in a script creates K separate tag slots. When OFF (default), repeated words are collapsed into one. The toggle overrides the profile's `dedupe_repeat_tags` setting for this session only. Direct Tags mode is unaffected.

---

## Behavioral Spec

| Toggle State | Effective `dedupe` | Effect |
|---|---|---|
| OFF (default) | `True` (deduplicate) | "emperor emperor emperor" → 1 tag slot |
| ON | `False` (allow dupes) | "emperor emperor emperor" → 3 tag slots, all "emperor" |

When the toggle is ON and the downloader encounters K slots with the same word, it attempts to find K distinct files. If fewer than K distinct files exist, it reuses the best available (current behavior — confirmed satisfactory in change #2 review).

---

## Files Changed

| Action | File |
|--------|------|
| EDIT | `backend/session_state.py` |
| EDIT | `backend/routers/sessions.py` |
| EDIT | `backend/services/analyzer.py` |
| EDIT | `backend/services/downloader.py` |
| EDIT | `frontend/src/pages/Dashboard.jsx` |

---

## Implementation Steps

### Step 1 — `backend/session_state.py`

Add `dedupe_repeat_tags` field to the `Session` dataclass (stores the effective per-session value):

```python
@dataclass
class Session:
    session_id: str
    profile_id: int
    script_text: str
    item_count: int
    extracted_tags: list[Tag] = field(default_factory=list)
    download_results: list[DownloadResult] = field(default_factory=list)
    approved_items: list[DownloadResult] = field(default_factory=list)
    tmp_dir: Path = field(default=None)
    status: Literal["analyzing", "downloading", "awaiting_review", "done", "error"] = "analyzing"
    error_message: str | None = None
    missing_tags: list[str] = field(default_factory=list)
    needs_more_tags: bool = False
    dedupe_repeat_tags: bool = True          # ← NEW: effective for this session
```

### Step 2 — `backend/routers/sessions.py`

**Add `allow_duplicate_tags` to `SessionCreate`:**

```python
class SessionCreate(BaseModel):
    profile_id: int
    script_text: str
    item_count: int | None = None
    analysis_method: str | None = None
    allow_duplicate_tags: bool | None = None   # ← NEW: None → use profile.dedupe_repeat_tags
```

**In `create_session()`, compute effective dedupe value and store on session:**

```python
# After loading `profile` and before creating sess:
if body.allow_duplicate_tags is not None:
    effective_dedupe = not body.allow_duplicate_tags   # allow_dupes=True → dedupe=False
else:
    effective_dedupe = profile.dedupe_repeat_tags      # default: use profile setting

sess = Session(
    session_id=sid,
    profile_id=body.profile_id,
    script_text=body.script_text,
    item_count=item_count,
    tmp_dir=tmp_dir,
    status="analyzing",
    dedupe_repeat_tags=effective_dedupe,               # ← NEW
)
```

**Pass `dedupe_override` to `extract_tags`:**

```python
result = await asyncio.to_thread(
    extract_tags,
    script_text=body.script_text,
    profile=profile,
    n=item_count,
    db=db,
    analysis_method=body.analysis_method,
    dedupe_override=effective_dedupe,                  # ← NEW
)
```

**Add `dedupe_repeat_tags` to `_session_dict`** so the frontend can read the effective value:

```python
def _session_dict(s: Session) -> dict:
    return {
        "session_id": s.session_id,
        "profile_id": s.profile_id,
        "item_count": s.item_count,
        "status": s.status,
        "error_message": s.error_message,
        "needs_more_tags": s.needs_more_tags,
        "dedupe_repeat_tags": s.dedupe_repeat_tags,    # ← NEW
        "extracted_tags": [_tag_dict(t) for t in s.extracted_tags],
        "download_results": [_result_dict(r) for r in s.download_results],
        "missing_tags": s.missing_tags,
    }
```

### Step 3 — `backend/services/analyzer.py`

**Add `dedupe_override` parameter to `extract_tags()`:**

```python
def extract_tags(
    script_text: str,
    profile: NicheProfile,
    n: int,
    db: Session,
    analysis_method: str | None = None,
    dedupe_override: bool | None = None,    # ← NEW
) -> TagExtractionResult:
    ...
    # Replace:
    #   dedupe = profile.dedupe_repeat_tags
    # With:
    dedupe = dedupe_override if dedupe_override is not None else profile.dedupe_repeat_tags
```

The rest of `extract_tags` is unchanged — it already uses `dedupe` throughout.

### Step 4 — `backend/services/downloader.py`

**Change the dedupe check in `run_downloads()` to read from `sess` instead of `profile`:**

Find this line:
```python
if word_key in processed_words and profile.dedupe_repeat_tags:
    continue
```

Replace with:
```python
if word_key in processed_words and sess.dedupe_repeat_tags:
    continue
```

This ensures the downloader respects the per-session effective value, not the profile default.

### Step 5 — `frontend/src/pages/Dashboard.jsx`

**In `StepSetup`, add toggle state and render it in script mode only:**

```jsx
function StepSetup({ onAnalyzed }) {
  const [mode, setMode] = useState('script')
  const [profileId, setProfileId] = useState('')
  const [script, setScript] = useState('')
  const [tagText, setTagText] = useState('')
  const [itemCount, setItemCount] = useState(10)
  const [analysisMethod, setAnalysisMethod] = useState('algorithmic')
  const [showExample, setShowExample] = useState(false)
  const [allowDuplicateTags, setAllowDuplicateTags] = useState(false)   // ← NEW

  // ... existing code ...

  // In the script mode JSX, add the toggle before the Analyze button:
  // (Inside the {mode === 'script' && (...)} block, after the grid with Item Count / Analysis Method)
```

Add this toggle in the script mode section, between the grid and the Analyze button:

```jsx
{/* Duplicate Tags Toggle — script mode only */}
<div className="flex items-center justify-between rounded-lg bg-gray-800/50 border border-gray-700 px-4 py-3">
  <div>
    <p className="text-sm font-medium text-gray-200">Allow Duplicate Tags</p>
    <p className="text-xs text-gray-500 mt-0.5">
      {allowDuplicateTags
        ? 'Each occurrence of the same word creates its own tag slot'
        : 'Repeated words are collapsed into one tag (default)'}
    </p>
  </div>
  <button
    type="button"
    onClick={() => setAllowDuplicateTags(v => !v)}
    className={`relative inline-flex h-6 w-11 flex-shrink-0 rounded-full border-2 border-transparent
      transition-colors duration-200 focus:outline-none
      ${allowDuplicateTags ? 'bg-brand-600' : 'bg-gray-600'}`}
    role="switch"
    aria-checked={allowDuplicateTags}
  >
    <span
      className={`pointer-events-none inline-block h-5 w-5 rounded-full bg-white shadow transform
        transition duration-200 ease-in-out
        ${allowDuplicateTags ? 'translate-x-5' : 'translate-x-0'}`}
    />
  </button>
</div>
```

**Pass `allow_duplicate_tags` in the analyze mutation:**

```jsx
onClick={() => createSession.mutate({
  profile_id: parseInt(profileId),
  script_text: script,
  item_count: itemCount,
  analysis_method: analysisMethod,
  allow_duplicate_tags: allowDuplicateTags,    // ← NEW
})}
```

---

## Test Suite

Save as `backend/tests/phase_03/test_duplicate_toggle.py`

```python
"""
Phase 3 — E2E test suite: duplicate tags session toggle.

Run from backend/ directory:
    pytest tests/phase_03/ -v --tb=short
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
def profile_id(client):
    """Get or create a test profile and return its ID."""
    r = client.get("/api/profiles")
    if r.status_code == 200 and r.json():
        return r.json()[0]["id"]
    # Create a minimal profile
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
    import dataclasses
    from session_state import Session
    field_names = {f.name for f in dataclasses.fields(Session)}
    assert "dedupe_repeat_tags" in field_names, "Session must have dedupe_repeat_tags field"


def test_session_dedupe_default_is_true():
    """Session.dedupe_repeat_tags must default to True."""
    import dataclasses
    from session_state import Session
    for f in dataclasses.fields(Session):
        if f.name == "dedupe_repeat_tags":
            assert f.default is True or (
                hasattr(f, "default") and f.default == True
            ), "dedupe_repeat_tags default must be True"


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
    sid = r.json()["session_id"]
    r2 = client.get(f"/api/sessions/{sid}")
    assert "dedupe_repeat_tags" in r2.json(), "Session response must include dedupe_repeat_tags"
    client.delete(f"/api/sessions/{sid}")


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
    sid = data["session_id"]
    assert data.get("dedupe_repeat_tags") is True, \
        f"allow_duplicate_tags=False must set dedupe_repeat_tags=True, got: {data.get('dedupe_repeat_tags')}"
    client.delete(f"/api/sessions/{sid}")


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
    sid = data["session_id"]
    assert data.get("dedupe_repeat_tags") is False, \
        f"allow_duplicate_tags=True must set dedupe_repeat_tags=False, got: {data.get('dedupe_repeat_tags')}"
    client.delete(f"/api/sessions/{sid}")


def test_omitting_flag_uses_profile_default(client, profile_id):
    """Omitting allow_duplicate_tags must use the profile's dedupe_repeat_tags value."""
    # Get profile's dedupe setting
    r_profile = client.get(f"/api/profiles/{profile_id}")
    profile_dedupe = r_profile.json().get("dedupe_repeat_tags", True)

    r = client.post("/api/sessions", json={
        "profile_id": profile_id,
        "script_text": REPEAT_SCRIPT,
        "item_count": 3,
        "analysis_method": "algorithmic",
        # allow_duplicate_tags omitted intentionally
    })
    assert r.status_code == 201
    data = r.json()
    sid = data["session_id"]
    assert data.get("dedupe_repeat_tags") == profile_dedupe, \
        f"When allow_duplicate_tags is omitted, session.dedupe_repeat_tags must match profile ({profile_dedupe})"
    client.delete(f"/api/sessions/{sid}")


# ---------------------------------------------------------------------------
# Tests: analyzer respects the effective dedupe value
# ---------------------------------------------------------------------------

def test_extract_tags_signature_accepts_dedupe_override():
    """extract_tags() must accept a dedupe_override keyword argument."""
    import inspect
    from services.analyzer import extract_tags
    sig = inspect.signature(extract_tags)
    assert "dedupe_override" in sig.parameters, \
        "extract_tags() must have a dedupe_override parameter"


def test_downloader_reads_sess_dedupe_not_profile():
    """
    Verify downloader.py reads sess.dedupe_repeat_tags, not profile.dedupe_repeat_tags.
    This is a code inspection test — grep for the pattern.
    """
    import pathlib, re
    downloader_path = pathlib.Path(__file__).parent.parent.parent / "backend" / "services" / "downloader.py"
    src = downloader_path.read_text()
    # Must NOT contain the old pattern
    assert "profile.dedupe_repeat_tags" not in src, \
        "downloader.py must not reference profile.dedupe_repeat_tags — use sess.dedupe_repeat_tags"
    # Must contain the new pattern
    assert "sess.dedupe_repeat_tags" in src, \
        "downloader.py must reference sess.dedupe_repeat_tags"
```

---

## Terminal Command

```bat
cd /d "D:\yt_vids\automation ecosystem\BRollGen\backend"
python -m pytest tests/phase_03/ -v --tb=short 2>&1
```

---

## Pass Criteria

- All 10 tests green
- In the browser: toggle button visible only in "Script Analysis" mode (not in Direct Tags mode)
- Toggle ON + submit with script containing repeated word → more tags returned than toggle OFF
- `allow_duplicate_tags` missing from request → profile default respected (no regression)
