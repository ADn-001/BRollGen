"""
SQLAlchemy ORM models — all persistent config lives here.
Session data (Session, Tag, DownloadResult) is in-memory only; see backend/session_state.py.
"""
from datetime import datetime

from sqlalchemy import (
    Boolean, Column, DateTime, Float, ForeignKey, Integer, JSON,
    String, Text, UniqueConstraint,
)
from sqlalchemy.orm import relationship

from db.database import Base


class AppSettings(Base):
    """Single-row application settings (id always = 1)."""
    __tablename__ = "app_settings"

    id = Column(Integer, primary_key=True, default=1)
    ffmpeg_path = Column(Text, nullable=True)       # None → auto-detect bin/ffmpeg.exe then PATH
    tmp_path = Column(Text, nullable=True)           # None → ./tmp relative to project root
    realesrgan_path = Column(Text, nullable=True)    # None → lanczos fallback for all profiles
    # "algorithmic" = spaCy primary, LLM never called
    # "llm"         = LLM primary, spaCy is final fallback
    analysis_method = Column(String(20), nullable=False, default="algorithmic")


class LLMProvider(Base):
    __tablename__ = "llm_providers"

    id = Column(Integer, primary_key=True)
    name = Column(String(100), nullable=False)
    # "openai" | "anthropic" | "gemini" | "ollama" | "custom"
    provider_type = Column(String(50), nullable=False)
    # SECURITY: api_key stored as plain text in v1 — encrypt in v2
    api_key = Column(Text, nullable=True)
    base_url = Column(Text, nullable=True)   # required for ollama/custom
    model = Column(String(100), nullable=True)
    priority = Column(Integer, nullable=False, default=0)  # lower = tried first
    enabled = Column(Boolean, nullable=False, default=True)


class MediaSource(Base):
    __tablename__ = "media_sources"

    id = Column(Integer, primary_key=True)
    name = Column(String(100), nullable=False)
    # "pexels" | "pixabay" | "unsplash" | "serp_scraper" | "custom_adapter" | "local_folder"
    type = Column(String(50), nullable=False)
    config = Column(JSON, nullable=True)     # api_key, folder_path, adapter_url, etc.
    enabled = Column(Boolean, nullable=False, default=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    # Rate-limit delay between consecutive download requests to this source.
    # NULL  → random 2–30 s each time
    # 0.0   → no delay
    # N > 0 → fixed N seconds
    request_delay_seconds = Column(Float, nullable=True, default=None)


class NicheProfile(Base):
    __tablename__ = "niche_profiles"

    id = Column(Integer, primary_key=True)
    name = Column(String(100), unique=True, nullable=False)
    description = Column(Text, nullable=True)
    # When ON: best-quality-one per source per tag
    multi_item_per_tag = Column(Boolean, nullable=False, default=True)
    # When ON: repeated tag word treated as single tag
    dedupe_repeat_tags = Column(Boolean, nullable=False, default=True)
    # When ON: download best-1 result from EACH enabled source per tag (instead
    # of the single globally-best one); review step groups them by tag so the
    # user can pick which source's result(s) to keep.
    redundant_source_download = Column(Boolean, nullable=False, default=False)
    default_item_count = Column(Integer, nullable=False, default=10)
    llm_enabled = Column(Boolean, nullable=False, default=True)
    llm_provider_id = Column(Integer, ForeignKey("llm_providers.id"), nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)

    llm_provider = relationship("LLMProvider")
    tags = relationship("ProfileTag", back_populates="profile", cascade="all, delete-orphan")
    source_links = relationship("ProfileSourceLink", back_populates="profile", cascade="all, delete-orphan")


class ProfileSourceLink(Base):
    __tablename__ = "profile_source_links"

    id = Column(Integer, primary_key=True)
    profile_id = Column(Integer, ForeignKey("niche_profiles.id"), nullable=False)
    source_id = Column(Integer, ForeignKey("media_sources.id"), nullable=False)
    priority = Column(Integer, nullable=False, default=0)  # lower = searched first

    profile = relationship("NicheProfile", back_populates="source_links")
    source = relationship("MediaSource")


class ProfileTag(Base):
    __tablename__ = "profile_tags"

    id = Column(Integer, primary_key=True)
    profile_id = Column(Integer, ForeignKey("niche_profiles.id"), nullable=False)
    word = Column(String(200), nullable=False)

    __table_args__ = (UniqueConstraint("profile_id", "word", name="uq_profile_tag"),)

    profile = relationship("NicheProfile", back_populates="tags")


class GlobalTag(Base):
    __tablename__ = "global_tags"

    id = Column(Integer, primary_key=True)
    word = Column(String(200), unique=True, nullable=False)
