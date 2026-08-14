"""
Pixabay adapter — Phase 7.
Uses the Pixabay REST API (images + videos endpoints).
Requires api_key in source config.
"""
from pathlib import Path

import httpx

from services.source_adapters.base import BaseAdapter, MediaCandidate

IMAGE_URL = "https://pixabay.com/api/"
VIDEO_URL = "https://pixabay.com/api/videos/"


class PixabayAdapter(BaseAdapter):
    def __init__(self, source_config: dict):
        super().__init__(source_config)
        self.api_key: str = source_config.get("api_key", "")

    async def search(self, query: str, limit: int) -> list[MediaCandidate]:
        if not self.api_key:
            return []

        candidates: list[MediaCandidate] = []
        per_page = min(limit, 20)

        async with httpx.AsyncClient(timeout=15) as client:
            # Images
            try:
                resp = await client.get(
                    IMAGE_URL,
                    params={
                        "key": self.api_key,
                        "q": query,
                        "per_page": per_page,
                        "image_type": "photo",
                        "order": "popular",
                    },
                )
                if resp.status_code == 200:
                    for hit in resp.json().get("hits", []):
                        candidates.append(MediaCandidate(
                            id=f"pixabay_img_{hit['id']}",
                            source_id=self.config.get("source_id", 0),
                            media_type="image",
                            preview_url=hit.get("webformatURL"),
                            download_url=hit.get("largeImageURL"),
                            width=hit.get("imageWidth"),
                            height=hit.get("imageHeight"),
                            file_size_bytes=hit.get("imageSize"),
                        ))
            except Exception:
                pass

            # Videos
            try:
                resp = await client.get(
                    VIDEO_URL,
                    params={
                        "key": self.api_key,
                        "q": query,
                        "per_page": per_page,
                        "order": "popular",
                    },
                )
                if resp.status_code == 200:
                    for hit in resp.json().get("hits", []):
                        videos = hit.get("videos", {})
                        # Pick highest available resolution
                        for res in ("large", "medium", "small", "tiny"):
                            v = videos.get(res)
                            if v and v.get("url"):
                                candidates.append(MediaCandidate(
                                    id=f"pixabay_vid_{hit['id']}",
                                    source_id=self.config.get("source_id", 0),
                                    media_type="video",
                                    preview_url=hit.get("userImageURL"),
                                    download_url=v["url"],
                                    width=v.get("width"),
                                    height=v.get("height"),
                                    duration_seconds=hit.get("duration"),
                                    file_size_bytes=v.get("size"),
                                ))
                                break
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
                resp = await client.get(IMAGE_URL, params={"key": self.api_key, "q": "test", "per_page": 3})
            return resp.status_code == 200
        except Exception:
            return False
