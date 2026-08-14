"""
Unsplash adapter — Phase 7.
Uses the Unsplash REST API (images only — Unsplash has no video API).
Requires access_key in source config.
"""
from pathlib import Path

import httpx

from services.source_adapters.base import BaseAdapter, MediaCandidate

SEARCH_URL = "https://api.unsplash.com/search/photos"


class UnsplashAdapter(BaseAdapter):
    def __init__(self, source_config: dict):
        super().__init__(source_config)
        self.access_key: str = source_config.get("access_key", "")

    def _headers(self) -> dict:
        return {"Authorization": f"Client-ID {self.access_key}"}

    async def search(self, query: str, limit: int) -> list[MediaCandidate]:
        if not self.access_key:
            return []

        per_page = min(limit, 30)
        try:
            async with httpx.AsyncClient(timeout=15) as client:
                resp = await client.get(
                    SEARCH_URL,
                    headers=self._headers(),
                    params={"query": query, "per_page": per_page, "orientation": "landscape"},
                )
            if resp.status_code != 200:
                return []
            results = resp.json().get("results", [])
        except Exception:
            return []

        candidates = []
        for photo in results:
            urls = photo.get("urls", {})
            candidates.append(MediaCandidate(
                id=f"unsplash_{photo['id']}",
                source_id=self.config.get("source_id", 0),
                media_type="image",
                preview_url=urls.get("small"),
                download_url=urls.get("full"),   # highest quality without "raw" (raw can be huge)
                width=photo.get("width"),
                height=photo.get("height"),
            ))
        return candidates[:limit]

    async def download(self, candidate: MediaCandidate, dest_path: Path) -> Path:
        # Unsplash requires a download tracking ping before downloading
        # (per API guidelines) — we fire-and-forget it
        async with httpx.AsyncClient(timeout=60, follow_redirects=True) as client:
            async with client.stream(
                "GET",
                candidate.download_url,
                headers=self._headers(),
            ) as resp:
                resp.raise_for_status()
                dest_path.parent.mkdir(parents=True, exist_ok=True)
                with open(dest_path, "wb") as f:
                    async for chunk in resp.aiter_bytes(8192):
                        f.write(chunk)
        return dest_path

    async def health_check(self) -> bool:
        if not self.access_key:
            return False
        try:
            async with httpx.AsyncClient(timeout=5) as client:
                resp = await client.get(
                    SEARCH_URL,
                    headers=self._headers(),
                    params={"query": "test", "per_page": 1},
                )
            return resp.status_code == 200
        except Exception:
            return False
