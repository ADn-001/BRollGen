"""
Preview router — serve tmp session media files for in-browser preview.
"""
from pathlib import Path

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import FileResponse

router = APIRouter(prefix="/preview", tags=["preview"])

PROJECT_ROOT = Path(__file__).parent.parent.parent
TMP_BASE = PROJECT_ROOT / "tmp"


@router.get("/{session_id}/{filename:path}")
def serve_preview(session_id: str, filename: str, request: Request):
    """
    Serve a file from tmp/{session_id}/ for media preview.
    Only serves files that belong to an active session (security check).
    """
    sess = request.app.state.sessions.get(session_id)
    if sess is None:
        raise HTTPException(404, detail="Session not found.")

    # Resolve and validate path is inside the session's tmp dir
    target = (TMP_BASE / session_id / filename).resolve()
    session_dir = (TMP_BASE / session_id).resolve()
    if not str(target).startswith(str(session_dir)):
        raise HTTPException(403, detail="Access denied.")
    if not target.exists():
        raise HTTPException(404, detail="File not found.")

    return FileResponse(str(target))
