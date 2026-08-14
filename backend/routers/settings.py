"""
Settings router — Phase 2.
Handles: AppSettings CRUD, LLM provider CRUD, global tag CRUD.
"""
import csv
from pathlib import Path
from typing import Annotated

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from pydantic import BaseModel
from sqlalchemy.orm import Session

from db.database import get_db
from db.models import AppSettings, GlobalTag, LLMProvider

router = APIRouter(tags=["settings"])

DbDep = Annotated[Session, Depends(get_db)]


# ── Helpers ──────────────────────────────────────────────────────────────────

def _get_settings(db: Session) -> AppSettings:
    s = db.get(AppSettings, 1)
    if s is None:
        s = AppSettings(id=1)
        db.add(s)
        db.commit()
        db.refresh(s)
    return s


def _settings_dict(s: AppSettings) -> dict:
    return {
        "ffmpeg_path": s.ffmpeg_path,
        "tmp_path": s.tmp_path,
        "analysis_method": s.analysis_method,
    }


def _provider_dict(p: LLMProvider) -> dict:
    return {
        "id": p.id,
        "name": p.name,
        "provider_type": p.provider_type,
        "api_key": p.api_key,
        "base_url": p.base_url,
        "model": p.model,
        "priority": p.priority,
        "enabled": p.enabled,
    }


def _tag_dict(t: GlobalTag) -> dict:
    return {"id": t.id, "word": t.word}


# ── AppSettings ───────────────────────────────────────────────────────────────

class SettingsUpdate(BaseModel):
    ffmpeg_path: str | None = None
    tmp_path: str | None = None
    analysis_method: str | None = None


@router.get("/settings")
def get_app_settings(db: DbDep):
    return _settings_dict(_get_settings(db))


@router.put("/settings")
def update_app_settings(body: SettingsUpdate, db: DbDep):
    s = _get_settings(db)
    if body.ffmpeg_path is not None:
        s.ffmpeg_path = body.ffmpeg_path or None
    if body.tmp_path is not None:
        s.tmp_path = body.tmp_path or None
    if body.analysis_method is not None:
        if body.analysis_method not in ("llm", "algorithmic"):
            raise HTTPException(400, detail="analysis_method must be 'llm' or 'algorithmic'")
        s.analysis_method = body.analysis_method
    db.commit()
    db.refresh(s)
    return _settings_dict(s)


# ── LLM Providers ─────────────────────────────────────────────────────────────

VALID_PROVIDER_TYPES = {"openai", "anthropic", "gemini", "ollama", "custom"}


class LLMProviderCreate(BaseModel):
    name: str
    provider_type: str
    api_key: str | None = None
    base_url: str | None = None
    model: str | None = None
    priority: int = 0
    enabled: bool = True


class LLMProviderUpdate(BaseModel):
    name: str | None = None
    provider_type: str | None = None
    api_key: str | None = None
    base_url: str | None = None
    model: str | None = None
    priority: int | None = None
    enabled: bool | None = None


@router.get("/llm-providers")
def list_llm_providers(db: DbDep):
    providers = db.query(LLMProvider).order_by(LLMProvider.priority).all()
    return [_provider_dict(p) for p in providers]


@router.post("/llm-providers", status_code=201)
def create_llm_provider(body: LLMProviderCreate, db: DbDep):
    if body.provider_type not in VALID_PROVIDER_TYPES:
        raise HTTPException(
            400,
            detail=f"provider_type must be one of: {', '.join(sorted(VALID_PROVIDER_TYPES))}",
        )
    p = LLMProvider(**body.model_dump())
    db.add(p)
    db.commit()
    db.refresh(p)
    return _provider_dict(p)


@router.put("/llm-providers/{provider_id}")
def update_llm_provider(provider_id: int, body: LLMProviderUpdate, db: DbDep):
    p = db.get(LLMProvider, provider_id)
    if p is None:
        raise HTTPException(404, detail="LLM provider not found.")
    if body.provider_type is not None and body.provider_type not in VALID_PROVIDER_TYPES:
        raise HTTPException(
            400,
            detail=f"provider_type must be one of: {', '.join(sorted(VALID_PROVIDER_TYPES))}",
        )
    for field, val in body.model_dump(exclude_none=True).items():
        setattr(p, field, val)
    db.commit()
    db.refresh(p)
    return _provider_dict(p)


@router.delete("/llm-providers/{provider_id}", status_code=204)
def delete_llm_provider(provider_id: int, db: DbDep):
    p = db.get(LLMProvider, provider_id)
    if p is None:
        raise HTTPException(404, detail="LLM provider not found.")
    db.delete(p)
    db.commit()


# ── Global Tags ───────────────────────────────────────────────────────────────

class GlobalTagCreate(BaseModel):
    word: str


@router.get("/global-tags")
def list_global_tags(db: DbDep):
    tags = db.query(GlobalTag).order_by(GlobalTag.word).all()
    return [_tag_dict(t) for t in tags]


@router.post("/global-tags", status_code=201)
def add_global_tag(body: GlobalTagCreate, db: DbDep):
    word = body.word.strip().lower()
    if not word:
        raise HTTPException(400, detail="word cannot be empty.")
    existing = db.query(GlobalTag).filter(GlobalTag.word == word).first()
    if existing:
        return _tag_dict(existing)  # idempotent
    t = GlobalTag(word=word)
    db.add(t)
    db.commit()
    db.refresh(t)
    return _tag_dict(t)


@router.delete("/global-tags/{tag_id}", status_code=204)
def delete_global_tag(tag_id: int, db: DbDep):
    t = db.get(GlobalTag, tag_id)
    if t is None:
        raise HTTPException(404, detail="Global tag not found.")
    db.delete(t)
    db.commit()


def _parse_tag_upload(content: bytes) -> list[str]:
    """
    Parse .txt or .csv bytes → list of lowercased words.
    CSV: first column only. TXT: one word per line.
    Handles UTF-8 BOM, strips whitespace, skips blanks.
    """
    text = content.decode("utf-8-sig", errors="replace")
    lines = text.splitlines()
    words: list[str] = []
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


@router.post("/global-tags/import-csv", status_code=200)
async def import_global_tags_csv(file: UploadFile = File(...), db: Session = Depends(get_db)):
    """
    Import words from .txt (one per line) or .csv (first column).
    Returns {added, skipped, words}.
    """
    content = await file.read()
    candidates = _parse_tag_upload(content)

    if not candidates:
        return {"added": 0, "skipped": 0, "words": []}

    existing_words = {row.word for row in db.query(GlobalTag.word).all()}

    added_words: list[str] = []
    skipped = 0

    for word in candidates:
        if word in existing_words:
            skipped += 1
        else:
            db.add(GlobalTag(word=word))
            existing_words.add(word)
            added_words.append(word)

    db.commit()
    return {"added": len(added_words), "skipped": skipped, "words": added_words}
