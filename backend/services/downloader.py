"""
Download orchestrator — Phase 8.

Per PRD §5.4:
- Always search ALL sources for every tag (no short-circuit on first hit).
- quality_score = width*height (images) or width*height*bitrate (video); file_size proxy if unavailable.
- multi_item_per_tag=ON → keep single best across all sources.
- multi_item_per_tag=OFF → keep all results from all sources.
- dedupe_repeat_tags=OFF → for K occurrences of same word, find K distinct files; reuse best if fewer found.
- redundant_source_download=ON → overrides multi_item_per_tag/dedupe selection entirely:
  downloads the best-1 result from EACH enabled source per tag (see _download_redundant_for_tag).
"""
import asyncio
import logging
import mimetypes
import random
import time
import uuid
from pathlib import Path

import httpx
from PIL import Image
from sqlalchemy.orm import Session

from db.models import MediaSource, NicheProfile, ProfileSourceLink
from services.source_adapters.base import MediaCandidate
from session_state import DownloadResult, Session as AppSession, Tag

logger = logging.getLogger(__name__)


# ── Adapter factory ───────────────────────────────────────────────────────────

def _get_adapter(source: MediaSource):
    cfg = dict(source.config or {})
    cfg["source_id"] = source.id
    if source.type == "pexels":
        from services.source_adapters.pexels import PexelsAdapter
        return PexelsAdapter(cfg)
    if source.type == "pixabay":
        from services.source_adapters.pixabay import PixabayAdapter
        return PixabayAdapter(cfg)
    if source.type == "unsplash":
        from services.source_adapters.unsplash import UnsplashAdapter
        return UnsplashAdapter(cfg)
    if source.type == "serp_scraper":
        from services.source_adapters.serp_scraper import SerpScraperAdapter
        return SerpScraperAdapter(cfg)
    if source.type == "custom_adapter":
        from services.source_adapters.custom_adapter import CustomAdapter
        return CustomAdapter(cfg)
    if source.type == "local_folder":
        from services.source_adapters.local_folder import LocalFolderAdapter
        return LocalFolderAdapter(cfg)
    raise ValueError(f"Unknown source type: {source.type}")


# ── Per-source rate-limit delay ───────────────────────────────────────────────

async def _apply_source_delay(source: MediaSource, last_times: dict[int, float]) -> None:
    """
    Sleep if needed to honour this source's configured request_delay_seconds.

    request_delay_seconds semantics (from DB column):
      None  → random delay between 2 and 30 seconds on each request
      0.0   → no delay
      N > 0 → fixed N-second gap between consecutive requests to this source

    The delay is the MINIMUM gap — if the previous download already took longer
    than the configured delay, no additional sleep is injected.

    local_folder sources are always skipped (no network involved).
    """
    if source.type == "local_folder":
        return

    delay_cfg = source.request_delay_seconds  # None | 0.0 | float

    if delay_cfg is not None and delay_cfg <= 0:
        # Explicitly disabled
        return

    target_gap: float
    if delay_cfg is None:
        target_gap = random.uniform(2.0, 30.0)
    else:
        target_gap = float(delay_cfg)

    last_t = last_times.get(source.id)
    if last_t is None:
        # First request to this source in this session — no delay needed
        return

    elapsed = time.monotonic() - last_t
    wait = target_gap - elapsed
    if wait > 0:
        logger.debug(
            "Rate-limit delay %.1fs before next download from source '%s'",
            wait, source.name,
        )
        await asyncio.sleep(wait)


# ── Quality scoring ───────────────────────────────────────────────────────────

def _compute_quality_score(candidate: MediaCandidate, media_type: str) -> float:
    w, h = candidate.width, candidate.height
    if w and h:
        if media_type == "image":
            return float(w * h)
        # video: use resolution; bitrate not available from metadata at search time
        return float(w * h)
    # Proxy: file size in KB
    if candidate.file_size_bytes:
        return float(candidate.file_size_bytes) * 0.001
    return 0.0


# ── File metadata reading ─────────────────────────────────────────────────────

def _read_image_dimensions(path: Path) -> tuple[int | None, int | None]:
    try:
        with Image.open(path) as img:
            return img.size  # (width, height)
    except Exception:
        return None, None


# ── Extension inference ───────────────────────────────────────────────────────

def _infer_ext(url: str, content_type: str | None) -> str:
    """Guess file extension from URL path or Content-Type."""
    from urllib.parse import urlparse
    parsed = urlparse(url)
    path_ext = Path(parsed.path).suffix.lower()
    if path_ext in {".jpg", ".jpeg", ".png", ".webp", ".mp4", ".mov", ".avi", ".mkv"}:
        return path_ext
    if content_type:
        ext = mimetypes.guess_extension(content_type.split(";")[0].strip())
        if ext:
            return ext
    return ".bin"


# ── Download a single candidate ───────────────────────────────────────────────

async def _download_candidate(
    adapter,
    candidate: MediaCandidate,
    dest_path: Path,
) -> Path:
    """Call adapter.download(); return the saved path."""
    return await adapter.download(candidate, dest_path)


# ── Per-tag search across all sources ────────────────────────────────────────

async def _search_tag(
    tag: Tag,
    sources: list[MediaSource],
    limit_per_source: int,
    multi_item: bool,
) -> list[tuple[MediaCandidate, MediaSource]]:
    """
    Search all sources for `tag.word`. Always completes all sources.
    Returns list of (candidate, source) pairs.
    """
    all_candidates: list[tuple[MediaCandidate, MediaSource]] = []

    for source in sources:
        if not source.enabled:
            continue
        try:
            adapter = _get_adapter(source)
            candidates = await adapter.search(tag.word, limit_per_source)
            for c in candidates:
                c.quality_score = _compute_quality_score(c, c.media_type)
            all_candidates.extend((c, source) for c in candidates)
        except Exception as exc:
            logger.warning("Source '%s' search failed for tag '%s': %s", source.name, tag.word, exc)

    if not all_candidates:
        return []

    # Shuffle first so that ties in quality score resolve randomly rather than
    # always favouring the first result returned by the source.  After the
    # shuffle, a stable sort preserves the random ordering within equal-score
    # groups (Python's sort is guaranteed stable).
    random.shuffle(all_candidates)

    if multi_item:
        # Best single result across all sources; random among tied top scorers.
        top_score = max(c.quality_score for c, _ in all_candidates)
        top_candidates = [(c, s) for c, s in all_candidates if c.quality_score == top_score]
        return [random.choice(top_candidates)]
    else:
        # All results, sorted quality desc; shuffle-before-sort randomises ties.
        all_candidates.sort(key=lambda x: x[0].quality_score, reverse=True)
        return all_candidates


# ── Redundant source download (best-1 per source per tag) ────────────────────

_BIN_EXT_MAP = {
    "jpeg": ".jpg", "png": ".png", "webp": ".webp",
    "gif": ".gif", "bmp": ".bmp",
}


async def _fix_bin_extension(saved_path: Path) -> Path:
    """If saved with a generic .bin extension, sniff the real format and rename."""
    if saved_path.suffix.lower() != ".bin":
        return saved_path
    try:
        with Image.open(saved_path) as _img:
            real_ext = _BIN_EXT_MAP.get((_img.format or "").lower())
        if real_ext:
            new_path = saved_path.with_suffix(real_ext)
            saved_path.rename(new_path)
            return new_path
    except Exception:
        pass  # leave as .bin — preview will still try to serve it
    return saved_path


async def _download_redundant_for_tag(
    tag: Tag,
    sources: list[MediaSource],
    sess: AppSession,
    last_download_time: dict[int, float],
) -> list[DownloadResult]:
    """
    Redundant source download mode: download the single best result from
    EACH enabled source for this tag (instead of the one globally-best
    result). Produces up to len(sources) DownloadResult entries, all
    sharing the same tag/occurrence_index — the review UI groups them.
    """
    tag_results: list[DownloadResult] = []

    for source in sources:
        if not source.enabled:
            continue

        sess.current_item_label = f'Searching: "{tag.word}" from {source.name}'
        try:
            adapter = _get_adapter(source)
            candidates = await adapter.search(tag.word, 5)
            if not candidates:
                continue
            for c in candidates:
                c.quality_score = _compute_quality_score(c, c.media_type)
            best = max(candidates, key=lambda c: c.quality_score)

            uid = str(uuid.uuid4())[:8]
            ext = _infer_ext(best.download_url, None)
            dest = sess.tmp_dir / f"{uid}{ext}"

            sess.current_item_label = f'Downloading: "{tag.word}" from {source.name}'
            await _apply_source_delay(source, last_download_time)
            saved_path = await _download_candidate(adapter, best, dest)
            last_download_time[source.id] = time.monotonic()

            saved_path = await _fix_bin_extension(saved_path)

            w, h = best.width, best.height
            if best.media_type == "image":
                img_w, img_h = _read_image_dimensions(saved_path)
                if img_w and img_h:
                    w, h = img_w, img_h

            size_bytes = saved_path.stat().st_size

            tag_results.append(DownloadResult(
                tag=tag,
                tag_occurrence_index=tag.occurrence_index,
                source_id=source.id,
                source_name=source.name,
                file_path=saved_path,
                media_type=best.media_type,
                width=w,
                height=h,
                file_size_bytes=size_bytes,
                quality_score=float(w * h) if (w and h) else float(size_bytes) * 0.001,
                kept=True,
            ))
        except Exception as exc:
            logger.warning(
                "Redundant download failed for tag '%s' from source '%s': %s",
                tag.word, source.name, exc,
            )
            # Non-fatal: this source is simply skipped for this tag

    return tag_results


# ── Main orchestrator ─────────────────────────────────────────────────────────

async def run_downloads(sess: AppSession, db: Session) -> list[DownloadResult]:
    """
    Entry point called from sessions router.
    Downloads media for all tags in sess.extracted_tags.
    Returns list of DownloadResult objects.
    """
    profile: NicheProfile = db.get(NicheProfile, sess.profile_id)
    if profile is None:
        raise RuntimeError(f"Profile {sess.profile_id} not found.")

    # Load sources ordered by priority
    links: list[ProfileSourceLink] = (
        db.query(ProfileSourceLink)
        .filter(ProfileSourceLink.profile_id == profile.id)
        .order_by(ProfileSourceLink.priority)
        .all()
    )
    sources: list[MediaSource] = [
        lnk.source for lnk in links if lnk.source and lnk.source.enabled
    ]
    if not sources:
        logger.warning("No enabled sources for profile %d — no downloads possible.", profile.id)
        return []

    multi_item = profile.multi_item_per_tag
    limit_per_source = 15 if multi_item else 30
    redundant_mode = profile.redundant_source_download

    results: list[DownloadResult] = []

    # Tracks monotonic time of last completed download per source_id,
    # used by _apply_source_delay() to enforce per-source rate-limit gaps.
    last_download_time: dict[int, float] = {}

    # Group tags by word for dedupe=OFF duplicate handling
    from collections import defaultdict
    tag_groups: dict[str, list[Tag]] = defaultdict(list)
    for tag in sess.extracted_tags:
        tag_groups[tag.word.lower()].append(tag)

    processed_words: set[str] = set()

    items_total = len(sess.extracted_tags)
    items_processed = 0

    for tag in sess.extracted_tags:
        word_key = tag.word.lower()
        if word_key in processed_words and sess.dedupe_repeat_tags:
            continue
        processed_words.add(word_key)

        items_processed += 1
        sess.current_item_index = items_processed - 1

        sess.current_item_label = f'Searching: "{tag.word}" ({items_processed} of {items_total})'

        if redundant_mode:
            # ── Redundant mode: best-1 per source per tag, skip normal
            # single-best-selection logic entirely for this tag ────────────
            results.extend(await _download_redundant_for_tag(tag, sources, sess, last_download_time))
            continue

        k = len(tag_groups[word_key])  # number of slots for this word

        # Search all sources
        candidates_with_sources = await _search_tag(tag, sources, limit_per_source, multi_item)

        if not candidates_with_sources:
            logger.info("No results for tag '%s' across all sources.", tag.word)
            continue

        # For dedupe=OFF, we need K distinct files
        distinct: list[tuple[MediaCandidate, MediaSource]] = []
        seen_urls: set[str] = set()
        for c, src in candidates_with_sources:
            if c.download_url not in seen_urls:
                distinct.append((c, src))
                seen_urls.add(c.download_url)

        # Fill K slots — reuse best if insufficient distinct files
        slots = tag_groups[word_key]
        download_plan: list[tuple[Tag, MediaCandidate, MediaSource, str | None]] = []
        for i, slot_tag in enumerate(slots):
            if i < len(distinct):
                cand, src = distinct[i]
                download_plan.append((slot_tag, cand, src, None))
            else:
                # Reuse the best available
                best_cand, best_src = distinct[0]
                reused_uid = results[0].file_path.stem if results else None
                download_plan.append((slot_tag, best_cand, best_src, str(best_cand.id)))

        # Download each planned item
        for slot_tag, cand, src, reused_from_uid in download_plan:
            uid = str(uuid.uuid4())[:8]
            ext = _infer_ext(cand.download_url, None)
            dest = sess.tmp_dir / f"{uid}{ext}"

            sess.current_item_label = (
                f'Downloading: "{slot_tag.word}" from {src.name} '
                f'({items_processed} of {items_total})'
            )

            try:
                # Honour per-source rate-limit delay before issuing the request
                await _apply_source_delay(src, last_download_time)

                adapter = _get_adapter(src)
                saved_path = await _download_candidate(adapter, cand, dest)
                last_download_time[src.id] = time.monotonic()

                # If the file was saved with a generic .bin extension (happens when the
                # download URL has no path extension, e.g. /download?id=foo), try to
                # detect the real format from the file bytes and rename before further use.
                if saved_path.suffix.lower() == ".bin":
                    _BIN_EXT_MAP = {
                        "jpeg": ".jpg", "png": ".png", "webp": ".webp",
                        "gif": ".gif", "bmp": ".bmp",
                    }
                    try:
                        with Image.open(saved_path) as _img:
                            _real_ext = _BIN_EXT_MAP.get((_img.format or "").lower())
                        if _real_ext:
                            _new_path = saved_path.with_suffix(_real_ext)
                            saved_path.rename(_new_path)
                            saved_path = _new_path
                    except Exception:
                        pass  # leave as .bin — preview will still try to serve it

                # Read dimensions if image (more accurate than API metadata)
                w, h = cand.width, cand.height
                if cand.media_type == "image":
                    img_w, img_h = _read_image_dimensions(saved_path)
                    if img_w and img_h:
                        w, h = img_w, img_h

                size_bytes = saved_path.stat().st_size
                quality_score = float(w * h) if (w and h) else float(size_bytes) * 0.001

                results.append(DownloadResult(
                    tag=slot_tag,
                    tag_occurrence_index=slot_tag.occurrence_index,
                    source_id=src.id,
                    source_name=src.name,
                    file_path=saved_path,
                    media_type=cand.media_type,
                    width=w,
                    height=h,
                    file_size_bytes=size_bytes,
                    quality_score=quality_score,
                    reused_from_uid=reused_from_uid,
                ))
            except Exception as exc:
                logger.warning(
                    "Download failed for tag '%s' from source '%s': %s",
                    tag.word, src.name, exc,
                )
                # Non-fatal: item is simply not added to results

    # Sort final results by occurrence_index (stitch order)
    results.sort(key=lambda r: r.tag_occurrence_index)
    sess.current_item_label = ""
    return results
