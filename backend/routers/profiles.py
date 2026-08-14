"""
Profiles router — Phase 4.
CRUD for NicheProfile, ProfileTag, and ProfileSourceLink.
"""
from datetime import datetime
from typing import Annotated

import asyncio
import csv
import io
import subprocess
import sys

from fastapi import APIRouter, Depends, HTTPException, Request, UploadFile, File
from pydantic import BaseModel
from sqlalchemy.orm import Session

from db.database import get_db
from db.models import (
    LLMProvider, MediaSource, NicheProfile,
    ProfileSourceLink, ProfileTag,
)

router = APIRouter(tags=["profiles"])

DbDep = Annotated[Session, Depends(get_db)]


# ── Serialisers ───────────────────────────────────────────────────────────────

def _profile_dict(p: NicheProfile) -> dict:
    return {
        "id": p.id,
        "name": p.name,
        "description": p.description,
        "multi_item_per_tag": p.multi_item_per_tag,
        "dedupe_repeat_tags": p.dedupe_repeat_tags,
        "redundant_source_download": p.redundant_source_download,
        "default_item_count": p.default_item_count,
        "llm_enabled": p.llm_enabled,
        "llm_provider_id": p.llm_provider_id,
        "created_at": p.created_at.isoformat() if p.created_at else None,
        "tag_count": len(p.tags),
        "source_count": len(p.source_links),
    }


def _tag_dict(t: ProfileTag) -> dict:
    return {"id": t.id, "profile_id": t.profile_id, "word": t.word}


def _link_dict(lnk: ProfileSourceLink) -> dict:
    return {
        "id": lnk.id,
        "profile_id": lnk.profile_id,
        "source_id": lnk.source_id,
        "priority": lnk.priority,
        "source_name": lnk.source.name if lnk.source else None,
        "source_type": lnk.source.type if lnk.source else None,
    }


# ── Profile CRUD ──────────────────────────────────────────────────────────────

class ProfileCreate(BaseModel):
    name: str
    description: str | None = None
    multi_item_per_tag: bool = True
    dedupe_repeat_tags: bool = True
    redundant_source_download: bool = False
    default_item_count: int = 10
    llm_enabled: bool = True
    llm_provider_id: int | None = None


class ProfileUpdate(BaseModel):
    name: str | None = None
    description: str | None = None
    multi_item_per_tag: bool | None = None
    dedupe_repeat_tags: bool | None = None
    redundant_source_download: bool | None = None
    default_item_count: int | None = None
    llm_enabled: bool | None = None
    llm_provider_id: int | None = None


def _validate_profile_fields(data: dict, db: Session):
    if "llm_provider_id" in data and data["llm_provider_id"] is not None:
        if db.get(LLMProvider, data["llm_provider_id"]) is None:
            raise HTTPException(400, detail="llm_provider_id references a non-existent provider.")


@router.get("/profiles")
def list_profiles(db: DbDep):
    profiles = db.query(NicheProfile).order_by(NicheProfile.name).all()
    return [_profile_dict(p) for p in profiles]


@router.post("/profiles", status_code=201)
def create_profile(body: ProfileCreate, db: DbDep):
    data = body.model_dump()
    _validate_profile_fields(data, db)
    p = NicheProfile(**data, created_at=datetime.utcnow())
    db.add(p)
    db.commit()
    db.refresh(p)
    return _profile_dict(p)


@router.get("/profiles/{profile_id}")
def get_profile(profile_id: int, db: DbDep):
    p = db.get(NicheProfile, profile_id)
    if p is None:
        raise HTTPException(404, detail="Profile not found.")
    return _profile_dict(p)


@router.put("/profiles/{profile_id}")
def update_profile(profile_id: int, body: ProfileUpdate, db: DbDep):
    p = db.get(NicheProfile, profile_id)
    if p is None:
        raise HTTPException(404, detail="Profile not found.")
    data = body.model_dump(exclude_none=True)
    _validate_profile_fields(data, db)
    for field, val in data.items():
        setattr(p, field, val)
    db.commit()
    db.refresh(p)
    return _profile_dict(p)


@router.delete("/profiles/{profile_id}", status_code=204)
def delete_profile(profile_id: int, db: DbDep):
    p = db.get(NicheProfile, profile_id)
    if p is None:
        raise HTTPException(404, detail="Profile not found.")
    db.delete(p)
    db.commit()


# ── Profile Tags ──────────────────────────────────────────────────────────────

class TagCreate(BaseModel):
    word: str


@router.get("/profiles/{profile_id}/tags")
def list_profile_tags(profile_id: int, db: DbDep):
    if db.get(NicheProfile, profile_id) is None:
        raise HTTPException(404, detail="Profile not found.")
    tags = (
        db.query(ProfileTag)
        .filter(ProfileTag.profile_id == profile_id)
        .order_by(ProfileTag.word)
        .all()
    )
    return [_tag_dict(t) for t in tags]


@router.post("/profiles/{profile_id}/tags", status_code=201)
def add_profile_tag(profile_id: int, body: TagCreate, db: DbDep):
    if db.get(NicheProfile, profile_id) is None:
        raise HTTPException(404, detail="Profile not found.")
    word = body.word.strip().lower()
    if not word:
        raise HTTPException(400, detail="word cannot be empty.")
    existing = (
        db.query(ProfileTag)
        .filter(ProfileTag.profile_id == profile_id, ProfileTag.word == word)
        .first()
    )
    if existing:
        return _tag_dict(existing)  # idempotent
    t = ProfileTag(profile_id=profile_id, word=word)
    db.add(t)
    db.commit()
    db.refresh(t)
    return _tag_dict(t)


@router.delete("/profiles/{profile_id}/tags/{tag_id}", status_code=204)
def delete_profile_tag(profile_id: int, tag_id: int, db: DbDep):
    t = db.query(ProfileTag).filter(
        ProfileTag.id == tag_id, ProfileTag.profile_id == profile_id
    ).first()
    if t is None:
        raise HTTPException(404, detail="Tag not found.")
    db.delete(t)
    db.commit()


def _parse_tag_upload(content: bytes) -> list[str]:
    """
    Parse uploaded .txt or .csv bytes into a list of lowercased words.
    - .txt: one word/phrase per line
    - .csv: only the first column is used; header row skipped if non-numeric
    Both formats: strip whitespace, skip blank lines.
    """
    text = content.decode("utf-8-sig", errors="replace")  # handle BOM
    lines = text.splitlines()
    words: list[str] = []
    # Try CSV: if any line contains a comma, treat as CSV
    if any("," in line for line in lines):
        reader = csv.reader(lines)
        for row in reader:
            if not row:
                continue
            cell = row[0].strip().lower()
            if cell:
                words.append(cell)
    else:
        for line in lines:
            w = line.strip().lower()
            if w:
                words.append(w)
    return words


@router.post("/profiles/{profile_id}/tags/import-csv", status_code=200)
async def import_profile_tags_csv(
    profile_id: int, file: UploadFile = File(...), db: Session = Depends(get_db)
):
    """
    Import words from a .txt (one per line) or .csv (first column) file.
    Returns {added, skipped, words}.
    """
    if db.get(NicheProfile, profile_id) is None:
        raise HTTPException(404, detail="Profile not found.")

    content = await file.read()
    candidates = _parse_tag_upload(content)

    if not candidates:
        return {"added": 0, "skipped": 0, "words": []}

    # Fetch existing words for this profile in one query
    existing_words = {
        row.word
        for row in db.query(ProfileTag.word)
        .filter(ProfileTag.profile_id == profile_id)
        .all()
    }

    added_words: list[str] = []
    skipped = 0

    for word in candidates:
        if word in existing_words:
            skipped += 1
        else:
            db.add(ProfileTag(profile_id=profile_id, word=word))
            existing_words.add(word)
            added_words.append(word)

    db.commit()
    return {"added": len(added_words), "skipped": skipped, "words": added_words}


# ── Profile Source Links ──────────────────────────────────────────────────────

class SourceLinkUpsert(BaseModel):
    """Replace the entire source list for a profile in one call."""
    source_ids: list[int]  # ordered by desired priority (index = priority)


@router.get("/profiles/{profile_id}/sources")
def list_profile_sources(profile_id: int, db: DbDep):
    if db.get(NicheProfile, profile_id) is None:
        raise HTTPException(404, detail="Profile not found.")
    links = (
        db.query(ProfileSourceLink)
        .filter(ProfileSourceLink.profile_id == profile_id)
        .order_by(ProfileSourceLink.priority)
        .all()
    )
    return [_link_dict(lnk) for lnk in links]


@router.put("/profiles/{profile_id}/sources")
def set_profile_sources(profile_id: int, body: SourceLinkUpsert, db: DbDep):
    """Replace the profile's source list. Send source_ids ordered by priority."""
    if db.get(NicheProfile, profile_id) is None:
        raise HTTPException(404, detail="Profile not found.")
    # Validate all source IDs exist
    for sid in body.source_ids:
        if db.get(MediaSource, sid) is None:
            raise HTTPException(400, detail=f"Source {sid} not found.")
    # Delete existing links
    db.query(ProfileSourceLink).filter(ProfileSourceLink.profile_id == profile_id).delete()
    # Re-create with new priority order
    for priority, sid in enumerate(body.source_ids):
        db.add(ProfileSourceLink(profile_id=profile_id, source_id=sid, priority=priority))
    db.commit()
    return list_profile_sources(profile_id, db)


# ── Adapter lifecycle ────────────────────────────────────────────────────────

@router.post("/profiles/{profile_id}/adapters/start")
async def start_profile_adapters(profile_id: int, request: Request, db: DbDep):
    """
    For each custom_adapter source linked to this profile:
    1. Health-check the adapter_url.
    2. If healthy → already running, skip.
    3. If unhealthy + adapter_script_path configured → launch subprocess.
    4. Wait up to 10s for health check to pass.
    5. Return status for each adapter (non-blocking — failures are warnings only,
       per OQ4: session setup is never blocked on adapter start).
    """
    import httpx

    if db.get(NicheProfile, profile_id) is None:
        raise HTTPException(404, detail="Profile not found.")

    links = (
        db.query(ProfileSourceLink)
        .filter(ProfileSourceLink.profile_id == profile_id)
        .all()
    )
    custom_sources = [
        lnk.source for lnk in links
        if lnk.source and lnk.source.type == "custom_adapter" and lnk.source.enabled
    ]

    if not hasattr(request.app.state, "adapter_processes"):
        request.app.state.adapter_processes = {}

    results = []

    async def _health_check(adapter_url: str) -> bool:
        try:
            async with httpx.AsyncClient(timeout=3.0) as client:
                r = await client.get(f"{adapter_url.rstrip('/')}/health")
                return r.status_code == 200
        except Exception:
            return False

    for source in custom_sources:
        cfg = source.config or {}
        adapter_url = (cfg.get("adapter_url") or "").rstrip("/")
        script_path = cfg.get("adapter_script_path") or ""

        if not adapter_url:
            results.append({
                "source": source.name,
                "status": "skipped",
                "reason": "no adapter_url configured",
            })
            continue

        # Check if already running
        if await _health_check(adapter_url):
            results.append({"source": source.name, "status": "already_running"})
            continue

        if not script_path:
            results.append({
                "source": source.name,
                "status": "not_running",
                "reason": "adapter_script_path not configured — start it manually",
            })
            continue

        # Launch the adapter subprocess
        try:
            proc = subprocess.Popen(
                [sys.executable, script_path],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                # Windows: don't create a new console window
                creationflags=subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0,
            )
            request.app.state.adapter_processes[adapter_url] = proc
        except Exception as exc:
            results.append({
                "source": source.name,
                "status": "launch_failed",
                "reason": str(exc),
            })
            continue

        # Wait up to 10s for health check to pass (non-blocking — 20 × 0.5s)
        started = False
        for _ in range(20):
            await asyncio.sleep(0.5)
            if await _health_check(adapter_url):
                started = True
                break

        results.append({
            "source": source.name,
            "status": "started" if started else "start_timeout",
        })

    return {"adapters": results}
