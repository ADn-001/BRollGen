# B-Roll Engine — Gate Log

**Last updated:** 2026-08-14  
**Tracking:** 6 implementation phases

---

## Phase Status

| Phase | Title | Status | Gate |
|-------|-------|--------|------|
| 1 | Remove Stitcher / Upscaler | **COMPLETE** | 16/16 tests green |
| 2 | VideoStitch Export + Adaptive Naming | **COMPLETE** | 10/10 tests green |
| 3 | Duplicate Tags Session Toggle | **COMPLETE** | 9/9 tests green |
| 4 | Real-Time Progress Bar (per-item text) | **COMPLETE** | 11/11 tests green |
| 5 | Persistent Playwright Browser in Adapters | **COMPLETE** | 21/21 tests green |
| 6 | Adapter Lifecycle + Redundant Source Download + Docker | **COMPLETE** — Parts A+B: 14/14 tests green, migration 003 applied. Part C: `docker-compose up` confirmed live — all 4 containers (app + 3 adapters) build and run healthy | — |

---

## Design Decisions (Locked)

| # | Decision | Rationale |
|---|----------|-----------|
| D1 | Existing ZIP export keeps `001_` zero-padded naming unchanged | User confirmed: normal ZIP stays as-is |
| D2 | New "Export for VideoStitch" button exports with no-zero-padding (`1_`, `10_`, `100_`) | VideoStitch app expects this format |
| D3 | When K occurrences of same tag but < K distinct results: reuse best available (current behavior) | User confirmed: change #2 (guarantee distinct) is NOT required |
| D4 | Duplicate tag toggle is per-session in script analysis mode only; Direct Tags mode is unaffected | User request |
| D5 | Sweep / upscaler / Real-ESRGAN removed entirely; files exported as-is from download | User request: "images/gifs/videos should stay untouched" |
| D6 | `realesrgan_path` column stays in DB schema (harmless, avoids migration risk); only the test endpoint and UI are removed | Migration risk not worth it for a dead config key |
| D7 | Persistent Playwright browser with fallback to stateless (fresh browser per call) on any failure | User: "make persistent but add logic to fallback to stateless mode in case there's critical issues or failures" |
| D8 | Profile selection in frontend triggers `POST /api/profiles/{id}/adapters/start` which health-checks adapters and launches any not running | User: "when user picks a profile, it starts all adapters connected to that profile" |
| D9 | Docker: one container per adapter (A option) | User confirmed |
| D10 | Missing-tags export (`GET /sessions/{id}/export/missing-tags`) is KEPT — it is an intentional PRD feature (§5.9), already implemented in frontend curation step | PRD §5.9 documents it explicitly |
| D11 | Redundant source download is a new NicheProfile boolean `redundant_source_download` (default False); when ON, downloads best-1 per source per tag, shows grouped in review | User feature request |
| D12 | Phase 5 persistent browser uses a dedicated worker thread + job queue per adapter (not a lock-guarded shared Browser). Playwright's sync API pins a Browser/Context to its launching thread; a lock only serialises access, it doesn't force same-thread execution, so it would still crash under Flask's default `threaded=True`. `40k_adapter.py`'s own pre-existing comments documented this exact failure mode (`greenlet.error: cannot switch to a different thread`). One background thread now owns the browser exclusively; Flask request threads submit jobs via a queue and block on a `concurrent.futures.Future` | User confirmed after conflict flagged — see corrected fact below |
| D13 | `local_folder` sources' `config.folder_path` is now populated by file upload (`POST /sources/{id}/upload/folder`, storing under app-managed `local_libraries/<source_id>/`) instead of the user typing an existing host path. The manual path text field is removed entirely for this source type | User: broke down under Docker/WSL since the typed path had to exist inside whatever filesystem the backend process runs in; user wanted upload to "accept any folder/files via upload instead of local path input" |
| D14 | Uploaded folders are flattened (subfolder structure discarded) when saved to `local_libraries/<source_id>/` | Matches `services/source_adapters/local_folder.py`'s actual read behavior — a flat, non-recursive directory listing; preserving nested folders would silently break search for anything not at the top level |
| D15 | `custom_adapter` sources' `adapter_script_path` keeps its manual text field AND gains an upload option (`POST /sources/{id}/upload/adapter-script`, saved under `CustomAdapters/uploaded/<source_id>/`) — both set the same config key, neither replaces the other | User explicitly asked for "both" when offered manual-only vs. upload-only |

---

## Open Design Questions — RESOLVED (confirmed by user before Phase 6 code)

| # | Question | Resolution |
|---|----------|------------|
| OQ1 | Redundant source download: how many items downloaded per source per tag — best 1, or configurable N? | **Best 1 per source.** Confirmed. |
| OQ2 | When redundant source download is ON and user keeps multiple files from same tag, how are they numbered in the ZIPs? | **Sequential across all kept items** (`1_emperor.jpg`, `2_emperor.jpg`, `3_space_marine.jpg`) — no export.py change needed, existing ZIP numbering already does this since results share the same `tag_occurrence_index` and Python's sort is stable. Confirmed. |
| OQ3 | Adapter script path for auto-launch: should it be stored in the source's `config` JSON (`adapter_script_path` key) and editable in the Sources UI? Or managed differently? | **`MediaSource.config.adapter_script_path` JSON key.** No DB migration needed. Confirmed. |
| OQ4 | When adapter fails to start after 10s health-check timeout: should the session setup be blocked, or is it a warning-only (user can proceed)? | **Warning-only, non-blocking.** Confirmed. |

---

## Crucial Discovered Facts

- **`app.state.sessions`** is the only source-of-truth for in-flight sessions. Nothing is DB-persisted. SSE generators read directly from this dict — writing to `sess` fields from `run_downloads` is safe because both run on the same asyncio event loop (no thread races).
- **`multi_item_per_tag=True`** currently means "return 1 random top-quality result globally across all sources." When False: return all candidates sorted by quality. The new `redundant_source_download` flag is a third mode that overrides both.
- **The pre-export sweep (`/sweep`) is NEVER called from the current frontend.** `triggerSweep` is in `api.js` but not imported or used in `Dashboard.jsx`. The sweep was a dead feature in the UI even before this change request.
- **`export.py` ZIP route checks for `_processed` file variants** (from upscaler) before writing each item. After Phase 1, this logic must be stripped — just write the original `item.file_path` directly.
- **`session_state.py` `DownloadResult.needs_upscale` and `upscale_applied`** are referenced nowhere in the frontend (they're in `_result_dict` but the UI doesn't render them). Safe to remove.
- **`settings.py` `SettingsUpdate` Pydantic model includes `realesrgan_path`** — this field should be removed from the model and the `PUT /settings` update logic so it can no longer be set. The column stays in the DB.
- **Adapter port numbers** (3000, 3001, 3002) are hardcoded in each adapter file's `PORT` constant and presumably in DB source configs. Auto-launch must discover the port from the `adapter_url` in DB config, not assume a port.
- **`sess.dedupe_repeat_tags`** does not currently exist on the `Session` dataclass. Phase 3 adds it. The downloader currently reads `profile.dedupe_repeat_tags` directly — Phase 3 changes it to read `sess.dedupe_repeat_tags` (the effective per-session value).
- **`_fetch_html` in all 3 adapters** currently runs the full Playwright boot/teardown per call. The persistent browser shares the `Browser` object across Flask threads; each thread gets its own `BrowserContext` (Playwright's isolation boundary). The `_browser_lock` guards only the initial launch — concurrent `new_context()` calls are safe without a lock.
- **CORRECTED (was wrong in this file since Phase 5 planning):** `artvee_adapter.py` uses **sync** Playwright (`from playwright.sync_api import sync_playwright`), identical to the other two adapters — it does NOT use `async_playwright`. All three adapters share the same persistence architecture (dedicated worker thread + job queue); no async-event-loop-in-thread special case was needed.
- **`artvee_adapter.py`'s download flow must navigate the artwork page AND fetch the signed S3 URL through the same Playwright context** (a separate `requests.get()` on the S3 URL gets 403'd — the signature covers the Host header). Phase 5's persistent-browser job queue therefore submits whole task functions (`task_fn(browser) -> result`), not bare URLs, so `_fetch_artwork_and_download_with_browser` can run the full navigate+download sequence atomically inside one job.
- **Testing SSE endpoints (`download_progress_sse`) with `TestClient` deadlocks if the injected session's `status` keeps `event_generator()`'s `while True` loop alive** (e.g. `status="downloading"`). The loop only exits via `request.is_disconnected()`, and `TestClient`'s sync thread-portal teardown can hang indefinitely waiting on that generator. Fix: inject the session with a terminal `status` (e.g. `"awaiting_review"`) so the generator yields exactly one event and returns on its own — no reliance on disconnect detection. Apply this pattern in any future SSE test (Phase 6 adapter/session tests).
- **Path math in test files under `backend/tests/phase_XX/`**: `Path(__file__).parent.parent.parent` from a file at `backend/tests/phase_XX/test_foo.py` already resolves to `backend/`. Do not append another `"backend"` segment when building paths to `backend/services/...` etc. (Phase 4's plan doc had this bug — cost real debugging time. Copy the pattern from `tests/phase_01/test_cleanup.py`, which does it correctly.)
- **Phase 6's plan doc `docker-compose.yml` had two silent path bugs, both fixed during implementation:** `backend/db/database.py` computes `DB_PATH = Path(__file__).parent.parent.parent / "broll_engine.db"` — that's the **project root** (`/app/broll_engine.db` in the container), not `/app/backend/broll.db` as the plan's volume line said (wrong directory AND wrong filename — the actual file is `broll_engine.db`, not `broll.db`). Likewise `main.py`'s `TMP_DIR = PROJECT_ROOT / "tmp"` resolves to `/app/tmp`, not `/app/backend/tmp`. Corrected compose volumes: `./tmp:/app/tmp` and `./broll_engine.db:/app/broll_engine.db`. Also: `alembic.ini`'s `script_location = alembic` is relative to the project root, so the Dockerfile CMD must run `alembic upgrade head` from `/app` before `cd backend && uvicorn ...` — running it from `/app/backend` (as literally written in the plan) would fail to find `alembic.ini`.
- **Docker adapter URLs**: `custom_adapter` sources' `config.adapter_url` must be switched from `http://localhost:PORT` to `http://adapter-<name>:PORT` (the Compose service name) before running under Docker — `localhost` inside the `app` container does not reach sibling containers. Documented in `DOCKER_SETUP.md`. `adapter_script_path` (used for local auto-launch) is irrelevant in Docker — each adapter container runs its script directly via its own Dockerfile `CMD`.
- **Bug found during live Docker verification: `CustomAdapters/wh40k/requirements.txt` never listed `playwright` itself** — only `flask`, `requests`, `beautifulsoup4`, `pytest`. Locally this was invisible because the dev venv is installed from the project-root `requirements.txt` (which does pin `playwright==1.47.0`, for the backend's own `serp_scraper.py` Playwright fallback), and the adapters were always run from that same venv, not from a venv built off their own `requirements.txt`. But `CustomAdapters/wh40k/Dockerfile` installs *only* the adapter's own `requirements.txt` in an isolated image, so `RUN playwright install chromium` failed with `playwright: not found` (exit 127) — pip never installed the `playwright` package, so the CLI didn't exist. Fixed by adding `playwright==1.47.0` to `CustomAdapters/wh40k/requirements.txt` to match the root pin.
- **Bug found during live Docker verification (2nd): `python:3.11-slim` is a moving tag that currently resolves to Debian 13 ("trixie"), which Playwright's `install-deps` does not officially support** — it fails trying to apt-install `ttf-ubuntu-font-family` / `ttf-unifont`, packages that don't exist in trixie's repos (`E: Package '...' has no installation candidate`, exit 100). Fixed by pinning both `Dockerfile` (project root) and `CustomAdapters/wh40k/Dockerfile` to `python:3.11-slim-bookworm` (Debian 12), which Playwright's dependency installer does support, and which won't silently shift under us the way the unpinned `-slim` tag will as Debian's stable release rolls forward.
- **Bug found during live Docker verification (3rd): the main app's `Dockerfile` installed `playwright` via pip but never ran `playwright install chromium`** — so `services/source_adapters/serp_scraper.py`'s Playwright fallback (used whenever a `serp_scraper` source has no `serpapi_key` configured) would silently return zero results in a Docker deployment (caught by its own try/except, logged as a warning, never crashes — so this would have been very easy to miss without noticing suspiciously empty results from that source). Fixed by adding `RUN playwright install --with-deps chromium` to the main `Dockerfile`.
- **`docker-compose up` port conflict was environmental, not a code bug**: an unrelated pre-existing container from a different project (`talking-head-animation-makerv01-app`) was already bound to host port 3000. User stopped it (`docker stop`) and the compose stack came up clean on the next attempt — all 4 containers (app + 3 adapters) built and reported healthy. **Phase 6 is now fully confirmed end-to-end, including Part C.** The `Exception in thread Thread-13 (watch_events): KeyError: 'id'` seen in the `docker-compose up` log output is a known cosmetic bug in the legacy Python-based `docker-compose` v1 CLI's log-printer thread — unrelated to this project, does not affect the running containers.

---

## File Inventory (All Files That Will Be Touched)

### Phase 1
- `backend/services/stitcher.py` — **DELETE**
- `backend/services/upscaler.py` — **DELETE**
- `backend/routers/export.py` — remove video routes, remove `_processed` lookup in ZIP
- `backend/routers/sessions.py` — remove sweep + sweep-progress routes
- `backend/session_state.py` — remove `stitching`/`sweeping` status, remove `needs_upscale`/`upscale_applied` from DownloadResult
- `backend/routers/settings.py` — remove `POST /settings/test-realesrgan`, remove `realesrgan_path` from `SettingsUpdate`
- `backend/main.py` — no change needed (export router stays; stitcher import removed automatically)
- `frontend/src/api.js` — remove `triggerSweep`, `exportVideo`, `downloadVideo`, `testRealesrgan`
- `frontend/src/pages/Dashboard.jsx` — gut `StepExport`: remove video stitch UI, keep ZIP button only

### Phase 2
- `backend/routers/export.py` — add `GET /{session_id}/export/videostitch`
- `frontend/src/api.js` — add `exportVideoStitch`
- `frontend/src/pages/Dashboard.jsx` — add "Export for VideoStitch" button in StepExport

### Phase 3
- `backend/session_state.py` — add `dedupe_repeat_tags: bool` field to `Session`
- `backend/routers/sessions.py` — add `allow_duplicate_tags` to `SessionCreate`; compute effective value; store on sess
- `backend/services/analyzer.py` — accept `dedupe_override` param; use it instead of `profile.dedupe_repeat_tags`
- `backend/services/downloader.py` — read `sess.dedupe_repeat_tags` instead of `profile.dedupe_repeat_tags`
- `frontend/src/pages/Dashboard.jsx` — add toggle in StepSetup script mode; pass to `createSession`

### Phase 4
- `backend/session_state.py` — add `current_item_label: str` and `current_item_index: int` to `Session`
- `backend/services/downloader.py` — write `sess.current_item_label` before each search and download
- `backend/routers/sessions.py` — include `current_item_label` in SSE event JSON
- `frontend/src/pages/Dashboard.jsx` — render label text in StepDownload progress card

### Phase 5
- `CustomAdapters/wh40k/40k_adapter.py` — add persistent browser globals + lock + fallback
- `CustomAdapters/wh40k/artvee_adapter.py` — same (async variant)
- `CustomAdapters/wh40k/loc_adapter.py` — same (sync variant)

### Phase 6
- `backend/db/models.py` — add `redundant_source_download` to `NicheProfile`
- `backend/db/migrations/` — new Alembic migration for `redundant_source_download`
- `backend/routers/profiles.py` — add `POST /{profile_id}/adapters/start`; expose `redundant_source_download` in CRUD
- `backend/routers/sessions.py` — ensure `_session_dict` includes `redundant_source_download`
- `backend/services/downloader.py` — add redundant source download mode
- `backend/routers/sessions.py` — session_dict must surface which items came from which source (for grouping)
- `frontend/src/api.js` — add `startAdapters`
- `frontend/src/pages/Dashboard.jsx` — trigger `startAdapters` on profile select; add grouped curation UI when redundant mode active
- `frontend/src/pages/Profiles.jsx` — add `redundant_source_download` toggle; add `adapter_script_path` to custom_adapter source config UI
- `docker-compose.yml` — new file at project root
- `Dockerfile` — new file at project root (main app)
- `CustomAdapters/wh40k/Dockerfile` — new file (shared for all 3 adapters, parameterised by ADAPTER_SCRIPT)

### Final Documentation Pass (post-Phase-6)
- `docs/CUSTOM_ADAPTER_GUIDE.md` — added auto-launch section (`adapter_script_path`), persistent-browser worker-thread pattern for adapter authors, and a Dockerizing-your-adapter section; renumbered Troubleshooting last
- `instructions.md` — updated Workflow section with final phase-status table; corrected the stale "artvee uses async Playwright" claim (D12); added doc cross-references
- `handoff.md` — full rewrite: status header, phase table, D12 added, OQ1–OQ4 marked resolved, new Critical Technical Facts (stitcher/upscaler removal, sync Playwright correction, rate-limit delay field, from-tags session mode), updated Key File Locations, Docker readiness note. Security note preserved verbatim.
- `docs/USER_GUIDE.md` — new comprehensive end-user guide: setup, full 5-step Dashboard workflow, Sources, Profiles, custom adapter registration, tag extraction pipeline, tag file format, Settings, Local Library, troubleshooting

### Post-Handoff Maintenance Pass (bug fix + user-requested features, after live Docker verification)
- **Fixed: Adapter Docs page 404'd in Docker.** `Dockerfile` never `COPY`'d `docs/` into the image, so `backend/routers/docs.py`'s `GET /api/docs/adapter` had nothing to serve. Added `COPY docs/ ./docs/`.
- **New: file/folder upload replaces host-path text input for `local_folder` sources and augments it for `custom_adapter` script paths (D13–D15).** New `backend/routers/uploads.py` — `POST /sources/{id}/upload/folder` (multi-file, flattened into `local_libraries/<source_id>/`, sets `config.folder_path`), `GET .../upload/folder/status`, `DELETE .../upload/folder` (clear library), `POST /sources/{id}/upload/adapter-script` (single `.py`, saved under `CustomAdapters/uploaded/<source_id>/`, sets `config.adapter_script_path`). Registered in `main.py`. Both upload endpoints require the source to already exist (need its ID for the target folder) — new sources must be saved (name + type only) before the upload areas unlock; `frontend/src/pages/Sources.jsx`'s create flow now stays in the editor after Save instead of closing, specifically so this doesn't force a second navigation round-trip.
- `frontend/src/pages/Sources.jsx` — full rewrite of the local_folder and custom_adapter config panels: new `Dropzone` component (drag-and-drop with recursive `webkitGetAsEntry()` folder traversal + a "Browse Folder…"/"Browse File…" button opening the native OS picker via a hidden `webkitdirectory` or plain file `<input>`), `LocalFolderUploadPanel` (upload + live file count + Clear library), `AdapterScriptUploadPanel` (upload alongside the existing manual path field).
- `frontend/src/api.js` — added `sourcesApi.uploadFolder`, `.folderStatus`, `.clearFolder`, `.uploadAdapterScript`.
- `docker-compose.yml` — added `./local_libraries:/app/local_libraries` and `./CustomAdapters/uploaded:/app/CustomAdapters/uploaded` volume mounts so uploads survive a container restart; `.gitignore` updated to exclude both directories (user media, not source).
- **New: removed dead ffmpeg/Real-ESRGAN UI and the profile fields that only ever fed the removed video-stitching pipeline (D5/D6 superseded).** `frontend/src/pages/Settings.jsx` — removed the ffmpeg Path field, the Real-ESRGAN Binary Path field, and its Test button (which was calling `settingsApi.testRealesrgan`, a function that no longer exists in `api.js` since Phase 1 — clicking it would have thrown). `frontend/src/pages/Profiles.jsx` — removed Output Resolution, Min Resolution, Aspect Fit, and Upscale Method fields and the resolution badge on the profile list card. `backend/db/models.py` — dropped `resolution`, `min_resolution`, `aspect_fit`, `upscale_method` columns from `NicheProfile`. `backend/routers/profiles.py` — removed those fields from `ProfileCreate`/`ProfileUpdate`/`_profile_dict` and the now-empty `VALID_ASPECT_FIT`/`VALID_UPSCALE`/`VALID_RESOLUTIONS` validation constants. New migration `alembic/versions/004_drop_profile_video_fields.py` (`op.batch_alter_table`, required for SQLite column drops) actually removes the columns from the DB — this goes further than D6's original "leave the column, it's harmless" call for `realesrgan_path` (which still stands — that column is on `app_settings`, not `niche_profiles`, and wasn't touched).
- No automated tests were written for this maintenance pass (ad-hoc bug-fix/feature work between phases, not a new gated phase) — manual verification via the running app is the acceptance path here.

### Local Library page redesign (post-handoff, user-requested)
- **Problem:** the old `/library` page was a rudimentary two-panel layout (source dropdown + paginated file list on the left, viewer/tag editor on the right) with no working preview, no delete capability, and pagination that made it awkward to browse a library of any size.
- **New: full single-flow redesign per user spec.** `frontend/src/pages/LocalLibrary.jsx` — full rewrite, top-to-bottom: (1) source picker, (2) central preview (`<img>` for images/GIFs, `<video controls autoPlay loop>` for video), (3) controls directly under the preview — ← Prev / Next → to cycle sequentially, the tag chip editor + Quality Grade picker, a **Save Tagged Name** button, and a **Delete** button for the selected file, (4) a `flex flex-wrap` grid of every file as small cards (70%-height thumbnail, remaining strip holds filename + a small red ✕ delete button — clicking a card loads it into the preview above), (5) an upload area at the bottom (reuses the shared `Dropzone`) to add more files to the currently selected library without leaving the page. Fetches the full file list in one pass (`fetchAllLibraryFiles`, pages through the existing paginated endpoint at `page_size=200` internally) instead of paginating the UI, since the whole point of the new layout is scrollable/browsable cards.
- **New: `DELETE /api/library/{source_id}/files/{filename}` endpoint.** `backend/routers/local_library.py` — new `_safe_file_path()` helper (resolves the target path and rejects anything that escapes the source folder via `Path.relative_to()`, mirroring the existing traversal-safety pattern in `preview.py`) backing a new `delete_file()` route that removes the media file and its sidecar `.json` (if any), used by both the per-card ✕ and the under-preview Delete button.
- **New: shared `Dropzone` component.** `frontend/src/components/Dropzone.jsx` — extracted the drag-and-drop folder-walking logic (`filesFromDataTransfer`, recursive `webkitGetAsEntry()` traversal) and the `Dropzone` component itself out of `Sources.jsx` (where they were previously defined inline) so `LocalLibrary.jsx`'s bottom upload area can reuse them without duplication. `Sources.jsx` now imports `Dropzone` from the shared component instead of defining it locally — behavior is unchanged, this is a pure extraction.
- `frontend/src/api.js` — added `libraryApi.deleteFile(sourceId, filename)`.
- No DB/migration changes — the delete endpoint needs no schema change. Backend does need a restart to pick up the new router code; frontend needs a rebuild (`npm run build`) since this is all React/JSX.
- No automated tests were written for this pass either — manual verification via the running app (upload a folder, tag/preview/cycle/delete files, confirm sidecar writes and traversal-safe deletes) is the acceptance path.

### Local Library folder-detection bug fix + Download Folder + Niche Profile tag buttons (post-handoff, user-reported/requested)
- **Fixed: Library page reported "no files" for a source whose Sources-page upload panel showed the correct file count.** Root-caused by reading `broll_engine.db` directly — two independent config bugs, both now fixed generically rather than patched by hand in the DB:
  1. `local_library.py`'s `list_files` did `cfg.get("enabled_extensions", <default set>)`, which only falls back when the *key* is missing — an explicitly-empty `[]` (the Sources page's Enabled Extensions field saved blank) was taken as "match nothing" instead of "no restriction". Changed to `cfg.get("enabled_extensions") or <default set>`, matching how `services/source_adapters/local_folder.py` already treated it at actual search time.
  2. `config.folder_path` can go stale — captured as a Docker-container path (`/app/local_libraries/<id>`) from an earlier docker-compose run, or wiped back to `{}` because `Sources.jsx`'s `LocalFolderUploadPanel` never synced the server-written path into its own form state, so a later Save re-submitted the pre-upload config. Added `_resolve_library_folder()` to `local_library.py`, used by every route in that file (`list_files`, `get_file_metadata`, `save_file_tags`, `delete_file`, `preview_library_file`, `list_local_sources`, and the new `download_library_folder`): prefers the canonical `local_libraries/<source_id>/` directory (the only place uploads ever write to) over the cached config value, self-healing both bad sources in the live DB without a migration. Same fix applied to `sources.py`'s Test Connection `local_folder` check. `Sources.jsx`'s `LocalFolderUploadPanel` now also takes an `onFolderPathChange` callback (wired to `set('folder_path', ...)` in `ConfigFields`) so a successful upload syncs into local form state immediately, preventing the clobber-on-next-Save case going forward.
- **New: Download Folder button.** New `GET /api/library/{source_id}/download` (`local_library.py`) streams a ZIP of every media file currently in the library (current, already tag-renamed filenames; sidecar `.json` files excluded — the tags travel via the filename) via `StreamingResponse` + in-memory `zipfile.ZipFile`. `frontend/src/api.js` — added `libraryApi.downloadFolderUrl(sourceId)`. `LocalLibrary.jsx` — new `<a download>` button at the very bottom of the page (below the upload area), disabled when the library is empty, following the same `href`-to-a-`/api/...` route pattern already used by session ZIP export in `Dashboard.jsx`.
- **New: Niche Profile tag buttons in the tagger.** `LocalLibrary.jsx` — new **Niche Profile** dropdown (lists every `NicheProfile` via the existing `profilesApi.list()`) in the tagger controls, between the tag chips row and the free-text tag input. Selecting a profile fetches its tags (`profilesApi.listTags(id)`) and renders them as a `flex flex-wrap` row of buttons, one per tag word — clicking a button toggles that word on/off the selected file's tag list (`toggleProfileTag`), same effect as the free-text box + chip ✕ but one click instead of typing. The free-text box remains as the explicit fallback for words not in the selected profile's list. No backend or schema changes — this only reads the existing `ProfileTag.word` field (there's no separate tag-type/category concept in the data model; each button is simply titled with its tag word, confirmed with the user before implementing).
- No automated tests were written for this pass — manual verification via the running app (re-tested against the two real broken sources in the live `broll_engine.db`) is the acceptance path.

### Delete-source now cleans up its uploaded folder (post-handoff, user-reported)
- **Problem:** `DELETE /sources/{id}` (`sources.py`) only ever removed the `MediaSource` row and its `ProfileSourceLink` rows — it never touched the filesystem. A deleted Local Folder source's entire media library (and a deleted Custom Adapter source's uploaded `.py` script) stayed on disk forever, orphaned with nothing left pointing at it.
- **Fixed:** `delete_source()` now removes the DB row first (so a filesystem hiccup can never block the actual deletion), then best-effort `shutil.rmtree()`s the source's `<id>`-keyed directory under both `local_libraries/` and `CustomAdapters/uploaded/` (whichever applies — the other simply doesn't exist and is skipped) — the same two locations `uploads.py` writes to. A file locked by another process logs a warning instead of raising, so a stray open file can't turn a successful delete into a 500.
- No DB/migration changes, no frontend changes — this is backend-only cleanup logic. Backend needs a restart to pick it up.
- `docs/USER_GUIDE.md` §3 — added a note documenting this behavior, plus a tip that **Clear library** before re-uploading is the way to get a clean replace instead of the existing merge-on-reupload behavior.
- No automated tests were written for this pass — manual verification (delete a Local Folder source with uploaded files, confirm `local_libraries/<id>/` is gone) is the acceptance path.

### Docker deployment verified, then torn down in favor of local adapter testing (operational, no code change)
- User ran a real WH40k-profile session against a live `docker-compose up` deployment; it hit the `localhost`-vs-Compose-service-name issue described in `DOCKER_SETUP.md`'s "Adapter URLs" section (config not yet updated for that specific source) — diagnosed by reading `broll_engine.db` directly rather than guessing, confirming `media_sources.config.adapter_url` was still `http://localhost:3000` for the `wh40k` source. This is expected/documented Docker behavior, not a bug.
- Decision: tear down Docker (`docker-compose down --rmi all -v --remove-orphans`, plus a manual `docker rmi` of unrelated leftover images from other local projects) and switch to native `start.bat` runs for adapter development — faster iteration, no image rebuild per Python change. Docker remains the intended path for eventual VPS deployment; nothing in `docker-compose.yml`/`Dockerfile` changed, so it's reproducible later as-is.
- Running natively surfaced a second, unrelated issue: `frontend/npm run build` failed with `'vite' is not recognized` because `frontend/node_modules` had been installed from within WSL earlier in the project's history, and native-Windows npm packages ship different platform-specific binaries (esbuild/rollup) than WSL/Linux ones — fixed by reinstalling `frontend/node_modules` from a native Windows shell.
- A third issue on the `wh40k` custom_adapter source: **Test Connection never launches an adapter** — it's a plain health-check GET, distinct from the auto-launch that only fires when a profile is selected on the Dashboard (`POST /profiles/{id}/adapters/start`). With `config.adapter_script_path` unset, auto-launch had nothing to launch and silently logged `not_running` (by design — adapter start failures never block session setup, per OQ4). Resolved by uploading `40k_adapter.py` via the Sources page's Adapter Script Path upload panel; confirmed working by running the script manually first (surfaces real startup errors immediately, unlike a failed/timed-out auto-launch) before re-testing.
- No code changes resulted from this pass — purely operational diagnosis and configuration. Documented for future reference: `DOCKER_SETUP.md` (current status note, docker-compose v1 recreate-bug workaround, full-teardown command) and `docs/USER_GUIDE.md` §11 (Test-Connection-doesn't-launch and localhost-vs-Docker-URL troubleshooting entries).

### LLM prompt improvements + niche profile description injection (change request, COMPLETE)
- **`backend/services/analyzer.py` — `_build_llm_prompt()` rewritten.** New signature adds `profile_description: str | None = None`. Conditionally injects a `[NICHE CONTEXT]` block (only when `profile.description` is truthy) positioned between `[TASK]` and `[NICHE PROFILE WORD LIST]`, with a one-line disambiguation directive. When both `profile.description` and `profile_tags` are present, the wordlist parenthetical note adds one sentence identifying them as drawn from the same niche. Other prompt improvements applied in the same edit: (1) task description now states the use case ("stock image and video databases") so the model self-filters for searchability; (2) wordlist priority instruction changed from "always include if script mentions it" to "prioritize even in paraphrased/related form"; (3) output format section now requires "valid JSON parseable by Python's json.loads()"; (4) constraints section adds a bad-tag avoidance directive with generic LLM-padding examples ("journey", "struggle", "future", "world").
- **Call site in `extract_tags()`** updated to pass `profile.description` as the fifth argument.
- No DB changes, no migration, no frontend changes, no new tests (change is prompt-text only — regression-testable only by LLM output quality).

### First push to GitHub remote, tagged v1.0.0
- Pushed the project to `https://github.com/ADn-001/BRollGen.git` for the first time and tagged the resulting commit `v1.0.0` — see `handoff.md`'s Status header for what's included as of this tag.
- Added a small `.gitignore` addition (`bin/`, `ffmpeg-*/`, `ffmpeg-*.7z`, `.pytest_cache/`) to keep ~1GB of unused third-party ffmpeg binaries (leftover from the removed video pipeline, and individually over GitHub's 100MB per-file limit) out of the repo — `*.db` was already ignored, so `broll_engine.db` (which holds real API keys in plaintext, per its documented v1 security note) was never at risk of being committed. Confirmed via a repo-wide secret-pattern grep that nothing else tracked contains a hardcoded key.

### Phase 7 — Openverse adapter consolidation (COMPLETE)
- **Problem:** the LOC adapter scraped the Library of Congress and was defeated by Cloudflare Turnstile anti-scraping. Pivot to the Openverse API (600M+ openly licensed images) with adapters for different sources. The Flickr API was recently paywalled, so LOC / British Library images are reached through Openverse's `source=flickr` aggregate — Openverse has no `loc`/`british` source slug (verified against the live API).
- **Adapter set (final, per user):** 40k (3000, unchanged), artvee (3001, unchanged), Wikimedia Commons (3002, Openverse `source=wikimedia`), NASA (3003, Openverse `source=nasa`), All Openverse (3005, no source filter). Port 3004 freed.
- **Deleted:** `europeana_adapter.py`, `loc_adapter.py`, `britlib_adapter.py`, `flickr_commons_adapter.py`, `flickr_base.py`, plus stale debug artifacts `4.12.0`, `search_dump.html`, `test.txt`, `loc_debug.py`, `loc_browser_profile/`.
- **`openverse_base.py` fixes:** (1) `download_url` built from the request's Host header instead of hardcoded `localhost:<port>` — fixes downloads under Docker; (2) `openverse_search` now paginates (anonymous `page_size` caps at 20, so `limit=50` previously returned 20); (3) User-Agent added to search + download requests; (4) `_get_credentials()` guarded with `has_request_context()` — each adapter's `__main__` banner calls `is_authenticated()` outside a request context, which crashed startup with `RuntimeError: Working outside of request context` (latent since the adapters were written); (5) `_load_env_file()` reads `.env` from the adapter dir or repo root at import, never overriding real env vars.
- **Credentials:** new `.env.example` + `.gitignore` exception (`!.env.example`); the real `.env` (gitignored) holds `OPENVERSE_CLIENT_ID` / `OPENVERSE_CLIENT_SECRET`. A `client_id:client_secret` Auth Token in the Sources UI wins over `.env`. The registration dump `openversetoken.txt` (contained a live `client_secret`) was added to `.gitignore`.
- **No DB changes in this phase** — the adapters are source-agnostic and reusable across profiles; the user wires sources and profile links through the Sources UI per profile.
- **Scripts/Docker:** `start_adapters.bat` and `install_adapters.bat` updated to the 5-adapter set; wh40k `Dockerfile` now `COPY`s `openverse_base.py` alongside the entrypoint (the Openverse adapters import it as a sibling module); `docker-compose.yml` replaces `adapter-loc` with `adapter-wikimedia`/`adapter-nasa`/`adapter-openverse` and updates `app.depends_on`. `stop.bat` (untracked) dropped its dead port-3004 line.
- **Tests:** `tests/test_persistent_browser.py` narrowed to the two Playwright adapters (40k/artvee); new `tests/test_openverse_adapters.py` (health, well-formed results, anonymous pagination ≥20 of 50, real image download, `media_type=video` empty). Result: **15/15 passed** on first full run. A re-run minutes later failed every search test with 502 because Openverse's Cloudflare layer returned HTTP 429 to this IP after the anonymous burst — transient/rate-limiting, not a code issue (noted in the test file's docstring; clears on cooldown or with authenticated requests).
- **Docs:** `docs/CUSTOM_ADAPTER_GUIDE.md` — new §11 "Bundled Openverse API Adapters" (inventory, LOC/BritLib via `source=flickr`, auth via `.env` or Auth Token, Docker notes), Docker/Troubleshooting renumbered to §12/§13, Playwright section corrected to "two bundled adapters". `docs/implementation/phase_07_openverse_adapters.md` — full plan + setup instructions.
