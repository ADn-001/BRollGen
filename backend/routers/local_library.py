"""
Local Library router — Phase 12.
Browse local folder sources, tag files, serve previews.
"""
import io
import json
import re
import time
import zipfile
from pathlib import Path
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from sqlalchemy.orm import Session

from db.database import get_db
from db.models import MediaSource
from services.naming import parse_filename, build_filename

router = APIRouter(prefix="/library", tags=["library"])

DbDep = Annotated[Session, Depends(get_db)]

IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".webp", ".gif", ".bmp"}
VIDEO_EXTS = {".mp4", ".mov", ".avi", ".mkv", ".webm"}

# Every local_folder source's media has always lived here (see
# backend/routers/uploads.py's upload_local_folder) — config.folder_path is
# only ever a cached copy of "this directory" written back for display/debug
# purposes. Deriving straight from source_id instead of trusting that cached
# value protects against it going stale: e.g. it was captured while running
# inside Docker (where it resolves to /app/local_libraries/<id>, meaningless
# outside a container), or a later source-config Save clobbered it back to
# empty because the Sources page form hadn't refreshed its local state after
# an upload. If the canonical directory doesn't exist yet (a source that
# predates app-managed storage, or simply nothing uploaded yet), fall back to
# whatever's on the source's config so we don't regress that edge case.
PROJECT_ROOT = Path(__file__).parent.parent.parent
LOCAL_LIBRARIES_DIR = PROJECT_ROOT / "local_libraries"


def _resolve_library_folder(source_id: int, s: MediaSource) -> Path:
    canonical = LOCAL_LIBRARIES_DIR / str(source_id)
    if canonical.exists():
        return canonical
    return Path((s.config or {}).get("folder_path", ""))


def _media_type(path: Path) -> str:
    ext = path.suffix.lower()
    if ext in IMAGE_EXTS:
        return "image"
    if ext in VIDEO_EXTS:
        return "video"
    return "unknown"


def _read_sidecar(path: Path) -> dict | None:
    sidecar = path.parent / f"{path.stem}.json"
    if sidecar.exists():
        try:
            return json.loads(sidecar.read_text(encoding="utf-8"))
        except Exception:
            return None
    return None


def _file_info(path: Path) -> dict:
    parsed = parse_filename(path.name)
    sidecar = _read_sidecar(path)
    return {
        "filename": path.name,
        "stem": path.stem,
        "ext": path.suffix.lower(),
        "media_type": _media_type(path),
        "size_bytes": path.stat().st_size,
        "tags": sidecar["tags"] if sidecar else parsed["tags"],
        "quality": sidecar["quality"] if sidecar else parsed["quality"],
        "uid": sidecar["uid"] if sidecar else parsed["uid"],
        "tagged": sidecar is not None or parsed["uid"] is not None,
        "sidecar": sidecar,
    }


def _get_local_source(source_id: int, db: Session) -> MediaSource:
    s = db.get(MediaSource, source_id)
    if s is None or s.type != "local_folder":
        raise HTTPException(404, detail="Local folder source not found.")
    return s


# ── Routes ────────────────────────────────────────────────────────────────────

@router.get("/sources")
def list_local_sources(db: DbDep):
    sources = (
        db.query(MediaSource)
        .filter(MediaSource.type == "local_folder", MediaSource.enabled == True)
        .all()
    )
    return [
        {
            "id": s.id,
            "name": s.name,
            "folder_path": str(_resolve_library_folder(s.id, s)),
            "enabled": s.enabled,
        }
        for s in sources
    ]


@router.get("/{source_id}/files")
def list_files(
    source_id: int,
    db: DbDep,
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=200),
):
    s = _get_local_source(source_id, db)
    cfg = s.config or {}
    folder = _resolve_library_folder(source_id, s)
    # `.get(..., default)` only falls back when the key is *missing* — an
    # explicitly-empty list (e.g. the Sources page's Enabled Extensions field
    # got saved blank) would otherwise be taken as "match nothing" instead of
    # "no restriction, match everything". Use `or` so any falsy value falls
    # back to the full default set, matching how the actual search-time
    # adapter (services/source_adapters/local_folder.py) already treats it.
    enabled_exts = set(cfg.get("enabled_extensions") or list(IMAGE_EXTS | VIDEO_EXTS))
    if not folder.exists():
        raise HTTPException(400, detail=f"Folder not found: {folder}")

    all_files = sorted(
        [f for f in folder.iterdir() if f.is_file() and f.suffix.lower() in enabled_exts],
        key=lambda f: (
            # untagged first (parse_filename uid is None), then by uid
            parse_filename(f.name)["uid"] is not None,
            parse_filename(f.name)["uid"] or "",
        ),
    )
    total = len(all_files)
    start = (page - 1) * page_size
    page_files = all_files[start : start + page_size]

    return {
        "total": total,
        "page": page,
        "page_size": page_size,
        "files": [_file_info(f) for f in page_files],
    }


@router.get("/{source_id}/files/{filename:path}")
def get_file_metadata(source_id: int, filename: str, db: DbDep):
    s = _get_local_source(source_id, db)
    folder = _resolve_library_folder(source_id, s)
    path = folder / filename
    if not path.exists():
        raise HTTPException(404, detail="File not found.")
    return _file_info(path)


class TagSaveBody(BaseModel):
    tags: list[str]
    quality: str | None = None   # "U" | "H" | "M" | "L" | None
    original_filename: str | None = None


@router.post("/{source_id}/files/{filename:path}/tag")
def save_file_tags(source_id: int, filename: str, body: TagSaveBody, db: DbDep):
    """
    Rename a file using the naming convention and write its sidecar JSON.
    Never overwrites another file — generates a new UID if the file doesn't have one.
    """
    s = _get_local_source(source_id, db)
    folder = _resolve_library_folder(source_id, s)
    path = folder / filename
    if not path.exists():
        raise HTTPException(404, detail="File not found.")

    # Determine UID — keep existing or generate next
    existing = _read_sidecar(path)
    parsed = parse_filename(path.name)
    uid_int = None
    if existing and existing.get("uid"):
        uid_int = int(existing["uid"])
    elif parsed["uid"]:
        uid_int = int(parsed["uid"])
    else:
        # Auto-increment from max existing UID in folder
        max_uid = 0
        for f in folder.iterdir():
            p = parse_filename(f.name)
            if p["uid"]:
                try:
                    max_uid = max(max_uid, int(p["uid"]))
                except ValueError:
                    pass
        uid_int = max_uid + 1

    uid_str = f"{uid_int:06d}"
    new_name = build_filename(
        tags=body.tags,
        quality=body.quality,
        uid=uid_str,
        ext=path.suffix,
    )
    new_path = folder / new_name

    # Rename with retry (Windows may hold file open)
    for attempt in range(3):
        try:
            path.rename(new_path)
            break
        except PermissionError:
            if attempt == 2:
                raise HTTPException(500, detail="File rename failed — file may be open in another app.")
            time.sleep(0.5)

    # Write sidecar
    import datetime
    sidecar = {
        "uid": uid_str,
        "original_filename": body.original_filename or filename,
        "tags": [t.strip().lower() for t in body.tags if t.strip()],
        "quality": body.quality,
        "media_type": _media_type(new_path),
        "tagged_at": datetime.datetime.utcnow().isoformat() + "Z",
    }
    sidecar_path = folder / f"{new_path.stem}.json"
    sidecar_path.write_text(json.dumps(sidecar, indent=2), encoding="utf-8")

    return {"new_filename": new_name, "uid": uid_str, "sidecar": sidecar}


def _safe_file_path(folder: Path, filename: str) -> Path:
    """Resolve filename against folder and reject any path-traversal attempt."""
    target = (folder / filename).resolve()
    folder_resolved = folder.resolve()
    try:
        target.relative_to(folder_resolved)
    except ValueError:
        raise HTTPException(403, detail="Access denied.")
    return target


@router.delete("/{source_id}/files/{filename:path}", status_code=204)
def delete_file(source_id: int, filename: str, db: DbDep):
    """Delete a media file (and its sidecar JSON, if any) from a local_folder source's library."""
    s = _get_local_source(source_id, db)
    folder = _resolve_library_folder(source_id, s)
    path = _safe_file_path(folder, filename)
    if not path.exists() or not path.is_file():
        raise HTTPException(404, detail="File not found.")
    path.unlink()
    sidecar_path = folder / f"{path.stem}.json"
    if sidecar_path.exists():
        sidecar_path.unlink()


@router.get("/{source_id}/download")
def download_library_folder(source_id: int, db: DbDep):
    """
    Zip up every media file currently in this library (using their current,
    already-tagged-via-rename filenames — see save_file_tags above, which is
    where tags actually get baked into each file's name) and stream it back
    as a single download. Sidecar .json files are internal bookkeeping, not
    part of the deliverable, so they're left out of the archive.
    """
    s = _get_local_source(source_id, db)
    folder = _resolve_library_folder(source_id, s)
    if not folder.exists():
        raise HTTPException(404, detail="Folder not found.")

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for f in sorted(folder.iterdir()):
            if f.is_file() and f.suffix.lower() != ".json":
                zf.write(f, arcname=f.name)
    buf.seek(0)

    safe_name = re.sub(r"[^A-Za-z0-9._-]", "_", s.name).strip("_") or f"library_{source_id}"
    headers = {"Content-Disposition": f'attachment; filename="{safe_name}.zip"'}
    return StreamingResponse(buf, media_type="application/zip", headers=headers)


@router.get("/preview/{source_id}/{filename:path}")
def preview_library_file(source_id: int, filename: str, db: DbDep):
    """Serve a file from a local folder source for in-browser preview."""
    from fastapi.responses import FileResponse
    s = _get_local_source(source_id, db)
    folder = _resolve_library_folder(source_id, s)
    path = folder / filename
    if not path.exists():
        raise HTTPException(404, detail="File not found.")
    return FileResponse(str(path))
