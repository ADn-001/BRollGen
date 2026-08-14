"""
Export router.
ZIP export and missing-tags text export.
"""
import asyncio
import zipfile
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import FileResponse, StreamingResponse
from sqlalchemy.orm import Session

from db.database import get_db
from db.models import NicheProfile

router = APIRouter(prefix="/sessions", tags=["export"])

DbDep = Annotated[Session, Depends(get_db)]


def _get_session(request: Request, session_id: str):
    sess = request.app.state.sessions.get(session_id)
    if sess is None:
        raise HTTPException(404, detail="Session not found or expired.")
    return sess


# ── ZIP Export ────────────────────────────────────────────────────────────────

@router.get("/{session_id}/export/zip")
async def export_zip(session_id: str, request: Request):
    sess = _get_session(request, session_id)
    kept = [r for r in sess.download_results if r.kept]
    if not kept:
        raise HTTPException(400, detail="No kept items to export.")

    # Sort by occurrence_index (script order)
    kept_sorted = sorted(kept, key=lambda r: r.tag_occurrence_index)

    zip_path = sess.tmp_dir / f"broll_export_{session_id[:8]}.zip"

    def _build_zip():
        with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
            for i, item in enumerate(kept_sorted, start=1):
                tag_slug = item.tag.word.replace(" ", "_").lower()
                ext = item.file_path.suffix.lower()
                src = item.file_path
                dest_name = f"{i:03d}_{tag_slug}{ext}"
                zf.write(src, dest_name)

    await asyncio.to_thread(_build_zip)

    return FileResponse(
        str(zip_path),
        media_type="application/zip",
        filename=zip_path.name,
    )


# ── VideoStitch Export ───────────────────────────────────────────────────────

@router.get("/{session_id}/export/videostitch")
async def export_videostitch(session_id: str, request: Request):
    """
    Export ZIP with no-zero-padding naming for the VideoStitch application.
    Files are named: 1_emperor.jpg, 10_space_marine.png, 100_warpstorm.gif
    Ordering: chronological by tag_occurrence_index (script appearance order).
    Files are exported as-is — no processing, no crop.
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
                dest_name = f"{i}_{tag_slug}{ext}"   # no zero-padding
                zf.write(item.file_path, dest_name)

    await asyncio.to_thread(_build_zip)

    return FileResponse(
        str(zip_path),
        media_type="application/zip",
        filename=zip_path.name,
    )


# ── Missing tags export ───────────────────────────────────────────────────────

@router.get("/{session_id}/export/missing-tags")
def export_missing_tags(session_id: str, request: Request, db: DbDep):
    sess = _get_session(request, session_id)
    if not sess.missing_tags:
        raise HTTPException(400, detail="No missing tags for this session.")

    from datetime import datetime
    profile = db.get(NicheProfile, sess.profile_id)
    profile_name = profile.name if profile else str(sess.profile_id)
    ts = datetime.utcnow().strftime("%Y-%m-%d %H:%M")

    lines = [
        "B-Roll Engine — Missing Tags Report",
        f"Session: {ts}",
        f"Profile: {profile_name}",
        "",
        "Tags with no results:",
    ]
    for tag_word in sess.missing_tags:
        lines.append(f"- {tag_word}")

    content = "\n".join(lines) + "\n"
    filename = f"missing_tags_{datetime.utcnow().strftime('%Y%m%d_%H%M%S')}.txt"

    return StreamingResponse(
        iter([content]),
        media_type="text/plain",
        headers={"Content-Disposition": f"attachment; filename={filename}"},
    )
