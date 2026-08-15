# B-Roll Engine — Product Requirements Document
**Version:** 2.0 — updated to match the shipped app
**Target Agent:** Claude Code
**Platform:** Windows, local web server (browser UI); also deployable via Docker (see §11)
**Status:** Shipped as `v1.0.0` on GitHub. This document describes the app as actually built, not the original plan — several V1-scope items below were descoped or redesigned during implementation. See §0 for exactly what changed and why.

---

## 0. Changes From the Original V1.1 Plan

The original plan (preserved in Git history as `BROLL_ENGINE_PRD.md` v1.1, and in `docs/implementation/GATELOG.md`) specified an end-to-end pipeline that stitched downloaded media into a finished `.mp4` using ffmpeg, with optional Real-ESRGAN upscaling. That pipeline was fully built, then **removed** during a post-handoff maintenance pass once real usage showed the actual workflow was: download and curate B-roll, then hand it off to an external editor. The video-stitching/upscaling machinery added complexity (ffmpeg dependency management, Real-ESRGAN binary detection, resolution/aspect-fit config per profile) that nothing in the real workflow used. Rather than leave it half-supported, it was cut entirely, and the export step was replaced with two ZIP download modes instead.

Everything below reflects the current, shipped behavior. Where this document differs from v1.1:

- **No video stitching, no upscaling, no aspect-fit normalization.** `stitcher.py`, `upscaler.py`, the `bin/ffmpeg.exe` bundling, the four `black_bg_*` assets, and the `NicheProfile.resolution` / `min_resolution` / `aspect_fit` / `upscale_method` columns are all gone (dropped via Alembic migration `004`). Export is ZIP-only (§5.7 Step 5, §6).
- **Local Folder and Custom Adapter sources are configured by upload, not typed host paths.** A `local_folder` source's media is uploaded through the browser (drag-and-drop or a folder picker) into app-managed storage; a `custom_adapter` source's launch script can likewise be uploaded instead of typed. See §5.4.
- **The Local Library tagger (`/library`) was fully redesigned** into a single top-to-bottom flow with a working preview, Niche Profile quick-tag buttons, per-file delete, and a "Download Folder" export — see §5.6, which replaces the original two-panel spec entirely.
- **Custom adapters have a lifecycle**, not just a URL: an optional uploaded/typed launch script lets the app auto-start the adapter process when its profile is selected (§5.5).
- **Redundant Source Download** was added as a per-profile toggle: downloads one best-1 result from *every* enabled source per tag (instead of one globally-best pick), with a grouped review UI (§5.1, §5.7).
- **Docker deployment** was added as a first-class, verified deployment path alongside native Windows (§11).
- Deleting a source now cleans up its app-managed upload directory instead of leaving it orphaned on disk (§5.4).

---

## 1. Product Overview

B-Roll Engine is a locally-hosted web application that accepts a video script (or a plain tag list) as input, analyzes it to extract searchable tags, searches configured media sources (online stock APIs, web scrapers, custom scraper adapters, and your own local media folders) for matching images and videos, and lets the user curate and download the results as B-roll footage — all without requiring cloud storage or user accounts. The app does not edit or assemble a finished video; it produces a curated, downloadable set of media files (as a ZIP) for use in whatever editing workflow the user already has.

The app runs as a local Python server (backend) with a React frontend served from the same process. The user opens it in their browser. Session state (script, extracted tags, download progress, curation choices) lives in memory for the duration of a session and in a per-session `tmp/<session_id>/` folder; persistent configuration (profiles, sources, tag lists, LLM settings) lives in SQLite. Orphaned tmp folders older than 24h are swept on startup.

---

## 2. Tech Stack

### Backend
- **Python 3.10+** with **FastAPI** (async; download progress streams via Server-Sent Events, not WebSocket)
- **Playwright** (sync, persistent-browser pattern — see §5.5) for headless scraping, used both by the built-in SerpAPI-less Google Images fallback and by custom scraper adapters
- **spaCy** (`en_core_web_sm`) for NLP-based tag extraction (algorithmic fallback)
- **rapidfuzz** for fuzzy tag matching against profile/global wordlists
- **Pillow** — available for image metadata reading; no longer load-bearing for an upscale pipeline (removed)
- **SQLite** via **SQLAlchemy** (sync ORM) with **Alembic** migrations, for persistent config: profiles, sources, word lists, LLM settings — not session data
- **httpx** for async HTTP calls to online APIs, custom adapters, and LLM providers
- **yt-dlp** — listed as a dependency for potential video-source downloading; not required by any currently shipped source adapter
- Server-Sent Events (`GET /api/sessions/{id}/progress`) for real-time download progress, via a plain async generator — no separate task queue library

Two dependencies remain in `requirements.txt` from the original plan but are no longer used by shipped code, and are candidates for removal in a future cleanup: `ffmpeg-python` (the stitching pipeline it backed was removed) and any Real-ESRGAN integration (never had a Python dependency of its own — it shelled out to a user-supplied binary that no longer has a caller).

### Frontend
- **React 18** with **Vite**, dev-proxied through FastAPI; production build is a static `dist/` served by FastAPI's `StaticFiles`
- **TailwindCSS** for styling
- **@tanstack/react-query** for server state, polling, and cache invalidation — this is the actual state-management layer in practice
- **axios** for HTTP calls
- **react-router-dom** for page routing
- **Framer Motion** for transitions
- `zustand` and `react-player` are listed in `package.json` but are not imported anywhere in the shipped frontend — client state ended up living in component `useState`/React Query instead of a Zustand store, and media preview uses plain native `<img>`/`<video>` elements instead of `react-player`. Both are candidates for removal from `package.json` in a future cleanup.

### Packaging
- **Native (Windows):** `install.bat` (first-time setup: Python venv, pip deps, spaCy model, Playwright Chromium, Alembic migrate, frontend `npm install`) then `start.bat` (migrate → rebuild frontend → `uvicorn main:app --host 127.0.0.1 --port 7420`)
- **Docker:** `docker-compose.yml` runs the main app plus one container per custom adapter (see §11) — a verified, alternate deployment path, not a replacement for native

### File Layout (current)
```
BRollGen/
├── backend/
│   ├── main.py                  # FastAPI entry point, lifespan startup (tmp sweep, adapter_processes state)
│   ├── db/
│   │   ├── models.py            # SQLAlchemy models
│   │   └── database.py          # Engine/session setup
│   ├── routers/
│   │   ├── profiles.py          # NicheProfile CRUD, tags, source links, adapter auto-launch
│   │   ├── sources.py           # MediaSource CRUD, test endpoint, delete-with-cleanup
│   │   ├── uploads.py           # local_folder + custom_adapter-script uploads (app-managed storage)
│   │   ├── sessions.py          # Script/tag-list input, download orchestration, SSE progress
│   │   ├── export.py            # ZIP export (standard + VideoStitch naming), missing-tags export
│   │   ├── local_library.py     # Local folder browsing, tagging, delete, folder ZIP download
│   │   ├── preview.py           # Serves tmp session media files for in-browser preview
│   │   ├── settings.py          # App settings, LLM providers, global tags
│   │   └── docs.py              # Serves CUSTOM_ADAPTER_GUIDE.md as plain text at /docs/adapter
│   └── services/
│       ├── analyzer.py          # Tag extraction (algorithmic + LLM)
│       ├── downloader.py        # Download orchestration, redundant-source-download branch
│       ├── naming.py            # Filename convention parse/build
│       └── source_adapters/     # base.py, pexels.py, pixabay.py, unsplash.py, serp_scraper.py,
│                                 # custom_adapter.py, local_folder.py
├── frontend/
│   └── src/
│       ├── api.js                    # All API calls
│       ├── components/
│       │   └── Dropzone.jsx          # Shared drag-and-drop/browse upload widget
│       └── pages/
│           ├── Dashboard.jsx         # Session flow: setup → tags → download → curation → export
│           ├── Profiles.jsx
│           ├── Sources.jsx
│           ├── LocalLibrary.jsx      # Full tagger UI — see §5.6
│           ├── Settings.jsx
│           └── AdapterDocs.jsx       # Renders the adapter guide in-app
├── docs/
│   ├── implementation/GATELOG.md     # Full phase-by-phase and post-handoff change log
│   ├── CUSTOM_ADAPTER_GUIDE.md       # Adapter protocol + persistent-browser pattern + Docker packaging
│   └── USER_GUIDE.md                 # End-user walkthrough of every feature
├── CustomAdapters/
│   ├── wh40k/                        # Example adapters (40k.gallery, artvee.com, loc.gov)
│   └── uploaded/                     # gitignored — uploaded adapter scripts (backend/routers/uploads.py)
├── local_libraries/                  # gitignored — uploaded local_folder source media
├── alembic/versions/                 # Migration chain
├── tmp/                              # Runtime temp folder (gitignored)
├── docker-compose.yml                # app + one container per custom adapter
├── Dockerfile                        # Main app image
├── DOCKER_SETUP.md                   # Docker deployment notes
├── install.bat / start.bat
└── requirements.txt
```

There is no `bin/ffmpeg.exe`, no `backend/assets/black_bg_*`, no `stitcher.py`, and no `upscaler.py` — all removed with the video pipeline.

---

## 3. Data Models (SQLite, Persistent)

### 3.1 NicheProfile
```
id                        INTEGER PRIMARY KEY
name                      TEXT UNIQUE NOT NULL
description               TEXT
multi_item_per_tag        BOOLEAN DEFAULT TRUE   -- download best-quality-one per source per tag
dedupe_repeat_tags        BOOLEAN DEFAULT TRUE   -- treat repeated tag as one unique tag
redundant_source_download BOOLEAN DEFAULT FALSE  -- ignore multi-item/dedupe; best-1 from EVERY source per tag
default_item_count        INTEGER DEFAULT 10
llm_enabled                BOOLEAN DEFAULT TRUE
llm_provider_id            INTEGER REFERENCES LLMProvider(id)
created_at                 DATETIME
```
`resolution`, `min_resolution`, `aspect_fit`, and `upscale_method` from the original plan were dropped via migration `004` — they only ever fed the removed video pipeline.

### 3.2 ProfileSourceLink
```
id            INTEGER PRIMARY KEY
profile_id    INTEGER REFERENCES NicheProfile(id)
source_id     INTEGER REFERENCES MediaSource(id)
priority      INTEGER DEFAULT 0   -- lower = searched first
```

### 3.3 ProfileTag
```
id            INTEGER PRIMARY KEY
profile_id    INTEGER REFERENCES NicheProfile(id)
word          TEXT NOT NULL
-- UNIQUE(profile_id, word)
```
There is no separate tag-type/category field — a profile's tags are a flat wordlist. (The Local Library tagger's Niche Profile quick-tag buttons, §5.6, are titled directly with this `word`.)

### 3.4 GlobalTag
```
id            INTEGER PRIMARY KEY
word          TEXT UNIQUE NOT NULL
```

### 3.5 MediaSource
```
id                     INTEGER PRIMARY KEY
name                   TEXT NOT NULL
type                   TEXT NOT NULL   -- "pexels" | "pixabay" | "unsplash" | "serp_scraper" | "custom_adapter" | "local_folder"
config                 JSON            -- see §5.4 per-type fields
enabled                BOOLEAN DEFAULT TRUE
created_at             DATETIME
request_delay_seconds  FLOAT           -- NULL = random 2-30s, 0 = no delay, N = fixed N seconds
```
`request_delay_seconds` was added post-plan; it did not exist in the original schema.

### 3.6 LLMProvider
```
id            INTEGER PRIMARY KEY
name          TEXT NOT NULL      -- label
provider_type TEXT NOT NULL      -- "openai" | "anthropic" | "gemini" | "ollama" | "custom"
api_key       TEXT               -- stored as plain text — SECURITY: encrypt in a future version
base_url      TEXT               -- for ollama/custom endpoints
model         TEXT
priority      INTEGER DEFAULT 0  -- lower = tried first
enabled       BOOLEAN DEFAULT TRUE
```

---

## 4. Session Model (In-Memory Only)

A session is created when the user submits a script (or a direct tag list — see §5.7 Step 1). It exists only in server RAM and in the `tmp/<session_id>/` folder.

```python
class Session:
    session_id: str          # UUID4
    profile_id: int
    script_text: str | None  # None for the direct-tag-list session mode
    item_count: int          # N — number of tags to pick
    extracted_tags: list[Tag]
    download_results: list[DownloadResult]
    approved_items: list[DownloadResult]   # after user curation
    tmp_dir: Path
    status: Literal["analyzing","downloading","awaiting_review","done","error"]
    missing_tags: list[str]  # tags that yielded 0 results across all sources

class Tag:
    word: str
    source: Literal["profile_wordlist","global_wordlist","nlp","llm"]
    occurrence_index: int    # 0-based order of first appearance in script
    is_duplicate: bool       # True if same word already appears earlier in tag list

class DownloadResult:
    tag: Tag
    tag_occurrence_index: int
    source_id: int
    source_name: str
    file_path: Path          # local path inside tmp_dir
    media_type: Literal["image","video"]
    width: int | None
    height: int | None
    file_size_bytes: int
    quality_score: float     # computed: resolution-based or file-size proxy
    kept: bool                # user toggled in preview step
```
`needs_upscale` and `upscale_applied` from the original plan are gone — there is no upscale step. `status` no longer includes `"stitching"`.

---

## 5. Feature Specifications

### 5.1 Niche Profile Management (`/profiles`)

**Profile List Page**
- Lists all profiles as cards: name, description, source count, tag count
- "New Profile" button → Profile Editor
- Each card has Edit and Delete actions

**Profile Editor**
- **Basic Info:** Name, Description, Default Item Count (N). No resolution/aspect-fit/upscale fields — those were removed along with the video pipeline.
- **Behaviour toggles:**
  - `Multi-item per tag` (default ON) — download the single best-quality result across all sources per tag. OFF collects every result from every source for that tag.
  - `Deduplicate repeated tags` (default ON) — treat a repeated word as one tag; OFF gives each occurrence its own tag slot (see §5.3 for duplicate handling).
  - `Redundant Source Download` (default OFF) — when ON, ignores the two toggles above and instead downloads the best-1 result from **every enabled source** for that tag, so you get one candidate per source rather than a single globally-best pick. The Curation step (§5.7 Step 4) automatically switches to a grouped-by-tag layout when this is on.
  - `Enable LLM tag extraction` — whether this profile is allowed to use an LLM provider for script analysis
- **Sources panel** — checkboxes for all globally configured sources; selected ones are drag-ordered (sets `priority`)
- **Tag list panel** — chips, typeahead add, CSV/TXT import, per-chip delete

### 5.2 Global Settings Page (`/settings`)

1. **LLM Providers** — CRUD as originally specified: Label, Provider Type, API Key, Base URL, Model, Priority, enabled toggle.
2. **Global Word List** — same chip UI as profile tag list, for the app-wide supplementary list.
3. **Analysis Method** — `LLM` (primary, algorithmic as final fallback) vs `Algorithmic` (primary, LLM never called).
4. **App Paths** — no longer includes ffmpeg or Real-ESRGAN paths; those settings fields were removed along with the pipeline they configured.

### 5.3 Script Analysis & Tag Extraction

Unchanged from the original plan — implemented as specified:

**Entry point:** Dashboard Step 1 — select a profile, either paste a script (Script Analysis mode) or type a tag list directly (Direct Tag List mode, `POST /api/sessions/from-tags` — bypasses script analysis entirely and goes straight to `awaiting_review`), set item count N, analyze.

**Analysis pipeline** (Script Analysis mode):
```
1. Pre-process script: normalize whitespace, case-fold for matching (preserve original for display)
2. Profile wordlist scan (fuzzy match, ~85% threshold via rapidfuzz), honoring dedupe_repeat_tags
3. If tag count < N: scan global wordlist with the same fuzzy logic
4. If tag count still < N: invoke NLP (algorithmic) or LLM analysis for remaining slots
5. If tag count still < N: user fills remaining slots manually in the Tag Review step
6. Truncate to exactly N tags, ordered by first appearance offset in script
```

**Duplicate tag handling (dedupe OFF):** a word appearing K times becomes K tag slots; the downloader searches for up to K distinct files for that word, reusing the best available file(s) to fill any shortfall (logged).

**LLM prompt structure and algorithmic (spaCy) fallback:** unchanged from the original plan — profile wordlist and global wordlist are both included in the LLM prompt as priority/secondary reference, and the spaCy fallback scores candidates by wordlist membership + NER + noun-chunk extraction, deduplicated by lemma.

---

### 5.4 Source Configuration (`/sources`)

**Source List Page** — cards with type badge, name, enabled toggle, live request-delay display, Edit/Delete/Test Connection actions.

**Built-in Source Types:**

| Type | Config Fields |
|---|---|
| `pexels` | API Key |
| `pixabay` | API Key |
| `unsplash` | Access Key |
| `serp_scraper` | SerpAPI Key (optional; Playwright scraper fallback if absent), Max results per query |
| `custom_adapter` | Adapter Base URL, Auth Token (optional), Adapter Script Path — **typed or uploaded** (optional, enables auto-launch — see §5.5) |
| `local_folder` | Media library — **uploaded**, not a typed path (drag-and-drop or native folder/file picker); Enabled file extensions (optional filter, comma-separated) |

**Local Folder and Custom Adapter uploads (departure from the original plan):** the original plan had `local_folder` take a typed Windows path (`folder_path`) and `custom_adapter` take only a URL. In practice, a typed host path broke the moment the backend ran anywhere other than directly on the user's Windows machine (WSL, Docker) — the path had to exist on whatever filesystem the backend process saw. Both are now handled by real file upload over HTTP instead:

- `POST /api/sources/{id}/upload/folder` — accepts one or more files (a flat multi-select or a whole folder via a `webkitdirectory` picker / drag-and-drop, using `DataTransferItem.webkitGetAsEntry()` recursive traversal on drop). Files are flattened into `local_libraries/<source_id>/` (subfolder structure isn't kept — the local-folder search itself only ever scans that one directory, non-recursively). Re-uploading **adds to** the existing library; same-name files get a numeric suffix rather than being overwritten. `config.folder_path` is written automatically to that canonical directory.
- `POST /api/sources/{id}/upload/adapter-script` — accepts one `.py` file, saved under `CustomAdapters/uploaded/<source_id>/`, and sets `config.adapter_script_path` automatically.
- Both endpoints require the source to already have an ID (a brand-new source must be saved — name + type only — before its upload area unlocks).
- **`config.folder_path` is treated as a cache, not ground truth.** Every route that reads a local_folder source's files resolves the canonical `local_libraries/<source_id>/` directory first, falling back to the stored `folder_path` only if that canonical directory doesn't exist. This makes the app self-healing against a stale `folder_path` (e.g. captured while running under Docker, where it resolves to `/app/local_libraries/<id>` — meaningless outside a container) instead of requiring a manual fix.
- **Deleting a source now also removes its upload directory.** `DELETE /api/sources/{id}` deletes the `MediaSource` row first, then best-effort removes the matching `local_libraries/<id>/` or `CustomAdapters/uploaded/<id>/` directory (whichever applies) — nothing is left orphaned on disk. A locked file logs a warning rather than failing the delete.

**Source Search Protocol (per tag, per search run):** unchanged from the original plan — iterate sources by priority, score by `width * height` (images) or a bitrate-weighted equivalent (video), fall back to `file_size_bytes`; `multi_item_per_tag` keeps the single best or all results per source as configured; if `redundant_source_download` is on for the profile, this whole scoring/multi-item logic is bypassed in favor of one best-1 result per source.

**SerpAPI / Playwright scraper logic:** unchanged — SerpAPI Custom Search Images if a key is configured, otherwise a Playwright-driven Google Images scrape with a minimum-dimension heuristic.

---

### 5.5 Custom Source Adapter Protocol & Lifecycle

The wire protocol is unchanged from the original plan: `GET /health`, `GET /search?q=...&limit=...&media_type=...`, `GET /download?id=...`, `Authorization: Bearer {token}` auth, all documented in `docs/CUSTOM_ADAPTER_GUIDE.md` (also served in-app at `/docs/adapter`).

**New: adapter lifecycle.** The original plan treated a custom adapter as an always-external, always-running HTTP server. In practice, adapters are usually the app's own local scraper processes (see `CustomAdapters/wh40k/` for the shipped Flask examples — persistent-Playwright-browser pattern, one process per adapter). To avoid requiring the user to manually start each one before every session:

- `POST /api/profiles/{id}/adapters/start` is called automatically whenever a profile is selected on the Dashboard.
- For each linked `custom_adapter` source: health-check `adapter_url` first (already running → skip); if unhealthy and `adapter_script_path` is configured, launch it via `subprocess.Popen([sys.executable, script_path], ...)` and poll health for up to 10s.
- **This is fire-and-forget and never blocks session setup** — a launch failure or timeout is logged as a warning, not surfaced as a blocking error, since per-source search failures are already handled gracefully by the download orchestrator.
- **`Test Connection` on the Sources page never triggers this launch** — it's a plain health-check GET, nothing more. This distinction matters operationally: an adapter with no script configured and nothing manually started will show `"All connection attempts failed"` on both Test Connection and real searches, even though nothing is actually broken — it just hasn't been launched yet.
- **`adapter_url` must match how the app is currently running.** Native (`start.bat`): `http://localhost:<port>`. Docker: `http://<compose-service-name>:<port>` — `localhost` inside the `app` container refers to the `app` container itself, not sibling adapter containers. See `DOCKER_SETUP.md`.
- `adapter_script_path` is irrelevant under Docker — each adapter container starts its own script directly via its Dockerfile `CMD`.

---

### 5.6 Local Folder Source & Library Tagger (`/library`)

**This entire feature was redesigned post-launch** — the original plan's two-panel layout (dropdown + file list on the left, viewer + tag input on the right) shipped initially but had no working preview or delete capability and paginated awkwardly. It was replaced with a single top-to-bottom flow.

**Naming Convention** (unchanged from the original plan):
```
[tag1]_[tag2]_[tag3]--[quality]--[uid].[ext]
```
- Tags: lowercase, underscore-joined within a phrase, tags separated by `_`
- Quality (optional): `U` / `H` / `M` / `L`
- UID: 6-digit zero-padded integer, auto-incremented from the max existing UID in the folder
- Files not following the convention still appear, flagged "Untagged"

**Current page layout, top to bottom:**

1. **Source picker** — a dropdown of every uploaded `local_folder` source.
2. **Central preview** — the selected file's image/GIF renders directly, or a video plays with native `<video controls autoPlay loop>`.
3. **Controls directly under the preview:**
   - **← Prev / Next →** — step sequentially through every file in the library.
   - **Tag chips** — the file's currently applied tags, each removable via a ✕.
   - **Niche Profile tag buttons** (new) — a **Niche Profile** dropdown lists every profile; picking one renders a `flex flex-wrap` row of buttons below it, one per tag word in that profile's wordlist (§3.3 — there's no separate tag-type/category concept, so each button is simply titled with its tag word). Clicking a button toggles that word on/off the file's tag list — same effect as the free-text box below, one click instead of typing.
   - **Free-text tag input** — the fallback for anything the selected profile's buttons don't cover; Enter or comma confirms each word.
   - **Quality Grade** picker: U / H / M / L / none.
   - **Save Tagged Name** — generates a UID if absent, renames the file on disk (`[tags]--[quality]--[uid].[ext]`), and writes the sidecar JSON (schema unchanged from the original plan). A new-word-not-in-any-list triggers the same New Word Prompt modal as before.
   - **Delete** (new) — permanently removes the currently selected file and its sidecar (with confirmation).
4. **File card grid** (new, replaces the original plan's plain file list) — every file as a small card: a thumbnail filling ~70% of the card height (video files show a 🎬 placeholder rather than a generated thumbnail), the filename and a small red ✕ delete button in the remaining strip, an "Untagged" badge where applicable. Clicking a card loads that file into the preview above.
5. **Upload more files** — the same drag-and-drop/browse upload widget used on the Sources page, reused via a shared `Dropzone` component, appends more files to the currently selected library without leaving the page.
6. **Download Folder** (new) — a button that streams a ZIP of every media file currently in the selected library, using each file's current (already tag-renamed) filename. Sidecar `.json` files are excluded — the tags travel via the filename itself. Disabled when the library is empty.

**Local Source Search (during a session):** unchanged from the original plan — sidecar JSONs read and cached per session, filenames parsed as fallback, fuzzy-matched against the query (rapidfuzz, ~80% threshold), ranked by quality grade then file size.

---

### 5.7 Session Flow — Dashboard (`/`)

**Step 1: Setup**
- Select Niche Profile — this also fires the adapter auto-launch described in §5.5
- **Script Analysis** mode: paste script into textarea; or **Direct Tag List** mode: type tags directly, bypassing analysis
- Set Item Count (N), pre-filled from profile default
- Analysis Method toggle (Script Analysis mode only): LLM / Algorithmic
- "Analyze Script" (or "Use These Tags") button

**Step 2: Tag Review** — unchanged from the original plan: editable ordered chips (source label, occurrence count), tag count indicator vs. N, "Proceed to Download" gated on count = N.

**Step 3: Download** — unchanged: per-source progress, per-tag status via SSE, end-of-run "Missing Tags" panel with a `.txt` export.

**Step 4: Preview & Curation** — a grid of downloaded items with Keep/Drop toggles, as originally specified. **New:** when the profile has `redundant_source_download` on, this step automatically switches to a grouped-by-tag layout — one card per source that returned a result for that tag — instead of a flat grid, so the user can compare and pick per source rather than trust a single automatic best-pick.

**Step 5: Export — replaces the original plan's stitch-to-video step.** There is no video assembly. Two independent ZIP export modes, both usable on their own:
- **`GET /api/sessions/{id}/export/zip`** — the standard export, zero-padded numeric prefixes (`001_space_marine.jpg`, `002_ultramarines.mp4`), numbered by tag occurrence order.
- **`GET /api/sessions/{id}/export/videostitch`** — an alternate naming convention with no zero-padding (`1_`, `10_`, `100_`), added for compatibility with an external video-stitching tool the user runs separately, despite the app itself no longer doing any stitching.

The original plan's "Pre-Export Sweep" (resolution/aspect-fit check, single-pass ffmpeg normalization, sweep progress SSE, sweep summary panel) does not exist — there is nothing to normalize once upscaling and aspect-fit were removed. Files are exported exactly as downloaded.

---

### 5.8 Missing Tags Export

Unchanged from the original plan: any session with ≥1 zero-result tag shows a collapsible panel (tag word + sources searched) and an "Export as .txt" button (`GET /api/sessions/{id}/export/missing-tags`).

---

### 5.9 Adapter Documentation Page (`/docs/adapter`)

Unchanged in concept from the original plan — in-app rendering of `docs/CUSTOM_ADAPTER_GUIDE.md` via `GET /api/docs/adapter`, covering the protocol, endpoint examples, and (now also) the persistent-browser adapter pattern and Docker packaging notes that were added after the original plan was written.

---

## 6. API Routes (FastAPI) — current, as implemented

```
GET    /api/profiles                             List profiles
POST   /api/profiles                             Create profile
GET    /api/profiles/{id}                        Get profile
PUT    /api/profiles/{id}                        Update profile
DELETE /api/profiles/{id}                         Delete profile
GET    /api/profiles/{id}/tags                    List profile tags
POST   /api/profiles/{id}/tags                    Add tag word
DELETE /api/profiles/{id}/tags/{tag_id}            Remove tag word
POST   /api/profiles/{id}/tags/import-csv          Import tags from .txt/.csv
GET    /api/profiles/{id}/sources                  List a profile's linked sources
PUT    /api/profiles/{id}/sources                  Replace a profile's source list (ordered = priority)
POST   /api/profiles/{id}/adapters/start           Health-check/auto-launch this profile's custom adapters

GET    /api/sources                                List sources
POST   /api/sources                                Create source
PUT    /api/sources/{id}                           Update source
DELETE /api/sources/{id}                            Delete source (+ app-managed upload directory)
POST   /api/sources/{id}/test                       Test source connectivity
POST   /api/sources/{id}/upload/folder              Upload local_folder media (multi-file)
GET    /api/sources/{id}/upload/folder/status        Current uploaded file count
DELETE /api/sources/{id}/upload/folder                Clear the uploaded library
POST   /api/sources/{id}/upload/adapter-script        Upload a custom_adapter launch script

GET    /api/global-tags                            List global tags
POST   /api/global-tags                            Add global tag
DELETE /api/global-tags/{id}                        Remove global tag
POST   /api/global-tags/import-csv                  Import from .txt/.csv

GET    /api/llm-providers                           List LLM providers
POST   /api/llm-providers                            Add provider
PUT    /api/llm-providers/{id}                        Update provider
DELETE /api/llm-providers/{id}                        Delete provider

POST   /api/sessions                                Create session (script analysis)
POST   /api/sessions/from-tags                       Create session directly from a typed tag list
GET    /api/sessions/{id}                             Get session state
PUT    /api/sessions/{id}/tags                        Update tag list after user edits
POST   /api/sessions/{id}/download                    Start download job
GET    /api/sessions/{id}/progress                    SSE stream for download progress
PUT    /api/sessions/{id}/curation                    Update kept/dropped status of items
GET    /api/sessions/{id}/export/zip                  Standard ZIP export
GET    /api/sessions/{id}/export/videostitch          No-zero-padding ZIP export
GET    /api/sessions/{id}/export/missing-tags          Missing-tags .txt report
DELETE /api/sessions/{id}                              Clean up tmp folder

GET    /api/library/sources                          List local_folder sources
GET    /api/library/{source_id}/files                 List files in a library (paginated)
GET    /api/library/{source_id}/files/{filename}       Get file metadata
POST   /api/library/{source_id}/files/{filename}/tag    Save tags for a file (renames + sidecar)
DELETE /api/library/{source_id}/files/{filename}        Delete a file (+ sidecar)
GET    /api/library/{source_id}/download                Download the whole library as a ZIP
GET    /api/library/preview/{source_id}/{filename}      Serve a file for in-browser preview

GET    /api/preview/{session_id}/{filename}            Serve a tmp session media file for preview

GET    /api/settings                                   Get app settings
PUT    /api/settings                                    Update app settings

GET    /api/docs/adapter                                Serve adapter guide (plain text)
```

Removed from the original plan entirely (no replacement — the features they backed no longer exist): `POST /api/sessions/{id}/sweep`, `GET /api/sessions/{id}/sweep-progress`, `POST /api/sessions/{id}/export/video`.

---

## 7. Error Handling

Unchanged from the original plan, minus anything ffmpeg-specific:
- All API errors return `{"detail": "..."}` (FastAPI's default `HTTPException` shape) with an appropriate HTTP status
- Download failures per item are non-fatal: skipped, tag added to `missing_tags` if all its attempts fail
- LLM provider failures cascade to the next provider by priority; final fallback is algorithmic
- Playwright scraper failures (blocked, timeout) are caught and logged per-session, not globally disabling the source
- Adapter auto-launch failures/timeouts are logged as warnings and never block session setup (§5.5)
- A local_folder file rename retries up to 3 times with a 500ms delay on `PermissionError` (Windows file-lock)

---

## 8. Windows-Specific Considerations

- All file paths use `pathlib.Path`
- `tmp/` is created relative to the app's working directory, not system temp
- Playwright on Windows: Chromium, installed via `install.bat`'s `playwright install chromium` step
- File rename on Windows: handles `PermissionError` with retry (see §7)
- Long paths: keep the app directory shallow to avoid the 260-char `MAX_PATH` issue

The original plan's ffmpeg-binary-detection and Real-ESRGAN-binary-detection items are removed — there's nothing left that shells out to either.

---

## 9. Out-of-Scope Items

Everything from the original plan's out-of-scope list still holds, plus what was actively built and then removed:

- Video transitions, Ken Burns/pan-zoom, background music/audio track
- Session persistence / project save-and-reopen
- User authentication, cloud storage integration, multi-user support
- Subtitle/transcript overlay, scheduled/batch processing, browser extension
- **Video stitching and any form of image upscaling/aspect-fit normalization** — built in the original implementation, then fully descoped (§0). Not planned to return; the export step is ZIP-only by design now, not as an interim state.

---

## 10. Non-Functional Requirements

- App must start cold in < 5 seconds on a modern Windows machine
- Script analysis (algorithmic) must complete in < 3 seconds for scripts up to 5,000 words
- Download phase streams progress in real time (SSE, no full-page reload)
- Tmp folder cleanup runs on session end and via a startup sweep for orphaned folders older than 24h
- All user-facing text in English
- No telemetry, no network calls except to configured sources and LLM providers

The original plan's "video stitch for 20 clips must complete in < 60 seconds" requirement no longer applies — there is no stitch step.

---

## 11. Deployment: Native vs. Docker

Native (`install.bat` then `start.bat`) is the primary, actively-used path for day-to-day development and adapter iteration — no image rebuild needed for a Python-only change.

**Docker** (`docker-compose.yml`: the main `app` container plus one container per custom adapter, e.g. `adapter-wh40k`) was built and verified end-to-end — all containers healthy, a real session searching a custom adapter and downloading results successfully — and is the intended path for eventual deployment to a VPS. It is not currently the day-to-day deployment; see `DOCKER_SETUP.md` for the full setup, the `localhost`-vs-Compose-service-name adapter URL requirement (§5.5), and a known `docker-compose` v1 container-recreate bug and its workaround.

Switching between native and Docker requires updating each `custom_adapter` source's Adapter Base URL to match (`http://localhost:<port>` vs `http://<compose-service-name>:<port>`) — this is the single most common point of confusion when moving between the two, documented in both `DOCKER_SETUP.md` and `docs/USER_GUIDE.md`'s troubleshooting section.

---

## 12. Implementation History

The original plan's phased implementation order (scaffold → settings/LLM → sources → profiles → algorithmic analyzer → LLM analyzer → source adapters → download orchestrator → dashboard flow → stitcher → upscaler → library tagger → adapter docs → polish) was followed through 6 gated phases, all completed and verified — see `docs/implementation/GATELOG.md` for the authoritative, detailed record of every phase and every post-handoff change (including the stitcher/upscaler removal, the upload-based source config redesign, the Local Library redesign, and the Docker verification). That file, not this section, is the source of truth for exact chronology; this PRD describes end-state behavior only.
