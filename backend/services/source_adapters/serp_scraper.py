"""
SerpAPI / Playwright scraper adapter — Phase 7.
Primary: SerpAPI Google Images (if serpapi_key configured).
Fallback: Playwright headless Chromium scraping google images.
"""
import logging
from pathlib import Path
from typing import cast

import httpx

from services.source_adapters.base import BaseAdapter, MediaCandidate

logger = logging.getLogger(__name__)

SERPAPI_URL = "https://serpapi.com/search"


class SerpScraperAdapter(BaseAdapter):
    def __init__(self, source_config: dict):
        super().__init__(source_config)
        self.serpapi_key: str = source_config.get("serpapi_key", "")
        self.max_results: int = int(source_config.get("max_results", 10))

    async def search(self, query: str, limit: int) -> list[MediaCandidate]:
        effective_limit = min(limit, self.max_results)
        if self.serpapi_key:
            return await self._search_serpapi(query, effective_limit)
        return await self._search_playwright(query, effective_limit)

    async def _search_serpapi(self, query: str, limit: int) -> list[MediaCandidate]:
        try:
            async with httpx.AsyncClient(timeout=20) as client:
                resp = await client.get(
                    SERPAPI_URL,
                    params={
                        "api_key": self.serpapi_key,
                        "engine": "google_images",
                        "q": query,
                        "num": limit,
                    },
                )
            if resp.status_code != 200:
                logger.warning("SerpAPI returned HTTP %d", resp.status_code)
                return []
            results = resp.json().get("images_results", [])
        except Exception as exc:
            logger.warning("SerpAPI request failed: %s", exc)
            return []

        candidates = []
        for r in results[:limit]:
            w = r.get("original_width")
            h = r.get("original_height")
            if w and h and (w < 200 or h < 200):
                continue  # skip thumbnails
            candidates.append(MediaCandidate(
                id=f"serp_{r.get('position', 0)}",
                source_id=self.config.get("source_id", 0),
                media_type="image",
                preview_url=r.get("thumbnail"),
                download_url=r.get("original"),
                width=w,
                height=h,
            ))
        return candidates

    async def _search_playwright(self, query: str, limit: int) -> list[MediaCandidate]:
        """
        Headless Chromium fallback — loads Google Images, extracts src URLs.
        Skips thumbnails smaller than 200px in either dimension.
        """
        try:
            from playwright.async_api import async_playwright
        except ImportError:
            logger.error("Playwright not installed — install with: playwright install chromium")
            return []

        candidates: list[MediaCandidate] = []
        url = f"https://www.google.com/search?q={query}&tbm=isch"

        try:
            async with async_playwright() as p:
                browser = await p.chromium.launch(args=["--no-sandbox"])
                page = await browser.new_page()
                await page.goto(url, timeout=15000)
                await page.wait_for_timeout(2000)

                # Extract image sources from search results
                images = await page.query_selector_all("img")
                for img in images:
                    src = await img.get_attribute("src") or ""
                    if not src.startswith("http"):
                        continue
                    w = await img.get_attribute("width")
                    h = await img.get_attribute("height")
                    try:
                        wi, hi = int(w or 0), int(h or 0)
                    except ValueError:
                        wi, hi = 0, 0
                    if wi < 200 or hi < 200:
                        continue
                    candidates.append(MediaCandidate(
                        id=f"playwright_{len(candidates)}",
                        source_id=self.config.get("source_id", 0),
                        media_type="image",
                        preview_url=src,
                        download_url=src,
                        width=wi if wi > 0 else None,
                        height=hi if hi > 0 else None,
                    ))
                    if len(candidates) >= limit:
                        break

                await browser.close()
        except Exception as exc:
            logger.warning("Playwright scrape failed: %s", exc)

        return candidates

    async def download(self, candidate: MediaCandidate, dest_path: Path) -> Path:
        async with httpx.AsyncClient(timeout=30, follow_redirects=True) as client:
            async with client.stream("GET", candidate.download_url) as resp:
                resp.raise_for_status()
                dest_path.parent.mkdir(parents=True, exist_ok=True)
                with open(dest_path, "wb") as f:
                    async for chunk in resp.aiter_bytes(8192):
                        f.write(chunk)
        return dest_path
