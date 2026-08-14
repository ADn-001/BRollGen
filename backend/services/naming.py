"""
Filename convention parser and builder — Phase 12.

Convention: [tag1]_[tag2]_[tag3]--[quality]--[uid].[ext]
  - Tags: lowercase, words within a tag phrase joined by underscores; different tags also separated by _
  - Quality (optional): U | H | M | L
  - UID: 6-digit zero-padded integer

Examples:
  space_marine_ultramarines_warhammer--H--000042.jpg
  chaos_warp_storm--U--000107.mp4
  ocean_waves--000015.png   (no quality tag)
  image001.jpg              (unrecognized — raw file)
"""
from pathlib import Path


QUALITY_VALUES = {"U", "H", "M", "L"}


def parse_filename(filename: str) -> dict:
    """
    Parse a filename and return:
      {tags: list[str], quality: str|None, uid: str|None}

    If the filename doesn't match the convention, returns:
      {tags: [], quality: None, uid: None}
    """
    stem = Path(filename).stem
    parts = stem.split("--")

    # Full format: tag_section--quality--uid
    if len(parts) == 3:
        tag_section, maybe_quality, maybe_uid = parts
        if maybe_quality.upper() in QUALITY_VALUES:
            tags = _parse_tag_section(tag_section)
            return {"tags": tags, "quality": maybe_quality.upper(), "uid": maybe_uid}

    # No-quality format: tag_section--uid
    if len(parts) == 2:
        tag_section, maybe_uid_or_quality = parts
        if maybe_uid_or_quality.upper() in QUALITY_VALUES:
            # Actually quality-only (no UID)
            return {
                "tags": _parse_tag_section(tag_section),
                "quality": maybe_uid_or_quality.upper(),
                "uid": None,
            }
        # Assume it's the UID (numeric string)
        return {
            "tags": _parse_tag_section(tag_section),
            "quality": None,
            "uid": maybe_uid_or_quality,
        }

    # Unrecognized — raw file
    return {"tags": [], "quality": None, "uid": None}


def _parse_tag_section(tag_section: str) -> list[str]:
    """
    Split tag section on underscores.
    Each token is treated as a separate single-word tag (no sidecar available here).
    With a sidecar JSON, the caller can group tokens back into multi-word phrases.
    """
    return [t.replace("_", " ") for t in tag_section.split("_") if t]


def build_filename(tags: list[str], quality: str | None, uid: str, ext: str) -> str:
    """
    Build a canonical filename from components.

    tags:    list of tag strings (e.g. ["space marine", "ultramarines"])
    quality: "U" | "H" | "M" | "L" | None
    uid:     6-digit zero-padded string (e.g. "000042")
    ext:     file extension including dot (e.g. ".jpg")

    Result: "space_marine_ultramarines--H--000042.jpg"
    """
    tag_section = "_".join(t.lower().replace(" ", "_") for t in tags if t.strip())
    if quality and quality.upper() in QUALITY_VALUES:
        return f"{tag_section}--{quality.upper()}--{uid}{ext.lower()}"
    return f"{tag_section}--{uid}{ext.lower()}"
