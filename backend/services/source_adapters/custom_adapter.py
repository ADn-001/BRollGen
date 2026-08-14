"""
Custom adapter relay — Phase 7.
Communicates with any user-hosted HTTP server implementing the B-Roll Engine adapter protocol.
See docs/CUSTOM_ADAPTER_GUIDE.md for the full protocol spec.
"""
import logging
from pathlib import Path

import httpx

from services.source_adapters.base import BaseAdapter, MediaCandidate

logger = logging.getLogger(__name__)


class CustomAdapter(BaseAdapter):
    def __init__(self, source_config: dict):
        super().__init__(source_config)
        self.base_url: str = source_config.get("adapter_url", "").rstrip("/")
        self.auth_token: str = source_config.get("auth_token", "")

    def _headers(self) -> dict:
        if self.auth_token:
            return {"Authorization": f"Bearer {self.auth_token}"}
        return {}

    async def search(self, query: str, limit: int) -> list[MediaCandidate]:
        if not self.base_url:
            return []
        try:
            async with httpx.AsyncClient(timeout=60) as client:
                resp = await client.get(
                    f"{self.base_url}/search",
                    headers=self._headers(),
                    params={"q": query, "limit": limit, "media_type": "any"},
                )
            if resp.status_code != 200:
                logger.warning("Custom adapter /search returned HTTP %d", resp.status_code)
                return []
            data = resp.json()
        except Exception as exc:
            logger.warning("Custom adapter search failed: %s", exc)
            return []

        candidates = []
        for r in data.get("results", [])[:limit]:
            candidates.append(MediaCandidate(
                id=str(r["id"]),
                source_id=self.config.get("source_id", 0),
                media_type=r.get("media_type", "image"),
                preview_url=r.get("preview_url"),
                download_url=r["download_url"],
                width=r.get("width"),
                height=r.get("height"),
                duration_seconds=r.get("duration_seconds"),
                file_size_bytes=r.get("file_size_bytes"),
            ))
        return candidates

    async def download(self, candidate: MediaCandidate, dest_path: Path) -> Path:
        """
        If download_url is a direct file URL, download it directly.
        Otherwise, use the /download?id= endpoint.
        """
        url = candidate.download_url
        async with httpx.AsyncClient(timeout=60, follow_redirects=True) as client:
            async with client.stream("GET", url, headers=self._headers()) as resp:
                resp.raise_for_status()
                dest_path.parent.mkdir(parents=True, exist_ok=True)
                with open(dest_path, "wb") as f:
                    async for chunk in resp.aiter_bytes(8192):
                        f.write(chunk)
        return dest_path

    async def health_check(self) -> bool:
        if not self.base_url:
            return False
        try:
            async with httpx.AsyncClient(timeout=5) as client:
                resp = await client.get(f"{self.base_url}/health", headers=self._headers())
            return resp.status_code == 200
        except Exception:
            return False
