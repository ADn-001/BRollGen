# B-Roll Engine — Project Handoff

**Date:** 2026-08-14
**Status:** All 6 implementation phases COMPLETE, including a confirmed live `docker-compose up` run (Phase 6 Part C), plus several post-handoff maintenance passes — see GATELOG for full detail on each:
- Docker docs-404 fix; local_folder/adapter-script file upload replacing host-path text input; removal of dead ffmpeg/Real-ESRGAN UI and the profile fields that fed the removed video pipeline (D13–D15)
- Local Library page full redesign (source picker → preview → tag/delete controls, incl. Niche Profile quick-tag buttons → file card grid → upload/download)
- Fixed a Local Library folder-detection bug (stale/empty `config.folder_path` and `enabled_extensions` handling) and added folder cleanup on source delete
- Docker deployment verified working end-to-end (WH40k profile → 40k.gallery adapter → real search results downloaded), then torn down (`docker-compose down --rmi all -v --remove-orphans`) in favor of native `start.bat` runs for faster adapter iteration — Docker remains the plan for eventual VPS deployment (see `DOCKER_SETUP.md`)
- Adapter Base URL confirmed to need swapping between `localhost` (native) and the Compose service name (Docker) depending on how the app is currently running — documented in `DOCKER_SETUP.md` and `docs/USER_GUIDE.md` §11
- First push to a GitHub remote (`https://github.com/ADn-001/BRollGen.git`), tagged `v1.0.0`

**Next action:** None required to continue development. Ordinary maintenance/bug-fix work as it comes up. Note: `alembic upgrade head` needs to be re-run to pick up migration `004` (drops now-unused `niche_profiles` columns) if it hasn't been already.

---

## What This Project Is

**B-Roll Engine** — a locally-hosted Windows web app at `D:\yt_vids\automation ecosystem\BRollGen`.

- **Backend:** Python 3.10+ FastAPI, port 7420, SQLite via SQLAlchemy (sync ORM), Alembic migrations
- **Frontend:** React 18 + Vite, TailwindCSS, Zustand, React Query, Framer Motion, React Router v6
- **Adapters:** Three Flask scrapers at ports 3000 (40k.gallery), 3001 (artvee.com), 3002 (loc.gov), each using a persistent Playwright browser (Phase 5)

For a full end-user walkthrough of every feature, see `docs/USER_GUIDE.md`. For the adapter protocol and how to write new adapters, see `docs/CUSTOM_ADAPTER_GUIDE.md` (also served in-app at `/docs/adapter`).

---

## Behavioral Rules

- Address the user as **"my Grand Regent"** or **"Grand Regent"** at the start of every reply.
- Do not write stubs, mockup code, or fake tests. All implementations must be E2E real.
- Consult the user before making design decisions that stray from the PRD or confirmed decisions.
- Do not change anything outside the stated scope of the current task (surgical changes only).
- Workflow for any new phase/change request: implement → run tests → user provides terminal output → debug until green → update GATELOG.

---

## Change Request Summary

These were the 7 confirmed changes implemented across the 6 phases, plus one feature added during Phase 6. All are now implemented.

| # | Change | Summary | Status |
|---|--------|---------|--------|
| 1 | Settings Persistence | Already done pre-project — no change needed | N/A |
| 2 | N Unique Downloads for Duplicate Tags | Current logic satisfactory — no change | N/A |
| 3 | VideoStitch Export | Kept existing ZIP (`001_` padding unchanged). Added "Export for VideoStitch" button producing no-zero-padding ZIP (`1_`, `10_`, `100_`) | DONE (Phase 2) |
| 4 | Duplicate Tags Toggle | Per-session toggle in Script Analysis mode only. Toggle overrides profile default for that session | DONE (Phase 3) |
| 5 | Remove ffmpeg / stitcher / upscaler | Removed entirely — `stitcher.py`, `upscaler.py`, sweep routes, video export routes, upscale fields, realesrgan test endpoint, video UI. Files export untouched as downloaded | DONE (Phase 1) |
| 6 | Real-Time Progress Bar | SSE adds `current_item_label`. Format: `Searching: "emperor" (1 of 8)` and `Downloading: "emperor" from loc.gov (1 of 8)` | DONE (Phase 4) |
| 7 | Architecture improvements | (a) Persistent Playwright browsers with stateless fallback; (b) Profile selection auto-starts connected adapters; (c) Docker: one container per adapter | DONE (Phases 5 & 6) |
| + | Redundant Source Download | New `NicheProfile` boolean. When ON: download best-1 from each source per tag. Review page groups redundant files by tag — user picks what to keep | DONE (Phase 6 Part B) |

---

## Phase Status

| Phase | Title | Status | Gate |
|-------|-------|--------|------|
| 1 | Remove Stitcher / Upscaler | **COMPLETE** — 16/16 tests green | — |
| 2 | VideoStitch Export + Adaptive Naming | **COMPLETE** — 10/10 tests green | Was blocked by Phase 1 — satisfied |
| 3 | Duplicate Tags Session Toggle | **COMPLETE** — 9/9 tests green | Independent |
| 4 | Real-Time Progress Bar (per-item text) | **COMPLETE** — 11/11 tests green | Independent |
| 5 | Persistent Playwright Browser in Adapters | **COMPLETE** — 21/21 tests green | Independent |
| 6 | Adapter Lifecycle + Redundant Source Download + Docker | **COMPLETE** — Parts A+B: 14/14 tests green, migration `003` applied and verified. Part C: `docker-compose up` confirmed live, all 4 containers (app + 3 adapters) build and run healthy | Was blocked by Phase 5 — satisfied |

---

## Implementation Plan Documents

All plans are at `D:\yt_vids\automation ecosystem\BRollGen\docs\implementation\`:

- `GATELOG.md` — master tracking: phase status, locked decisions (D1–D12), open questions (OQ1–OQ4, all resolved), crucial discovered facts, file inventory. **This is the authoritative source of truth for project state — read it first for anything phase-related.**
- `phase_01_cleanup.md` — 7 steps, 16-test pytest suite
- `phase_02_videostitch_export.md` — 3 steps, 12-test pytest suite (10 ran/green)
- `phase_03_duplicate_tags_toggle.md` — 5 steps, 10-test pytest suite (9 ran/green)
- `phase_04_progress_bar.md` — 4 steps, 11-test pytest suite
- `phase_05_persistent_playwright.md` — 4 steps, pytest suite (code inspection + live adapter tests)
- `phase_06_adapter_lifecycle_redundant_docker.md` — 3 parts (A: adapter lifecycle, B: redundant download, C: Docker), separate test files

Each plan contains: objective, files affected, numbered implementation steps with exact code, complete runnable pytest test suite, terminal command to run tests, and pass criteria. Treat these as historical record now that all phases are done — for current app behavior, prefer reading the actual source files or `docs/USER_GUIDE.md`, since a few plan docs (and the original PRD) contained bugs or later-superseded assumptions that were caught and corrected during implementation (see Crucial Technical Facts below).

---

## Locked Design Decisions

| # | Decision |
|---|----------|
| D1 | Existing ZIP export keeps `001_` zero-padded naming unchanged |
| D2 | New VideoStitch export: no-zero-padding (`1_`, `10_`, `100_`) |
| D3 | K occurrences of same tag but <K distinct results → reuse best available (current behavior, satisfactory) |
| D4 | Duplicate tag toggle is per-session, script analysis mode only; Direct Tags mode unaffected |
| D5 | Sweep/upscaler/Real-ESRGAN removed entirely; files exported as-is |
| D6 | `realesrgan_path` DB column STAYS (harmless, avoids migration risk); only the test endpoint and `SettingsUpdate` field are removed |
| D7 | Persistent Playwright browser with stateless fallback on any failure |
| D8 | Profile selection in frontend triggers `POST /api/profiles/{id}/adapters/start` — health-checks and launches missing adapters |
| D9 | Docker: one container per adapter (option A) |
| D10 | Missing-tags export (`GET /sessions/{id}/export/missing-tags`) is KEPT — PRD §5.9 intentional feature |
| D11 | Redundant source download: new `NicheProfile.redundant_source_download` boolean (default False); when ON downloads best-1 per source per tag, groups in review |
| D12 | Phase 5 persistent browser uses a dedicated worker thread + job queue per adapter (not a lock-guarded shared Browser). Playwright's sync API pins a Browser/Context to its launching thread — a lock only serializes access, it doesn't force same-thread execution, so a shared-Browser-with-lock design would still crash under Flask's `threaded=True` with `greenlet.error: cannot switch to a different thread`. One background thread now owns the browser exclusively; request threads submit jobs via a queue and block on a `concurrent.futures.Future`. All three adapters use this identical pattern. |

---

## Open Questions — ALL RESOLVED

| # | Question | Resolution |
|---|----------|------------|
| OQ1 | Redundant source download: how many per source per tag — best 1 or configurable N? | **Best 1 per source.** Confirmed. |
| OQ2 | When redundant mode ON and user keeps multiple files from same tag, ZIP numbering? | **Sequential across all kept items** — existing ZIP numbering already handles this correctly since results share `tag_occurrence_index` and Python's sort is stable. No `export.py` change needed. Confirmed. |
| OQ3 | Adapter script path for auto-launch: stored in source's `config` JSON as `adapter_script_path`? | **Yes — `MediaSource.config.adapter_script_path` JSON key.** No DB migration needed. Confirmed. |
| OQ4 | Adapter fails to start after 10s timeout: block session setup or warning-only? | **Warning-only, non-blocking.** Confirmed. |

---

## Critical Technical Facts

### In-memory sessions
`app.state.sessions` is the only source-of-truth for in-flight sessions. Nothing is DB-persisted between requests. SSE generators read directly from this dict — writing to `sess` fields from `run_downloads` is safe because both run on the same asyncio event loop (no thread races).

### Sweep/upscaler was already dead before Phase 1, and stitcher/upscaler are now deleted
The PRD (§5.7–5.8) describes a pre-export sweep with Real-ESRGAN/lanczos upscaling and ffmpeg video stitching. This entire subsystem was removed in Phase 1 per user request ("images/gifs/videos should stay untouched") — `stitcher.py` and `upscaler.py` no longer exist, and the export flow is ZIP-only (standard + VideoStitch naming variants). **The bundled `BROLL_ENGINE_PRD.md` is now stale on this point** — do not use it as a source of truth for current export/stitching behavior; use `docs/USER_GUIDE.md` and the actual `backend/routers/export.py` instead.

### All three adapters use sync Playwright (corrected)
`40k_adapter.py`, `artvee_adapter.py`, and `loc_adapter.py` all use `playwright.sync_api`. An earlier assumption in planning docs that `artvee_adapter.py` used `async_playwright` was checked and found false before any code was written against it — see D12.

### Dedupe flag flow (Phase 3)
`allow_duplicate_tags` (frontend param) is inverted from `dedupe_repeat_tags` (backend field):
- `allow_duplicate_tags=True` → `dedupe_repeat_tags=False`
- `allow_duplicate_tags=False` → `dedupe_repeat_tags=True`
- `allow_duplicate_tags` omitted → use `profile.dedupe_repeat_tags`

The downloader reads the effective per-session value `sess.dedupe_repeat_tags` (set once at session creation), not `profile.dedupe_repeat_tags` directly.

### Persistent browser threading
The `_browser_lock` guards only the initial browser launch (one-time). Concurrent `browser.new_context()` calls are safe without a lock — contexts are Playwright's isolation boundary. See `docs/CUSTOM_ADAPTER_GUIDE.md` §10 for the full pattern, written up for anyone adding a new Playwright-based adapter.

### Docker URL problem
In Docker, `localhost:3000` won't resolve to another container. DB source configs need container-name URLs (`http://adapter-wh40k:3000`, etc.) for Docker deployments. Documented in `DOCKER_SETUP.md`.

### Port discovery for adapter auto-launch
Adapter ports (3000, 3001, 3002) are hardcoded in each adapter's `PORT` constant. Auto-launch discovers the port from `adapter_url` in the DB source config — it is not hardcoded in `profiles.py`.

### Redundant source download vs. multi_item_per_tag
`multi_item_per_tag=True` means "return 1 top-quality result globally across all sources" (random among ties). `multi_item_per_tag=False` means "return all candidates, sorted by quality." `redundant_source_download=True` is a third mode that overrides both — it downloads the best-1 result from *every enabled source* for each tag, and the review UI groups results by tag so the user can pick which source's result(s) to keep.

### Per-source rate-limit delay
`MediaSource.request_delay_seconds` (added after the original PRD, not documented there): `NULL` → random 2–30s delay between consecutive requests to that source; `0` → no delay; `N > 0` → fixed N-second minimum gap. `local_folder` sources are always skipped (no network call). Configurable per-source in the Sources UI.

### Direct Tag List session mode
`POST /api/sessions/from-tags` (not in the original PRD's API route list) creates a session directly from a user-typed tag list, bypassing script analysis (algorithmic/LLM) entirely. The session enters `awaiting_review` immediately. This exists alongside the script-analysis flow (`POST /api/sessions`) as a toggle in the Dashboard's Step 1 UI ("Script Analysis" vs. "Direct Tag List").

---

## Key File Locations

```
D:\yt_vids\automation ecosystem\BRollGen\
├── backend/
│   ├── main.py                          # FastAPI app, uvicorn port 7420, lifespan startup, adapter_processes dict
│   ├── session_state.py                 # Session, Tag, DownloadResult dataclasses (in-memory)
│   ├── routers/
│   │   ├── export.py                    # ZIP export (standard + VideoStitch), missing-tags export
│   │   ├── sessions.py                  # Session CRUD, from-tags bypass, SSE progress stream, curation
│   │   ├── settings.py                  # App settings, LLM providers, global tags + CSV/TXT import
│   │   ├── profiles.py                  # NicheProfile CRUD, tags, source links, adapters/start (Phase 6)
│   │   ├── sources.py                   # MediaSource CRUD, test endpoint
│   │   ├── uploads.py                   # local_folder + adapter-script file uploads (post-handoff)
│   │   ├── local_library.py             # Local folder browsing + tagging API
│   │   ├── preview.py                   # Serves tmp media files for preview
│   │   └── docs.py                      # Serves CUSTOM_ADAPTER_GUIDE.md as plain text at /docs/adapter
│   ├── services/
│   │   ├── downloader.py                # Core download logic, run_downloads(), redundant-mode branch
│   │   ├── analyzer.py                  # Tag extraction pipeline, extract_tags()
│   │   └── source_adapters/             # base.py, pexels.py, pixabay.py, unsplash.py, serp_scraper.py,
│   │                                     # custom_adapter.py, local_folder.py
│   └── db/
│       ├── models.py                    # SQLAlchemy models (AppSettings, NicheProfile, MediaSource, etc.)
│       └── database.py                  # Engine/session setup; DB_PATH resolves to project-root broll_engine.db
├── alembic/versions/                    # 001_initial_schema, 002_source_request_delay, 003_redundant_source_download,
│                                         # 004_drop_profile_video_fields
├── local_libraries/                     # gitignored — uploaded local_folder source media (backend/routers/uploads.py)
├── CustomAdapters/uploaded/              # gitignored — uploaded custom_adapter .py scripts (backend/routers/uploads.py)
├── frontend/src/
│   ├── api.js                           # All API calls
│   ├── components/
│   │   └── Dropzone.jsx                 # Shared drag-and-drop/browse upload widget (used by Sources.jsx + LocalLibrary.jsx)
│   └── pages/
│       ├── Dashboard.jsx                # Main workflow UI (StepSetup, StepTags, StepDownload, StepCuration, StepExport)
│       ├── Profiles.jsx                 # Profile editor incl. redundant_source_download toggle
│       ├── Sources.jsx                  # Source config incl. adapter_script_path field
│       ├── Settings.jsx                 # LLM providers, global tags, app paths
│       ├── LocalLibrary.jsx             # Local folder library: source picker → preview → tag/delete controls → file card grid → upload
│       └── AdapterDocs.jsx              # Renders the adapter guide in-app
├── CustomAdapters/wh40k/
│   ├── 40k_adapter.py                   # Flask, port 3000, persistent sync Playwright
│   ├── artvee_adapter.py                # Flask, port 3001, persistent sync Playwright
│   ├── loc_adapter.py                   # Flask, port 3002, persistent sync Playwright
│   ├── Dockerfile                       # Parameterized by ADAPTER_SCRIPT build arg
│   └── tests/test_persistent_browser.py # 21 tests
├── docs/
│   ├── implementation/                  # All phase plans + GATELOG.md
│   ├── CUSTOM_ADAPTER_GUIDE.md          # Adapter protocol + persistent-browser pattern + Docker packaging
│   └── USER_GUIDE.md                    # Comprehensive end-user guide
├── Dockerfile                           # Main app image
├── docker-compose.yml                   # app + 3 adapter containers
├── DOCKER_SETUP.md                      # Docker deployment notes (volume paths, URL swap)
├── BROLL_ENGINE_PRD.md                  # Original PRD reference — stale re: stitcher/upscaler (see above)
└── start.bat                            # Local dev/prod launcher: migrate → build frontend → uvicorn
```

---

## Test Commands Per Phase

```bat
REM Phase 1
cd /d "D:\yt_vids\automation ecosystem\BRollGen\backend"
python -m pytest tests/phase_01/ -v --tb=short 2>&1

REM Phase 2
python -m pytest tests/phase_02/ -v --tb=short 2>&1

REM Phase 3
python -m pytest tests/phase_03/ -v --tb=short 2>&1

REM Phase 4
python -m pytest tests/phase_04/ -v --tb=short 2>&1

REM Phase 5 (adapters must be running first)
cd /d "D:\yt_vids\automation ecosystem\BRollGen\CustomAdapters\wh40k"
python -m pytest tests/test_persistent_browser.py -v --tb=short 2>&1

REM Phase 6
cd /d "D:\yt_vids\automation ecosystem\BRollGen\backend"
python -m pytest tests/phase_06/ -v --tb=short 2>&1
```

All of the above have been run by the user and confirmed green (16/16, 10/10 [9/9 in the actual run], 11/11, 21/21, 14/14 respectively — see Phase Status table).

---

## Docker (Phase 6 Part C) — Confirmed Live

`Dockerfile` (main app), `CustomAdapters/wh40k/Dockerfile` (adapters, parameterized by `ADAPTER_SCRIPT`), and `docker-compose.yml` (4 services: app + 3 adapters) are all written, reviewed, and confirmed working via a live `docker-compose build && docker-compose up` run — all 4 containers built and came up healthy. See `DOCKER_SETUP.md` for the exact commands and the required `adapter_url` swap (`localhost` → Compose service name) before searches/downloads will actually reach the adapters from inside the `app` container.

Bugs found and fixed during the live verification pass (all documented in more detail in GATELOG's Crucial Technical Facts):
1. `CustomAdapters/wh40k/requirements.txt` never listed `playwright` itself (only `flask`/`requests`/`beautifulsoup4`/`pytest`) — invisible locally because the dev venv is built from the project-root `requirements.txt` instead, which does pin it. Fixed by adding `playwright==1.47.0` to the adapter's own `requirements.txt`.
2. `python:3.11-slim` is an unpinned tag that now resolves to Debian 13 ("trixie"), which Playwright's `install-deps` doesn't officially support (`ttf-ubuntu-font-family`/`ttf-unifont` don't exist in trixie's repos). Fixed by pinning both `Dockerfile`s to `python:3.11-slim-bookworm`.
3. The main app's `Dockerfile` `pip install`ed `playwright` but never ran `playwright install chromium`, so `serp_scraper.py`'s Playwright fallback would have silently returned zero results in Docker. Fixed by adding `RUN playwright install --with-deps chromium`.
4. The port conflict seen during `docker-compose up` (`Bind for 0.0.0.0:3000 failed: port is already allocated`) was environmental, not a code bug — an unrelated container from a different project (`talking-head-animation-makerv01-app`) was already bound to host port 3000. Resolved by `docker stop`ping it; no project files needed to change.

---

## Security Note

`# SECURITY: api_key stored as plain text in v1 — encrypt in v2` — this comment exists in the codebase (`backend/db/models.py`, `LLMProvider.api_key`). Do not change the storage mechanism. Encryption is deferred to v2.
