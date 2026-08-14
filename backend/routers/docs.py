"""
Adapter docs router — Phase 13.
Serves the bundled CUSTOM_ADAPTER_GUIDE.md as plain text.
"""
from pathlib import Path

from fastapi import APIRouter, HTTPException
from fastapi.responses import PlainTextResponse

router = APIRouter(tags=["docs"])

GUIDE_PATH = Path(__file__).parent.parent.parent / "docs" / "CUSTOM_ADAPTER_GUIDE.md"


@router.get("/docs/adapter")
def get_adapter_guide():
    if not GUIDE_PATH.exists():
        raise HTTPException(404, detail="Adapter guide not found.")
    return PlainTextResponse(GUIDE_PATH.read_text(encoding="utf-8"))
