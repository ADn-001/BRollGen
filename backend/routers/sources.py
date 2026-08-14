"""
Sources router — Phase 3.
CRUD for MediaSource and source connectivity test.
"""
import logging
import shutil
from pathlib import Path
from typing import Annotated

import httpx
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from db.database import get_db
from db.models import MediaSource, ProfileSourceLink

logger = logging.getLogger(__name__)

router = APIRouter(tags=["sources"])

DbDep = Annotated[Session, Depends(get_db)]

# Every file this app lets a source own gets uploaded into one of these two
# <source_id>-keyed directories (see backend/routers/uploads.py) — a
# local_folder source's media library, or a custom_adapter source's uploaded
# script. Deleting a source should take that directory with it, or the files
# just sit there forever with nothing left pointing at them.
PROJECT_ROOT = Path(__file__).parent.parent.parent
LOCAL_LIBRARIES_DIR = PROJECT_ROOT / "local_libraries"
UPLOADED_ADAPTERS_DIR = PROJECT_ROOT / "CustomAdapters" / "uploaded"

VALID_SOURCE_TYPES = {
    "pexels", "pixabay", "unsplash",
    "serp_scraper", "custom_adapter", "local_folder",
}


def _source_dict(s: MediaSource) -> dict:
    return {
        "id": s.id,
        "name": s.name,
        "type": s.type,
        "config": s.config,
        "enabled": s.enabled,
        "created_at": s.created_at.isoformat() if s.created_at else None,
        "request_delay_seconds": s.request_delay_seconds,  # None | 0.0 | float
    }


class SourceCreate(BaseModel):
    name: str
    type: str
    config: dict | None = None
    enabled: bool = True
    request_delay_seconds: float | None = None  # None=random 2-30s, 0=no delay, N=fixed N s


class SourceUpdate(BaseModel):
    name: str | None = None
    type: str | None = None
    config: dict | None = None
    enabled: bool | None = None
    request_delay_seconds: float | None = None


@router.get("/sources")
def list_sources(db: DbDep):
    sources = db.query(MediaSource).order_by(MediaSource.name).all()
    return [_source_dict(s) for s in sources]


@router.post("/sources", status_code=201)
def create_source(body: SourceCreate, db: DbDep):
    if body.type not in VALID_SOURCE_TYPES:
        raise HTTPException(
            400,
            detail=f"type must be one of: {', '.join(sorted(VALID_SOURCE_TYPES))}",
        )
    from datetime import datetime
    s = MediaSource(
        name=body.name,
        type=body.type,
        config=body.config or {},
        enabled=body.enabled,
        request_delay_seconds=body.request_delay_seconds,
        created_at=datetime.utcnow(),
    )
    db.add(s)
    db.commit()
    db.refresh(s)
    return _source_dict(s)


@router.put("/sources/{source_id}")
def update_source(source_id: int, body: SourceUpdate, db: DbDep):
    s = db.get(MediaSource, source_id)
    if s is None:
        raise HTTPException(404, detail="Source not found.")
    if body.type is not None and body.type not in VALID_SOURCE_TYPES:
        raise HTTPException(
            400,
            detail=f"type must be one of: {', '.join(sorted(VALID_SOURCE_TYPES))}",
        )
    # Use model_dump with exclude_unset so that fields the client didn't send are left alone.
    # request_delay_seconds can legitimately be None (reset to random), so we must not
    # use exclude_none here — we check each field explicitly instead.
    data = body.model_dump(exclude_unset=True)
    for field, val in data.items():
        setattr(s, field, val)
    db.commit()
    db.refresh(s)
    return _source_dict(s)


@router.delete("/sources/{source_id}", status_code=204)
def delete_source(source_id: int, db: DbDep):
    s = db.get(MediaSource, source_id)
    if s is None:
        raise HTTPException(404, detail="Source not found.")
    # Remove any profile links first
    db.query(ProfileSourceLink).filter(ProfileSourceLink.source_id == source_id).delete()
    db.delete(s)
    db.commit()

    # Delete the row before touching the filesystem: if cleanup below fails
    # partway (permissions, a file open in another app, etc.) the source is
    # still correctly gone, which matters more than a best-effort directory
    # cleanup succeeding. Best-effort by design — errors are logged, not
    # raised, so a stray locked file can't turn a delete into a 500.
    for base in (LOCAL_LIBRARIES_DIR, UPLOADED_ADAPTERS_DIR):
        target = base / str(source_id)
        if target.exists() and target.is_dir():
            try:
                shutil.rmtree(target)
            except OSError:
                logger.warning(
                    "Deleted source %s but couldn't remove its upload directory %s — "
                    "it may be locked by another process; you can delete it by hand.",
                    source_id, target, exc_info=True,
                )


@router.post("/sources/{source_id}/test")
async def test_source(source_id: int, db: DbDep):
    """
    Test source connectivity.
    - custom_adapter: GET /health
    - pexels/pixabay/unsplash: lightweight API auth check
    - local_folder: check folder exists and is readable
    - serp_scraper: check SerpAPI key if present
    """
    s = db.get(MediaSource, source_id)
    if s is None:
        raise HTTPException(404, detail="Source not found.")

    cfg = s.config or {}

    if s.type == "local_folder":
        from pathlib import Path
        # Prefer the canonical app-managed upload directory over the cached
        # config.folder_path, which can go stale (see local_library.py's
        # _resolve_library_folder for the full reasoning) — same fix applied
        # there so Test Connection agrees with what the Library page sees.
        canonical = Path(__file__).parent.parent.parent / "local_libraries" / str(source_id)
        folder = canonical if canonical.exists() else Path(cfg.get("folder_path", ""))
        if not folder.exists():
            return {"ok": False, "detail": f"Folder not found: {folder}"}
        if not folder.is_dir():
            return {"ok": False, "detail": f"Path is not a directory: {folder}"}
        count = sum(1 for _ in folder.iterdir() if _.is_file())
        return {"ok": True, "detail": f"Folder accessible. {count} files found."}

    if s.type == "custom_adapter":
        url = cfg.get("adapter_url", "").rstrip("/")
        token = cfg.get("auth_token", "")
        if not url:
            return {"ok": False, "detail": "adapter_url not configured."}
        headers = {"Authorization": f"Bearer {token}"} if token else {}
        try:
            async with httpx.AsyncClient(timeout=10) as client:
                resp = await client.get(f"{url}/health", headers=headers)
            if resp.status_code == 200:
                return {"ok": True, "detail": resp.json()}
            return {"ok": False, "detail": f"HTTP {resp.status_code}: {resp.text[:200]}"}
        except Exception as exc:
            return {"ok": False, "detail": str(exc)}

    if s.type == "pexels":
        key = cfg.get("api_key", "")
        if not key:
            return {"ok": False, "detail": "api_key not configured."}
        try:
            async with httpx.AsyncClient(timeout=10) as client:
                resp = await client.get(
                    "https://api.pexels.com/v1/search",
                    params={"query": "test", "per_page": 1},
                    headers={"Authorization": key},
                )
            return {"ok": resp.status_code == 200, "detail": f"HTTP {resp.status_code}"}
        except Exception as exc:
            return {"ok": False, "detail": str(exc)}

    if s.type == "pixabay":
        key = cfg.get("api_key", "")
        if not key:
            return {"ok": False, "detail": "api_key not configured."}
        try:
            async with httpx.AsyncClient(timeout=10) as client:
                resp = await client.get(
                    "https://pixabay.com/api/",
                    params={"key": key, "q": "test", "per_page": 3},
                )
            return {"ok": resp.status_code == 200, "detail": f"HTTP {resp.status_code}"}
        except Exception as exc:
            return {"ok": False, "detail": str(exc)}

    if s.type == "unsplash":
        key = cfg.get("access_key", "")
        if not key:
            return {"ok": False, "detail": "access_key not configured."}
        try:
            async with httpx.AsyncClient(timeout=10) as client:
                resp = await client.get(
                    "https://api.unsplash.com/search/photos",
                    params={"query": "test", "per_page": 1},
                    headers={"Authorization": f"Client-ID {key}"},
                )
            return {"ok": resp.status_code == 200, "detail": f"HTTP {resp.status_code}"}
        except Exception as exc:
            return {"ok": False, "detail": str(exc)}

    if s.type == "serp_scraper":
        key = cfg.get("serpapi_key", "")
        if not key:
            return {"ok": True, "detail": "No SerpAPI key — will use Playwright scraper fallback."}
        try:
            async with httpx.AsyncClient(timeout=10) as client:
                resp = await client.get(
                    "https://serpapi.com/account",
                    params={"api_key": key},
                )
            return {"ok": resp.status_code == 200, "detail": f"HTTP {resp.status_code}"}
        except Exception as exc:
            return {"ok": False, "detail": str(exc)}

    return {"ok": False, "detail": f"No test implemented for source type '{s.type}'."}
