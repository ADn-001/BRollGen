"""
Local folder adapter — Phase 7.
Searches tagged files in a local folder using sidecar JSON + filename convention.
Copies matching files to the session tmp dir (never moves/deletes originals).
"""
import json
import logging
import shutil
import uuid
from pathlib import Path

from rapidfuzz import fuzz

from services.source_adapters.base import BaseAdapter, MediaCandidate

logger = logging.getLogger(__name__)

IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".webp", ".gif", ".bmp"}
VIDEO_EXTS = {".mp4", ".mov", ".avi", ".mkv", ".webm"}
QUALITY_RANK = {"U": 4, "H": 3, "M": 2, "L": 1, None: 0}
FUZZY_THRESHOLD = 80  # per PRD §5.6


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


def _parse_convention(name: str) -> tuple[list[str], str | None, str | None]:
    """Parse filename convention → (tags, quality, uid)."""
    stem = Path(name).stem
    parts = stem.split("--")
    if len(parts) == 3:
        tag_section, quality_or_uid, uid_part = parts
        if quality_or_uid.upper() in ("U", "H", "M", "L"):
            tags = [t.replace("_", " ") for t in tag_section.split("_") if t]
            return tags, quality_or_uid.upper(), uid_part
    if len(parts) == 2:
        tag_section, uid_or_quality = parts
        if uid_or_quality.upper() in ("U", "H", "M", "L"):
            return [t.replace("_", " ") for t in tag_section.split("_") if t], uid_or_quality.upper(), None
        tags = [t.replace("_", " ") for t in tag_section.split("_") if t]
        return tags, None, uid_or_quality
    return [], None, None


class LocalFolderAdapter(BaseAdapter):
    def __init__(self, source_config: dict):
        super().__init__(source_config)
        self.folder = Path(source_config.get("folder_path", ""))
        enabled_exts = source_config.get("enabled_extensions")
        self.enabled_exts = set(enabled_exts) if enabled_exts else (IMAGE_EXTS | VIDEO_EXTS)
        self._cache: list[dict] | None = None  # session-scoped cache

    def _load_cache(self) -> list[dict]:
        if self._cache is not None:
            return self._cache

        if not self.folder.exists():
            logger.warning("Local folder not found: %s", self.folder)
            self._cache = []
            return self._cache

        entries = []
        for f in self.folder.iterdir():
            if not f.is_file():
                continue
            if f.suffix.lower() not in self.enabled_exts:
                continue
            if f.suffix.lower() == ".json":
                continue

            sidecar = _read_sidecar(f)
            if sidecar:
                tags = sidecar.get("tags", [])
                quality = sidecar.get("quality")
            else:
                tags, quality, _ = _parse_convention(f.name)

            entries.append({
                "path": f,
                "tags": tags,
                "quality": quality,
                "media_type": _media_type(f),
                "size_bytes": f.stat().st_size,
            })

        self._cache = entries
        return self._cache

    async def search(self, query: str, limit: int) -> list[MediaCandidate]:
        entries = self._load_cache()
        query_lower = query.lower()

        matches = []
        for entry in entries:
            best_score = 0
            for tag in entry["tags"]:
                score = fuzz.token_set_ratio(query_lower, tag.lower())
                if score > best_score:
                    best_score = score
            if best_score >= FUZZY_THRESHOLD:
                matches.append((best_score, entry))

        # Sort: quality grade desc, then fuzzy score desc, then size desc
        matches.sort(
            key=lambda x: (
                QUALITY_RANK.get(x[1]["quality"], 0),
                x[0],
                x[1]["size_bytes"],
            ),
            reverse=True,
        )

        candidates = []
        for _, entry in matches[:limit]:
            p: Path = entry["path"]
            candidates.append(MediaCandidate(
                id=f"local_{p.name}",
                source_id=self.config.get("source_id", 0),
                media_type=entry["media_type"],
                download_url=str(p),   # local path used as download URL
                preview_url=None,
                file_size_bytes=entry["size_bytes"],
            ))
        return candidates

    async def download(self, candidate: MediaCandidate, dest_path: Path) -> Path:
        """Copy the local file to dest_path — never move or delete the original."""
        src = Path(candidate.download_url)
        if not src.exists():
            raise RuntimeError(f"Local source file not found: {src}")
        dest_path.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, dest_path)
        return dest_path
