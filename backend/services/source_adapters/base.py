"""
Base adapter interface that all source adapters must implement.
New adapters go in services/source_adapters/ and inherit from BaseAdapter.
"""
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal


@dataclass
class MediaCandidate:
    id: str
    source_id: int
    media_type: Literal["image", "video"]
    download_url: str
    preview_url: str | None = None
    width: int | None = None
    height: int | None = None
    duration_seconds: float | None = None
    file_size_bytes: int | None = None
    # Computed in downloader.py after metadata is available
    quality_score: float = 0.0


class BaseAdapter(ABC):
    def __init__(self, source_config: dict):
        self.config = source_config

    @abstractmethod
    async def search(self, query: str, limit: int) -> list[MediaCandidate]:
        """
        Search for media matching `query`.
        Returns up to `limit` candidates ordered best-first by quality.
        Must NOT download files — only return metadata/URLs.
        """
        ...

    @abstractmethod
    async def download(self, candidate: MediaCandidate, dest_path: Path) -> Path:
        """
        Download `candidate` to `dest_path`.
        Returns the path of the saved file (may differ if extension changes).
        Raises RuntimeError on failure.
        """
        ...

    async def health_check(self) -> bool:
        """
        Lightweight connectivity check.
        Return True if the source is reachable, False otherwise.
        Default implementation always returns True (override for API sources).
        """
        return True
