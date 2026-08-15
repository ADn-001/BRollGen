"""
Sessions router — Phase 9 (full implementation).
Handles: session create/analyze, tag editing, download orchestration, curation, sweep trigger.
Progress streams use SSE via StreamingResponse.
"""
import asyncio
import json
import shutil
import uuid
from pathlib import Path
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from sqlalchemy.orm import Session as DbSession

from db.database import get_db
from db.models import NicheProfile
from session_state import Session, Tag

router = APIRouter(tags=["sessions"])

DbDep = Annotated[DbSession, Depends(get_db)]

PROJECT_ROOT = Path(__file__).parent.parent.parent
TMP_BASE = PROJECT_ROOT / "tmp"


# ── Helpers ───────────────────────────────────────────────────────────────────

def _get_session(request: Request, session_id: str) -> Session:
    sess = request.app.state.sessions.get(session_id)
    if sess is None:
        raise HTTPException(404, detail="Session not found or expired.")
    return sess


def _tag_dict(t: Tag) -> dict:
    return {
        "word": t.word,
        "source": t.source,
        "occurrence_index": t.occurrence_index,
        "is_duplicate": t.is_duplicate,
    }


def _result_dict(r) -> dict:
    return {
        "tag_word": r.tag.word,
        "tag_occurrence_index": r.tag_occurrence_index,
        "source_id": r.source_id,
        "source_name": r.source_name,
        "file_path": str(r.file_path),
        "media_type": r.media_type,
        "width": r.width,
        "height": r.height,
        "file_size_bytes": r.file_size_bytes,
        "quality_score": r.quality_score,
        "kept": r.kept,
        "reused_from_uid": r.reused_from_uid,
    }


def _session_dict(s: Session) -> dict:
    # redundant_source_download lives on the profile, not the in-memory session —
    # look it up with a short-lived DB session so callers don't have to thread
    # a `db` dependency through every place _session_dict is called.
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
        "session_id": s.session_id,
        "profile_id": s.profile_id,
        "item_count": s.item_count,
        "status": s.status,
        "error_message": s.error_message,
        "needs_more_tags": s.needs_more_tags,
        "dedupe_repeat_tags": s.dedupe_repeat_tags,
        "redundant_source_download": redundant,
        "extracted_tags": [_tag_dict(t) for t in s.extracted_tags],
        "download_results": [_result_dict(r) for r in s.download_results],
        "missing_tags": s.missing_tags,
    }


# ── Session create + analyze ──────────────────────────────────────────────────

class SessionCreate(BaseModel):
    profile_id: int
    script_text: str
    item_count: int | None = None           # defaults to profile.default_item_count
    analysis_method: str | None = None      # "llm" | "algorithmic" — overrides settings
    allow_duplicate_tags: bool | None = None  # None → use profile.dedupe_repeat_tags


@router.post("/sessions", status_code=201)
async def create_session(body: SessionCreate, request: Request, db: DbDep):
    profile = db.get(NicheProfile, body.profile_id)
    if profile is None:
        raise HTTPException(404, detail="Profile not found.")

    sid = str(uuid.uuid4())
    tmp_dir = TMP_BASE / sid
    tmp_dir.mkdir(parents=True, exist_ok=True)

    item_count = body.item_count or profile.default_item_count

    # allow_duplicate_tags=True → dedupe=False; allow_duplicate_tags=False → dedupe=True
    # None → fall back to profile setting
    if body.allow_duplicate_tags is not None:
        effective_dedupe = not body.allow_duplicate_tags
    else:
        effective_dedupe = profile.dedupe_repeat_tags

    sess = Session(
        session_id=sid,
        profile_id=body.profile_id,
        script_text=body.script_text,
        item_count=item_count,
        tmp_dir=tmp_dir,
        status="analyzing",
        dedupe_repeat_tags=effective_dedupe,
    )
    request.app.state.sessions[sid] = sess

    # Run analysis synchronously (fast enough for scripts up to 5k words)
    try:
        from services.analyzer import extract_tags
        result = await asyncio.to_thread(
            extract_tags,
            script_text=body.script_text,
            profile=profile,
            n=item_count,
            db=db,
            analysis_method=body.analysis_method,
            dedupe_override=effective_dedupe,
        )
        sess.extracted_tags = result.tags
        sess.needs_more_tags = result.needs_more
        sess.status = "awaiting_review"
    except Exception as exc:
        sess.status = "error"
        sess.error_message = str(exc)
        import logging
        logging.getLogger(__name__).exception("Tag extraction failed for session %s", sid)

    return _session_dict(sess)


class SessionFromTags(BaseModel):
    profile_id: int
    tags: list[str]              # plain words, one per search call
    item_count: int | None = None  # defaults to len(tags)


@router.post("/sessions/from-tags", status_code=201)
async def create_session_from_tags(body: SessionFromTags, request: Request, db: DbDep):
    """
    Create a session from a user-supplied tag list, bypassing script analysis entirely.
    The session enters awaiting_review immediately so the user can verify/edit tags.
    """
    profile = db.get(NicheProfile, body.profile_id)
    if profile is None:
        raise HTTPException(404, detail="Profile not found.")

    words = [w.strip().lower() for w in body.tags if w.strip()]
    if not words:
        raise HTTPException(400, detail="tags list must contain at least one non-empty word.")

    item_count = body.item_count or len(words)

    sid = str(uuid.uuid4())
    tmp_dir = TMP_BASE / sid
    tmp_dir.mkdir(parents=True, exist_ok=True)

    tags = [
        Tag(word=w, source="manual", occurrence_index=i, is_duplicate=False)
        for i, w in enumerate(words)
    ]

    sess = Session(
        session_id=sid,
        profile_id=body.profile_id,
        script_text="",          # no script — tag-list bypass
        item_count=item_count,
        tmp_dir=tmp_dir,
        status="awaiting_review",
    )
    sess.extracted_tags = tags
    sess.needs_more_tags = len(tags) < item_count

    request.app.state.sessions[sid] = sess
    return _session_dict(sess)


@router.get("/sessions/{session_id}")
def get_session(session_id: str, request: Request):
    return _session_dict(_get_session(request, session_id))


# ── Tag editing ───────────────────────────────────────────────────────────────

class TagsUpdate(BaseModel):
    tags: list[dict]   # list of {word, source, occurrence_index, is_duplicate}


@router.put("/sessions/{session_id}/tags")
def update_session_tags(session_id: str, body: TagsUpdate, request: Request):
    sess = _get_session(request, session_id)
    tags = []
    for i, t in enumerate(body.tags):
        tags.append(Tag(
            word=t.get("word", ""),
            source=t.get("source", "manual"),
            occurrence_index=t.get("occurrence_index", i),
            is_duplicate=t.get("is_duplicate", False),
        ))
    sess.extracted_tags = tags
    sess.needs_more_tags = len(tags) < sess.item_count
    return _session_dict(sess)


# ── Download ──────────────────────────────────────────────────────────────────

@router.post("/sessions/{session_id}/download", status_code=202)
async def start_download(session_id: str, request: Request, db: DbDep):
    sess = _get_session(request, session_id)
    if len(sess.extracted_tags) == 0:
        raise HTTPException(400, detail="No tags to download. Add at least one tag first.")
    if sess.status == "downloading":
        raise HTTPException(409, detail="Download already in progress.")

    sess.status = "downloading"
    sess.download_results = []

    async def _run():
        # Create a fresh DB session — the request-scoped one closes after this handler returns
        from db.database import SessionLocal
        fresh_db = SessionLocal()
        try:
            from services.downloader import run_downloads
            results = await run_downloads(sess=sess, db=fresh_db)
            sess.download_results = results
            sess.missing_tags = [
                t.word for t in sess.extracted_tags
                if not any(r.tag.word == t.word for r in results)
            ]
            sess.status = "awaiting_review"
        except Exception as exc:
            sess.status = "error"
            sess.error_message = str(exc)
            import logging
            logging.getLogger(__name__).exception("Download failed for session %s", session_id)
        finally:
            fresh_db.close()

    asyncio.create_task(_run())
    return {"session_id": session_id, "status": "downloading"}


@router.get("/sessions/{session_id}/progress")
async def download_progress_sse(session_id: str, request: Request):
    """SSE stream — emits session status updates during download."""
    sess = _get_session(request, session_id)

    async def event_generator():
        while True:
            if await request.is_disconnected():
                break
            data = json.dumps({
                "status": sess.status,
                "completed": len(sess.download_results),
                "total": sess.item_count,
                "missing_tags": sess.missing_tags,
                "current_item_label": sess.current_item_label,
            })
            yield f"data: {data}\n\n"
            if sess.status not in ("downloading", "analyzing"):
                break
            await asyncio.sleep(0.5)

    return StreamingResponse(event_generator(), media_type="text/event-stream")


# ── Curation ──────────────────────────────────────────────────────────────────

class CurationUpdate(BaseModel):
    """Map of file_path → kept (true/false)."""
    items: list[dict]   # [{file_path, kept}]


@router.put("/sessions/{session_id}/curation")
def update_curation(session_id: str, body: CurationUpdate, request: Request):
    sess = _get_session(request, session_id)
    path_map = {item["file_path"]: item["kept"] for item in body.items}
    for r in sess.download_results:
        key = str(r.file_path)
        if key in path_map:
            r.kept = path_map[key]
    sess.approved_items = [r for r in sess.download_results if r.kept]
    return _session_dict(sess)


# ── Session cleanup ───────────────────────────────────────────────────────────

@router.delete("/sessions/{session_id}", status_code=204)
def delete_session(session_id: str, request: Request):
    sess = request.app.state.sessions.pop(session_id, None)
    if sess is None:
        raise HTTPException(404, detail="Session not found or already deleted.")
    if sess.tmp_dir and sess.tmp_dir.exists():
        shutil.rmtree(sess.tmp_dir, ignore_errors=True)
