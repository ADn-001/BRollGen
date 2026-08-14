"""
B-Roll Engine — FastAPI entry point.
Run from backend/ directory: uvicorn main:app --host 127.0.0.1 --port 7420
"""
import logging
import shutil
import time
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from routers import docs, export, local_library, preview, profiles, sessions, settings, sources, uploads

logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO, format="%(levelname)s [%(name)s] %(message)s")

# Project root is one level above backend/
PROJECT_ROOT = Path(__file__).parent.parent
TMP_DIR = PROJECT_ROOT / "tmp"
TMP_MAX_AGE_HOURS = 24


def _sweep_old_tmp_folders() -> None:
    """Delete any tmp/{session_id} folder whose mtime is older than 24 hours."""
    if not TMP_DIR.exists():
        TMP_DIR.mkdir(parents=True)
        return
    now = time.time()
    for folder in TMP_DIR.iterdir():
        if not folder.is_dir():
            continue
        age_hours = (now - folder.stat().st_mtime) / 3600
        if age_hours > TMP_MAX_AGE_HOURS:
            shutil.rmtree(folder, ignore_errors=True)
            logger.info("Swept orphaned tmp folder (%.1fh old): %s", age_hours, folder.name)


@asynccontextmanager
async def lifespan(app: FastAPI):
    # --- Startup ---
    TMP_DIR.mkdir(parents=True, exist_ok=True)
    _sweep_old_tmp_folders()
    app.state.sessions: dict[str, object] = {}  # session_id → Session (see session_state.py)
    # adapter_url → subprocess.Popen, for adapters auto-launched via
    # POST /profiles/{id}/adapters/start (see routers/profiles.py)
    app.state.adapter_processes: dict[str, object] = {}
    logger.info("B-Roll Engine started. Tmp dir: %s", TMP_DIR)
    yield
    # --- Shutdown ---
    for url, proc in getattr(app.state, "adapter_processes", {}).items():
        try:
            proc.terminate()
            logger.info("Terminated adapter process for %s", url)
        except Exception:
            pass
    logger.info("B-Roll Engine shutting down.")


app = FastAPI(
    title="B-Roll Engine",
    version="1.0.0",
    description="Local B-roll search, download, and stitch tool.",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:5173",
        "http://127.0.0.1:5173",
        "http://localhost:7420",
        "http://127.0.0.1:7420",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# --- API Routers ---
app.include_router(profiles.router, prefix="/api")
app.include_router(sources.router, prefix="/api")
app.include_router(uploads.router, prefix="/api")
app.include_router(sessions.router, prefix="/api")
app.include_router(settings.router, prefix="/api")
app.include_router(local_library.router, prefix="/api")
app.include_router(preview.router, prefix="/api")
app.include_router(export.router, prefix="/api")
app.include_router(docs.router, prefix="/api")


# --- Serve React frontend in production (dist/ must exist) ---
_frontend_dist = PROJECT_ROOT / "frontend" / "dist"
if _frontend_dist.exists():
    # Mount at "/" — must be LAST so API routes take priority
    app.mount("/", StaticFiles(directory=str(_frontend_dist), html=True), name="frontend")
    logger.info("Serving frontend from %s", _frontend_dist)
else:
    logger.warning(
        "Frontend dist not found at %s — run 'npm run build' in frontend/. "
        "In dev mode, use Vite dev server on port 5173.",
        _frontend_dist,
    )
