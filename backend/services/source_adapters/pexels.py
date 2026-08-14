"""
Pexels adapter — Phase 7.
Uses the Pexels REST API (photos + videos endpoints).
Requires api_key in source config.
"""
from pathlib import Path

import httpx

from services.source_adapters.base import BaseAdapter, MediaCandidate

PHOTO_URL = "https://api.pexels.com/v1/search"
VIDEO_URL = "https://api.pexels.com/videos/search"


class PexelsAdapter(BaseAdapter):
    def __init__(self, source_config: dict):
        super().__init__(source_config)
        self.api_key: str = source_config.get("api_key", "")

    def _headers(self) -> dict:
        return {"Authorization": self.api_key}

    async def search(self, query: str, limit: int) -> list[MediaCandidate]:
        if not self.api_key:
            return []

        candidates: list[MediaCandidate] = []
        per_page = min(limit, 15)

        async with httpx.AsyncClient(timeout=15) as client:
            # Photos
            try:
                resp = await client.get(
                    PHOTO_URL,
                    headers=self._headers(),
                    params={"query": query, "per_page": per_page, "orientation": "landscape"},
                )
                if resp.status_code == 200:
                    for p in resp.json().get("photos", []):
                        src = p.get("src", {})
                        candidates.append(MediaCandidate(
                            id=f"pexels_photo_{p['id']}",
                            source_id=self.config.get("source_id", 0),
                            media_type="image",
                            preview_url=src.get("medium"),
                            download_url=src.get("original"),
                            width=p.get("width"),
                            height=p.get("height"),
                        ))
            except Exception:
                pass

            # Videos
            try:
                resp = await client.get(
                    VIDEO_URL,
                    headers=self._headers(),
                    params={"query": query, "per_page": per_page},
                )
                if resp.status_code == 200:
                    for v in resp.json().get("videos", []):
                        # Pick highest-res video file
                        files = sorted(
                            v.get("video_files", []),
                            key=lambda f: (f.get("width") or 0) * (f.get("height") or 0),
                            reverse=True,
                        )
                        best = files[0] if files else None
                        if best:
                            candidates.append(MediaCandidate(
                                id=f"pexels_video_{v['id']}",
                                source_id=self.config.get("source_id", 0),
                                media_type="video",
                                preview_url=v.get("image"),
                                download_url=best.get("link"),
                                width=best.get("width"),
                                height=best.get("height"),
                                duration_seconds=v.get("duration"),
                            ))
            except Exception:
                pass

        return candidates[:limit]

    async def download(self, candidate: MediaCandidate, dest_path: Path) -> Path:
        async with httpx.AsyncClient(timeout=60, follow_redirects=True) as client:
            async with client.stream("GET", candidate.download_url) as resp:
                resp.raise_for_status()
                dest_path.parent.mkdir(parents=True, exist_ok=True)
                with open(dest_path, "wb") as f:
                    async for chunk in resp.aiter_bytes(8192):
                        f.write(chunk)
        return dest_path

    async def health_check(self) -> bool:
        if not self.api_key:
            return False
        try:
            async with httpx.AsyncClient(timeout=5) as client:
                resp = await client.get(
                    PHOTO_URL,
                    headers=self._headers(),
                    params={"query": "test", "per_page": 1},
                )
            return resp.status_code == 200
        except Exception:
            return False
