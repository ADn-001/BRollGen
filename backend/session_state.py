"""
In-memory session models. These are NEVER persisted to SQLite.
Session lifecycle: created on POST /api/sessions, deleted on DELETE /api/sessions/{id}.
"""
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal


@dataclass
class Tag:
    word: str
    source: Literal["profile_wordlist", "global_wordlist", "nlp", "llm", "manual"]
    occurrence_index: int    # 0-based, order of first appearance in script
    is_duplicate: bool = False  # True if same word already appears earlier in tag list


@dataclass
class DownloadResult:
    tag: Tag
    tag_occurrence_index: int
    source_id: int
    source_name: str
    file_path: Path
    media_type: Literal["image", "video"]
    width: int | None
    height: int | None
    file_size_bytes: int
    quality_score: float          # resolution-based or file_size_bytes proxy
    kept: bool = True             # user can toggle in curation step
    reused_from_uid: str | None = None  # set when file reused for a duplicate tag slot


@dataclass
class Session:
    session_id: str              # UUID4
    profile_id: int
    script_text: str
    item_count: int              # N — number of tags/items to produce
    extracted_tags: list[Tag] = field(default_factory=list)
    download_results: list[DownloadResult] = field(default_factory=list)
    approved_items: list[DownloadResult] = field(default_factory=list)
    tmp_dir: Path = field(default=None)
    status: Literal[
        "analyzing", "downloading", "awaiting_review", "done", "error"
    ] = "analyzing"
    error_message: str | None = None
    missing_tags: list[str] = field(default_factory=list)
    # Set by analysis pipeline; True when fewer than N tags could be extracted
    needs_more_tags: bool = False
    dedupe_repeat_tags: bool = True  # effective per-session value (overrides profile default)
    current_item_label: str = ""     # e.g. 'Searching: "emperor" (1 of 8)'
    current_item_index: int = 0      # 0-based index of the item being processed
