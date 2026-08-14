"""
Uploads router.

Lets the browser hand the app real file bytes for the two source-config
fields that used to be raw host-filesystem paths typed into a text box:

- local_folder sources' `config.folder_path`
- custom_adapter sources' `config.adapter_script_path`

Both were unusable from a Docker deployment (the path had to exist inside
whatever filesystem the backend process runs on) and, even locally, forced
the user to already have their media/script sitting on the same machine at
a path they had to type by hand. These endpoints instead accept uploaded
bytes over HTTP and store them under an app-managed directory at the
project root, then write the resulting on-disk path back into the source's
config automatically.
"""
import logging
import re
from pathlib import Path
from typing import Annotated

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from sqlalchemy.orm import Session

from db.database import get_db
from db.models import MediaSource

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/sources", tags=["uploads"])

DbDep = Annotated[Session, Depends(get_db)]

PROJECT_ROOT = Path(__file__).parent.parent.parent
LOCAL_LIBRARIES_DIR = PROJECT_ROOT / "local_libraries"
UPLOADED_ADAPTERS_DIR = PROJECT_ROOT / "CustomAdapters" / "uploaded"

# Matches the naming convention's quality-grade/uid suffix so we don't
# accidentally corrupt a filename that already follows it (see
# services/source_adapters/local_folder.py's _parse_convention).
_UNSAFE_CHARS = re.compile(r"[^A-Za-z0-9._\- ]")


def _get_source(source_id: int, db: Session) -> MediaSource:
    s = db.get(MediaSource, source_id)
    if s is None:
        raise HTTPException(404, detail="Source not found.")
    return s


def _safe_basename(name: str) -> str:
    """
    Reduce an arbitrary (possibly attacker- or OS-supplied) filename to a
    safe basename: strip any directory components, replace characters
    outside a conservative allowlist, and guard against empty results.
    """
    base = Path(name).name.strip()
    base = _UNSAFE_CHARS.sub("_", base)
    base = base.lstrip(".")  # no hidden files, no leading-dot traversal tricks
    return base or "file"


def _dedupe_path(dest_dir: Path, filename: str) -> Path:
    """If filename already exists in dest_dir, append _2, _3, ... before the extension."""
    candidate = dest_dir / filename
    if not candidate.exists():
        return candidate
    stem, suffix = Path(filename).stem, Path(filename).suffix
    n = 2
    while True:
        candidate = dest_dir / f"{stem}_{n}{suffix}"
        if not candidate.exists():
            return candidate
        n += 1


# ── Local folder upload ───────────────────────────────────────────────────────

@router.post("/{source_id}/upload/folder")
async def upload_local_folder(
    source_id: int,
    db: DbDep,
    files: list[UploadFile] = File(...),
):
    """
    Upload one or more files to become this local_folder source's media
    library. Accepts either a flat multi-file selection or a whole folder
    picked via a webkitdirectory input / dropped from the OS file manager —
    the frontend sends each file's original relative path as its
    `filename`, but files are flattened to a single directory on save
    (matching how services/source_adapters/local_folder.py actually reads
    this folder: a flat, non-recursive directory listing). Re-uploading
    adds to the existing library; same-name files are disambiguated with a
    numeric suffix rather than overwritten, so nothing already tagged is
    silently replaced.
    """
    source = _get_source(source_id, db)
    if source.type != "local_folder":
        raise HTTPException(400, detail="Source is not a local_folder source.")
    if not files:
        raise HTTPException(400, detail="No files uploaded.")

    dest_dir = LOCAL_LIBRARIES_DIR / str(source_id)
    dest_dir.mkdir(parents=True, exist_ok=True)

    saved = 0
    skipped: list[str] = []
    for f in files:
        basename = _safe_basename(f.filename or "")
        if not basename or basename == "_":
            skipped.append(f.filename or "<unnamed>")
            continue
        dest_path = _dedupe_path(dest_dir, basename)
        content = await f.read()
        if not content:
            skipped.append(f.filename or basename)
            continue
        dest_path.write_bytes(content)
        saved += 1

    cfg = dict(source.config or {})
    cfg["folder_path"] = str(dest_dir)
    source.config = cfg
    db.commit()

    total_files = sum(1 for p in dest_dir.iterdir() if p.is_file())
    return {
        "folder_path": str(dest_dir),
        "uploaded": saved,
        "skipped": skipped,
        "total_files_in_library": total_files,
    }


@router.get("/{source_id}/upload/folder/status")
def local_folder_status(source_id: int, db: DbDep):
    """Report what's currently in this source's uploaded library, if anything."""
    source = _get_source(source_id, db)
    folder_path = (source.config or {}).get("folder_path")
    if not folder_path:
        return {"folder_path": None, "file_count": 0}
    p = Path(folder_path)
    if not p.exists() or not p.is_dir():
        return {"folder_path": folder_path, "file_count": 0}
    count = sum(1 for f in p.iterdir() if f.is_file())
    return {"folder_path": folder_path, "file_count": count}


@router.delete("/{source_id}/upload/folder", status_code=204)
def clear_local_folder(source_id: int, db: DbDep):
    """Remove every uploaded file for this source's library (keeps the source itself)."""
    source = _get_source(source_id, db)
    folder_path = (source.config or {}).get("folder_path")
    if folder_path:
        p = Path(folder_path)
        if p.exists() and p.is_dir() and p.resolve().is_relative_to(LOCAL_LIBRARIES_DIR.resolve()):
            import shutil
            for child in p.iterdir():
                if child.is_file():
                    child.unlink()
                elif child.is_dir():
                    shutil.rmtree(child, ignore_errors=True)


# ── Custom adapter script upload ─────────────────────────────────────────────

@router.post("/{source_id}/upload/adapter-script")
async def upload_adapter_script(
    source_id: int,
    db: DbDep,
    file: UploadFile = File(...),
):
    """
    Upload a .py adapter entry-point script for a custom_adapter source.
    Saved under CustomAdapters/uploaded/<source_id>/, and
    config.adapter_script_path is set to that file so the existing
    auto-launch flow (POST /profiles/{id}/adapters/start) picks it up with
    no other change. A manually-typed adapter_script_path is still
    supported and is left alone unless this endpoint is called.
    """
    source = _get_source(source_id, db)
    if source.type != "custom_adapter":
        raise HTTPException(400, detail="Source is not a custom_adapter source.")

    basename = _safe_basename(file.filename or "")
    if not basename.endswith(".py"):
        raise HTTPException(400, detail="Adapter script must be a .py file.")

    dest_dir = UPLOADED_ADAPTERS_DIR / str(source_id)
    dest_dir.mkdir(parents=True, exist_ok=True)
    dest_path = dest_dir / basename

    content = await file.read()
    if not content:
        raise HTTPException(400, detail="Uploaded file is empty.")
    dest_path.write_bytes(content)

    cfg = dict(source.config or {})
    cfg["adapter_script_path"] = str(dest_path)
    source.config = cfg
    db.commit()

    return {"adapter_script_path": str(dest_path)}
