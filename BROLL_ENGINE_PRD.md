# B-Roll Engine — Product Requirements Document
**Version:** 1.1  
**Target Agent:** Claude Code  
**Platform:** Windows, local web server (browser UI)  
**Status:** V1 Scope — Stateless sessions, no auth, single user

---

## 1. Product Overview

B-Roll Engine is a locally-hosted web application that accepts a video script as input, analyzes it to extract searchable tags, searches configured media sources (online APIs, web scrapers, and local folders) for matching images and videos, presents the results for user curation, and stitches the approved media into a final B-roll video — all without requiring cloud storage or user accounts.

The app runs as a local Python server (backend) with a React frontend served from the same process. The user opens it in their browser. All state lives in memory for the duration of a session. On session end (video exported or page closed), temporary files are cleaned up.

---

## 2. Tech Stack

### Backend
- **Python 3.11+** with **FastAPI** (async, WebSocket support for progress streaming)
- **yt-dlp** for video downloading from supported sites
- **Playwright** (async) for headless scraping of non-API sources
- **spaCy** (`en_core_web_sm`) for NLP-based tag extraction (algorithmic fallback)
- **ffmpeg-python** wrapping the system `ffmpeg` binary for video stitching
- **Pillow** for image metadata/dimension reading
- **SQLite** via **SQLAlchemy** (sync, for persistent config: profiles, sources, word lists, LLM settings — NOT session data)
- **APScheduler** or simple background task via FastAPI `BackgroundTasks` for async download jobs
- **httpx** for async HTTP calls to online APIs and LLM providers
- **Real-ESRGAN** (optional, user-configured) for AI-based image upscaling — app must remain fully functional without it; ffmpeg lanczos is always the fallback

### Frontend
- **React 18** with **Vite** dev server proxied through FastAPI in production
- **TailwindCSS** for styling
- **Zustand** for client state management
- **React Query** for server state / API polling
- **react-player** for in-browser video/image preview
- **Framer Motion** for transitions

### Packaging
- A single `start.bat` launches `uvicorn main:app --host 127.0.0.1 --port 7420`
- Frontend is built (`npm run build`) into a `dist/` folder served by FastAPI's `StaticFiles`
- `ffmpeg.exe` is bundled in `/bin/ffmpeg.exe`; the app checks for it on startup and falls back to system PATH

### File Layout
```
broll-engine/
├── backend/
│   ├── main.py                  # FastAPI entry point
│   ├── db/                      # SQLAlchemy models + migrations (Alembic)
│   ├── routers/                 # One file per feature domain
│   │   ├── profiles.py
│   │   ├── sources.py
│   │   ├── sessions.py          # Script input, tag extraction, download orchestration
│   │   ├── local_library.py     # Local folder browsing + tagging UI
│   │   ├── preview.py           # Serve tmp media files
│   │   ├── export.py            # Video stitch + zip download
│   │   └── settings.py
│   ├── services/
│   │   ├── analyzer.py          # Tag extraction (algo + LLM)
│   │   ├── downloader.py        # Download orchestration
│   │   ├── source_adapters/     # One adapter per source type
│   │   │   ├── base.py
│   │   │   ├── pexels.py
│   │   │   ├── pixabay.py
│   │   │   ├── unsplash.py
│   │   │   ├── serp_scraper.py  # SerpAPI + Playwright fallback
│   │   │   └── custom_adapter.py
│   │   ├── stitcher.py          # ffmpeg video assembly
│   │   ├── upscaler.py          # image upscale pipeline (Real-ESRGAN + lanczos fallback)
│   │   └── naming.py            # Filename convention parsing/generation
│   └── assets/
│       ├── black_bg_horizontal.mp4   # 30-min UHD black background video (landscape)
│       ├── black_bg_vertical.mp4     # 30-min UHD black background video (portrait)
│       ├── black_bg_horizontal.png   # UHD black background image (landscape)
│       └── black_bg_vertical.png     # UHD black background image (portrait)
├── frontend/
│   ├── src/
│   │   ├── pages/
│   │   │   ├── Dashboard.jsx         # Script input + session start
│   │   │   ├── LocalLibrary.jsx      # Tagging UI for local folder sources
│   │   │   ├── Profiles.jsx
│   │   │   ├── Sources.jsx
│   │   │   ├── Settings.jsx
│   │   │   └── AdapterDocs.jsx       # In-app custom adapter documentation
│   │   └── components/
├── docs/
│   └── CUSTOM_ADAPTER_GUIDE.md       # Bundled adapter dev guide
├── bin/
│   └── ffmpeg.exe
├── tmp/                              # Runtime temp folder (gitignored)
├── start.bat
└── requirements.txt
```

---

## 3. Data Models (SQLite, Persistent)

### 3.1 NicheProfile
```
id            INTEGER PRIMARY KEY
name          TEXT UNIQUE NOT NULL
description   TEXT
resolution    TEXT DEFAULT "1920x1080"   -- "1920x1080" | "1080x1920" | "3840x2160" etc.
min_resolution TEXT DEFAULT "1920x1080" -- minimum resolution threshold for upscale check (WxH)
aspect_fit    TEXT DEFAULT "box_zoom"    -- "box_zoom" | "black_overlay"
upscale_method TEXT DEFAULT "lanczos"   -- "lanczos" | "realesrgan"
multi_item_per_tag  BOOLEAN DEFAULT TRUE  -- download best-quality-one per source per tag
dedupe_repeat_tags  BOOLEAN DEFAULT TRUE  -- treat repeated tag as one unique tag
default_item_count  INTEGER DEFAULT 10
llm_enabled   BOOLEAN DEFAULT TRUE
llm_provider_id INTEGER REFERENCES LLMProvider(id)
created_at    DATETIME
```

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

### 3.4 GlobalTag
```
id            INTEGER PRIMARY KEY
word          TEXT UNIQUE NOT NULL
```

### 3.5 MediaSource
```
id            INTEGER PRIMARY KEY
name          TEXT NOT NULL
type          TEXT NOT NULL   -- "pexels" | "pixabay" | "unsplash" | "serp_scraper" | "custom_adapter" | "local_folder"
config        JSON            -- api_key, base_url, folder_path, adapter_url, etc.
enabled       BOOLEAN DEFAULT TRUE
created_at    DATETIME
```

### 3.6 LLMProvider
```
id            INTEGER PRIMARY KEY
name          TEXT NOT NULL      -- "openai" | "anthropic" | "gemini" | "ollama" | custom label
provider_type TEXT NOT NULL      -- enum above
api_key       TEXT               -- stored as-is (no encryption in v1)
base_url      TEXT               -- for ollama or custom endpoints
model         TEXT               -- e.g. "gpt-4o", "claude-sonnet-4-6", "gemini-1.5-pro"
priority      INTEGER DEFAULT 0  -- lower = tried first
enabled       BOOLEAN DEFAULT TRUE
```

---

## 4. Session Model (In-Memory Only)

A session is created when the user submits a script. It exists only in server RAM and in the `/tmp/<session_id>/` folder.

```python
class Session:
    session_id: str          # UUID4
    profile_id: int
    script_text: str
    item_count: int          # N — number of tags to pick
    extracted_tags: list[Tag]
    download_results: list[DownloadResult]
    approved_items: list[DownloadResult]   # after user curation
    tmp_dir: Path
    status: Literal["analyzing","downloading","awaiting_review","stitching","done","error"]
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
    needs_upscale: bool      # True if image is below profile min_resolution
    upscale_applied: Literal["none","lanczos","realesrgan"] = "none"
    kept: bool               # user toggled in preview step
```

---

## 5. Feature Specifications

### 5.1 Niche Profile Management (`/profiles`)

**Profile List Page**
- Lists all profiles as cards: name, description, resolution, source count, tag count
- "New Profile" button → Profile Editor
- Each card has Edit and Delete actions

**Profile Editor**
- Fields: Name, Description, Output Resolution (dropdown: 1920×1080, 1080×1920, 3840×2160, custom), Minimum Resolution Threshold (same dropdown options as Output Resolution — images below this are upscaled), Aspect Fit Mode (box_zoom / black_overlay)
- **Upscale Method** selector: `ffmpeg lanczos` (always available) or `Real-ESRGAN` (shown with a "(not configured)" badge if Real-ESRGAN binary path is not set in Settings; clicking it redirects user to Settings to configure it)
- **Per-profile toggles:**
  - `Multi-item per tag` — when ON (default), download best-quality single item per source per tag. When OFF, download all hits from all sources for each tag
  - `Deduplicate repeated tags` — when ON (default), treat repeated word as one tag. When OFF, each occurrence becomes its own tag slot (see §5.3 for duplicate handling logic)
- **Default item count** — integer input, default 10
- **LLM setting** — select which LLM provider to use for this profile (inherits from global Settings if unset), toggle LLM on/off per profile
- **Sources panel** — shows all globally configured sources as checkboxes; user picks which ones this profile uses. Each selected source can be drag-ordered (sets `priority`)
- **Tag list panel:**
  - Shows all profile-specific tags as removable chips
  - Typeahead input to add new words to the profile tag list
  - "Import from CSV" option
  - Delete button per chip

### 5.2 Global Settings Page (`/settings`)

Sections:
1. **LLM Providers** — Add/edit/delete LLM providers. Fields: Label, Provider Type (openai / anthropic / gemini / ollama / custom), API Key, Base URL (for ollama/custom), Model name, Priority (drag to reorder). Toggle enabled/disabled per provider.
2. **Global Word List** — Same chip UI as profile tag list but for the global supplementary list
3. **Analysis Method** — Toggle: `LLM` (primary) vs `Algorithmic` (primary). When LLM is primary, algo is always the final fallback. When algo is primary, LLM is never called.
4. **App Paths** — ffmpeg binary path (auto-detected, overridable), tmp folder path, **Real-ESRGAN binary path** (optional — text input + "Test" button that runs `realesrgan-ncnn-vulkan.exe --version` and reports success/failure; if blank or failing, app falls back to lanczos for all profiles set to Real-ESRGAN)

### 5.3 Script Analysis & Tag Extraction

**Entry point:** Dashboard page — user selects a profile, pastes script, sets `N` (item count), and clicks "Analyze Script."

**Analysis pipeline:**

```
1. Pre-process script:
   - Normalize whitespace
   - Case-fold for matching (preserve original for display)

2. Profile wordlist scan (fuzzy match, threshold ~85% similarity using rapidfuzz):
   - Scan script for any word/phrase from profile tag list
   - Record position (character offset) of each match
   - If dedupe_repeat_tags = ON: collect unique matched words only
   - If dedupe_repeat_tags = OFF: collect every occurrence as a separate tag slot

3. If tag count < N: scan global wordlist with same fuzzy logic to fill gaps

4. If tag count still < N: invoke NLP or LLM analysis for remaining slots

5. If tag count still < N after all methods: prompt user to manually add remaining tags
   - Show "Tag Picker" modal: displays remaining gap count, lets user type tags freeform
   - User can type partial phrases and press Enter/comma to add

6. Truncate to exactly N tags (ordered by first appearance offset in script)
```

**Duplicate tag handling (dedupe OFF case):**

When a tag word appears K times and dedupe is OFF, create K tag slots all with the same word. During download, the downloader attempts to find K *distinct* files for this word. Strategy:
- Search all configured sources for all available results for that word (not just best-quality-one)
- Sort by quality_score descending, take up to K unique files
- If fewer than K unique files found, reuse the best available file(s) to fill remaining slots (log which files were reused)

**LLM Prompt Structure:**

```
[TASK]
You are a B-roll tag extractor. Given a video script, extract exactly {N} searchable tags to find relevant B-roll footage. Tags should be concrete, visual nouns or noun phrases (things that can be photographed or filmed).

[NICHE PROFILE WORD LIST]
{profile_tags_comma_separated}
(These are high-priority terms specific to this niche. Always include any of these that appear in the script before picking general tags.)

[GLOBAL SUPPLEMENTARY WORD LIST]
{global_tags_comma_separated}
(Use these as secondary reference to fill remaining slots after profile tags are exhausted.)

[SCRIPT]
{script_text}

[OUTPUT FORMAT]
Return exactly a JSON array of {N} strings, ordered by first appearance in the script. Example:
["the emperor", "space marine", "chaos army", "warp storm", "ultramarines chapter"]

[CONSTRAINTS]
Return only the JSON array. No explanation. No preamble. No trailing questions. No markdown code fences.
```

**Algorithmic fallback (spaCy NLP):**
1. Run spaCy `en_core_web_sm` NER + noun chunk extraction on script
2. Score each candidate: +2 if in profile wordlist (fuzzy), +1 if in global wordlist (fuzzy), +1 if named entity, +0.5 if noun chunk
3. Deduplicate by lemma
4. Sort by (score DESC, first_appearance ASC), take top N
5. Apply fuzzy normalization so "Ultramarines" and "ultramarines" resolve to same tag

---

### 5.4 Source Configuration (`/sources`)

**Source List Page**
- All configured sources as cards with type badge, name, enabled toggle, Edit/Delete
- "Add Source" button with type selector dropdown

**Built-in Source Types:**

| Type | Config Fields |
|---|---|
| `pexels` | API Key |
| `pixabay` | API Key |
| `unsplash` | Access Key |
| `serp_scraper` | SerpAPI Key (optional; falls back to Playwright scraper if absent), Max results per query |
| `custom_adapter` | Adapter Base URL, Auth Token (optional), Description |
| `local_folder` | Folder Path (Windows path, e.g. `D:\BRoll\Warhammer`), Enabled file extensions |

**Source Search Protocol (per tag, per search run):**

For each tag, iterate sources in priority order (lowest `priority` number first):
1. Call source adapter `search(query, max_results)` → returns list of candidate items with metadata
2. For each candidate: attempt to read metadata (dimensions, duration) before downloading
3. Compute `quality_score`: `width * height` for images; `width * height * bitrate` for video; fall back to `file_size_bytes` if metadata unavailable
4. If `multi_item_per_tag = ON`: keep only the single highest quality_score result from this source
5. If `multi_item_per_tag = OFF`: keep all results from this source
6. Continue to next source regardless (always search all sources to compare quality)
7. After all sources searched: if `multi_item_per_tag = ON`, pick the globally best item across all sources; if OFF, keep all collected items

**SerpAPI / Playwright scraper logic:**
- If SerpAPI key is configured: use Google Custom Search Images API
- If no SerpAPI key: use Playwright to load `https://www.google.com/search?q={query}&tbm=isch`, extract image URLs from DOM, download candidates
- Playwright scraper targets image `src` attributes with minimum dimension heuristic (skip thumbnails < 200px)

---

### 5.5 Custom Source Adapter Protocol

Custom adapters are HTTP servers (any language) that implement a simple REST interface. The app communicates with them via JSON over HTTP.

**Required endpoints:**

`GET /health`
```json
{ "status": "ok", "name": "My Custom Source", "version": "1.0" }
```

`GET /search?q={query}&limit={n}&media_type={image|video|any}`
```json
{
  "results": [
    {
      "id": "unique_string",
      "title": "optional description",
      "media_type": "image",
      "preview_url": "https://...",
      "download_url": "https://...",
      "width": 1920,
      "height": 1080,
      "duration_seconds": null,
      "file_size_bytes": 204800,
      "source_page_url": "https://..."
    }
  ]
}
```

`GET /download?id={id}` → streams the binary file with correct `Content-Type` header

- All fields except `id`, `media_type`, `download_url` are optional but recommended for quality scoring
- `width`, `height`, `duration_seconds`, `file_size_bytes` are used for quality scoring
- If `download_url` is a direct file URL, the app will download it directly (no `/download` call needed)
- Auth is via `Authorization: Bearer {token}` header (token configured in source settings)

The bundled `docs/CUSTOM_ADAPTER_GUIDE.md` contains a full reference with example implementations in Python (Flask), Node.js (Express), and a minimal shell script.

---

### 5.6 Local Folder Source & Library Tagger (`/library`)

**Naming Convention:**

Files managed by the app follow this convention:

```
[tag1]_[tag2]_[tag3]--[quality]--[uid].[ext]
```

- Tags: lowercase, words separated by underscores within a tag phrase, tags separated by `_`
- Quality (optional): `U` (ultra), `H` (high), `M` (medium), `L` (low)
- UID: 6-digit zero-padded integer generated by the app (e.g. `000042`)
- Examples:
  - `space_marine_ultramarines_warhammer--H--000042.jpg`
  - `chaos_warp_storm--U--000107.mp4`
  - `ocean_waves--000015.png` (no quality tag)

Files not following this convention are still shown in the library tagger but shown with a "Untagged" badge.

**Library Tagger Page:**

Left panel: Source selector (dropdown of all local_folder sources) + file list with thumbnail previews. Files sorted: untagged first, then by UID.

Right panel: Media viewer
- Images: displayed with natural aspect ratio, zoom on hover
- Videos: `<video>` element with autoplay, controls, loop

**Tagging workflow:**

1. User selects a file from left panel
2. Tag input appears below viewer: typeahead that searches profile tag lists and global list
3. User can also type freeform — pressing Enter or comma confirms each tag
4. Quality grade selector: U / H / M / L / (none)
5. "Save Tags" button:
   - Generates UID if not present (auto-incremented from max existing UID in that folder)
   - Renames file on disk: `[tags]--[quality]--[uid].[ext]`
   - Writes sidecar JSON: `[uid].json` in same folder
   ```json
   {
     "uid": "000042",
     "original_filename": "image001.jpg",
     "tags": ["space marine", "ultramarines", "warhammer"],
     "quality": "H",
     "media_type": "image",
     "tagged_at": "2025-06-17T14:00:00Z"
   }
   ```
   - Any newly typed tag not in any profile list or global list triggers the **New Word Prompt**

**New Word Prompt (modal):**
- Triggered automatically after Save Tags if unrecognized words were used
- Shows each new word as a chip
- User selects destination: "Global List" or any specific profile (dropdown)
- "Save Word" button — adds to selected list and closes modal
- User can dismiss without saving (tag still applies to the file, just not added to any list)

**Local Source Search (during session):**

When a local folder source is searched for a tag:
- Read all sidecar JSONs in the folder (cache in memory for the session)
- Also parse filenames following the naming convention as fallback
- Match tags against query using fuzzy match (rapidfuzz, threshold 80%)
- Rank by quality grade (U > H > M > L > ungraded), then by file_size_bytes

---

### 5.7 Session Flow — Dashboard (`/`)

**Step 1: Setup**
- Select Niche Profile (dropdown)
- Paste script into textarea
- Set Item Count (N) — pre-filled from profile default
- Analysis Method toggle: LLM / Algorithmic (inherits from Settings, overridable per session)
- "Analyze Script" button

**Step 2: Tag Review**

After analysis, show the extracted tag list as an editable interface:
- Ordered chips — each shows: tag word, source label (Profile / Global / NLP / LLM), occurrence count in script
- User can: remove a chip, edit a chip's text, drag to reorder, add new chips manually
- Tag count indicator: shows current / N. If count < N, show "Add more tags" prompt in red
- "Proceed to Download" button (disabled until tag count = N)

**Step 3: Download**

Progress screen with:
- Source-by-source progress bars (one per source)
- Per-tag status indicators: searching → found → downloaded / not found
- Real-time updates via WebSocket or SSE
- At end: "Missing Tags" section shows any tags that returned 0 results across all sources
  - "Export Missing Tags (.txt)" button — downloads newline-separated list

**Step 4: Preview & Curation**

Grid of downloaded items (thumbnails/preview frames). Each item shows:
- Preview thumbnail (click to open fullscreen lightbox with autoplay for video)
- Tag label it belongs to
- Source name
- Quality score badge
- Keep/Drop toggle (default: Keep)

Controls:
- "Keep All" / "Drop All" shortcuts
- "Proceed to Export" button (disabled if 0 items kept)

**Step 5: Export**

- **Item duration** (seconds): number input — applied to images only; videos play full length
- **Video output format:** pre-filled from profile resolution, editable
- Two export buttons:
  - **"Download Media ZIP"** — triggers pre-export sweep (see below), then zips all kept items, numbered by stitch order (`001_space_marine.jpg`, `002_ultramarines.mp4`, etc.) with the search tag appended to each filename
  - **"Make Video"** — triggers pre-export sweep, then ffmpeg stitch; shows progress bar; on complete offers download of `.mp4`
- Both buttons can be used independently or together

**Pre-Export Sweep (runs before both ZIP and video stitch):**

When the user clicks either export button, before any stitching or zipping begins, the app runs a full sweep of all kept `DownloadResult` items:

1. **Resolution check (images only):** Read each image's actual pixel dimensions (using Pillow). Compare against the profile's `min_resolution` (e.g. `1920x1080` means min width=1920 AND min height=1080 — both must be met). Images that fail either dimension are flagged `needs_upscale = True`. Videos are never checked or upscaled.

2. **Aspect fit check (images and videos):** Check each item's aspect ratio against the profile's target resolution aspect ratio. Items whose aspect ratio does not match (tolerance: ±2%) are flagged for aspect fit treatment (box_zoom or black_overlay per profile setting).

3. **Single-pass ffmpeg normalization per flagged image:** For images that need upscaling and/or aspect fit, both operations are combined into one ffmpeg call (never two separate passes). See §5.8 for filter graph details.

4. **Progress reporting:** The sweep streams progress via SSE on a new endpoint `GET /api/sessions/{id}/sweep-progress`. Frontend shows a "Preparing media..." progress bar before the stitch/zip begins.

5. **Sweep result summary:** After sweep completes, show the user a brief summary panel:
   - "X images upscaled (lanczos / Real-ESRGAN)"
   - "Y items aspect-fit applied"
   - "Z items needed no changes"
   - A "Proceed" button to continue to stitch/zip

   If Real-ESRGAN was selected in the profile but is not configured, show a warning: "Real-ESRGAN not configured — lanczos used instead." Do not block the export.

---

### 5.8 Video Stitching & Upscaling (`stitcher.py` + `upscaler.py`)

**Stitch order:** Items are ordered by their tag's `occurrence_index` (position in script). For duplicate tags (dedupe OFF), items within the same tag group maintain download order.

---

**Upscaler (`upscaler.py`)**

The upscaler is invoked during the Pre-Export Sweep (§5.7 Step 5) for flagged images only. It never touches videos.

*Upscale method selection:*
1. If `profile.upscale_method == "realesrgan"` AND Real-ESRGAN binary is configured and passing health check → use Real-ESRGAN
2. Otherwise → use ffmpeg lanczos (always available)

*Real-ESRGAN path:*
```bash
realesrgan-ncnn-vulkan.exe -i {input_path} -o {output_path} -s 4 -n realesrgan-x4plus
```
- Run with `subprocess`, capture stderr for error detection
- If exit code != 0, log the error and fall back to lanczos for that specific image (non-fatal)
- After Real-ESRGAN produces a 4× upscale, if the result still does not meet `min_resolution`, run one additional lanczos pass to reach exact target (rare edge case)

*Lanczos path (ffmpeg):* Handled inline in the single-pass normalization filter graph below.

---

**Single-Pass Normalization Filter Graphs**

Each kept image goes through exactly one ffmpeg call that handles upscaling + aspect fit + image-to-video conversion simultaneously. Never chain multiple ffmpeg passes on the same file.

The target resolution is always the profile's `resolution` (e.g. `W=1920, H=1080`).

*Case 1 — Box Zoom, image needs upscale:*
```
ffmpeg -loop 1 -i {input} -t {duration} -r 25 \
  -vf "scale={W}:{H}:force_original_aspect_ratio=increase:flags=lanczos,crop={W}:{H}" \
  -c:v libx264 -crf 18 -preset medium clip_{n}.mp4
```
This scales up (lanczos) to cover the frame and crops to exact target size in one filter chain.

*Case 2 — Black Overlay, image needs upscale:*
```
ffmpeg -loop 1 -i black_bg_{orientation}.png \
       -loop 1 -i {input} \
  -filter_complex \
  "[1:v]scale={W}:{H}:force_original_aspect_ratio=decrease:flags=lanczos,pad={W}:{H}:(ow-iw)/2:(oh-ih)/2[scaled]; \
   [0:v][scaled]overlay=(W-w)/2:(H-h)/2[out]" \
  -map "[out]" -t {duration} -r 25 -c:v libx264 -crf 18 -preset medium clip_{n}.mp4
```
The `scale` filter in the overlay chain simultaneously upscales (if needed) and contains the image within the frame. The black background image fills the rest.

*Case 3 — Box Zoom, image already meets min_resolution:*
```
ffmpeg -loop 1 -i {input} -t {duration} -r 25 \
  -vf "scale={W}:{H}:force_original_aspect_ratio=increase,crop={W}:{H}" \
  -c:v libx264 -crf 18 -preset medium clip_{n}.mp4
```

*Case 4 — Black Overlay, image already meets min_resolution:*
Same as Case 2 but without the upscale flag (lanczos is still used internally by ffmpeg for the contain-scale, which is harmless).

*Case 5 — Image already correct resolution AND correct aspect ratio (no changes needed):*
```
ffmpeg -loop 1 -i {input} -t {duration} -r 25 \
  -vf "scale={W}:{H}" \
  -c:v libx264 -crf 18 -preset medium clip_{n}.mp4
```

*Videos:* Videos are not upscaled. They are re-encoded to the target resolution with aspect fit applied using the same box_zoom or black_overlay filter logic as above, but without the `-loop 1` flag and using their natural duration:
- Box zoom: `scale={W}:{H}:force_original_aspect_ratio=increase,crop={W}:{H}`
- Black overlay: same overlay filter graph as Case 2 but input is the video file, not a looped image

*Orientation selection for black background assets:*
- If target W > H → use `black_bg_horizontal.png` / `black_bg_horizontal.mp4`
- If target H > W → use `black_bg_vertical.png` / `black_bg_vertical.mp4`
- If W == H → use `black_bg_horizontal.png` / `black_bg_horizontal.mp4` (square — landscape background is fine)

---

**Final Concat**

After all clips are normalized to individual `clip_{n}.mp4` files in the tmp folder:

Write `concat_list.txt`:
```
file 'clip_001.mp4'
file 'clip_002.mp4'
...
```
Then:
```bash
ffmpeg -f concat -safe 0 -i concat_list.txt -c copy broll_output.mp4
```
Since all clips are already encoded to H.264 at the target resolution by the normalization step, `-c copy` is always safe here. No codec mismatch check needed after normalization.

**Codec settings (all normalization passes):**
- Video: `libx264`, `crf 18`, `preset medium`
- Audio: none (`-an`)
- Container: `.mp4`

---

**ZIP Export**

For the ZIP download, the pre-export sweep produces the normalized image files (upscaled and/or aspect-fit applied) and saves them as images (not video clips) back into the tmp folder with a `_processed` suffix. These processed images — not the originals — are what go into the ZIP. Videos in the ZIP are the originals (no upscale). All files in the ZIP are renamed:

```
001_space_marine.jpg          ← image (processed)
002_ultramarines.mp4          ← video (original)
003_chaos_warp_storm.jpg      ← image (processed)
```

Number prefix = stitch order. Suffix = the search tag word (spaces replaced with underscores, lowercased).

---

### 5.9 Missing Tags Export

At the end of any download session where ≥ 1 tag returned 0 results:
- Show a collapsible "Missing Tags" panel on the preview page
- List: tag word + sources searched
- "Export as .txt" button → `missing_tags_{timestamp}.txt`

Format:
```
B-Roll Engine — Missing Tags Report
Session: 2025-06-17 14:32
Profile: Warhammer 40K

Tags with no results:
- horus heresy  (searched: Pexels, Local Warhammer Folder, SerpAPI)
- primarch      (searched: Pexels, Local Warhammer Folder)
```

---

### 5.10 Adapter Documentation Page (`/docs/adapter`)

In-app page with full markdown rendering of `CUSTOM_ADAPTER_GUIDE.md`. Sections:
1. Overview of the adapter protocol
2. Required endpoints (with copy-pasteable curl examples)
3. Full Python (Flask) example adapter
4. Full Node.js (Express) example adapter
5. Minimal shell script example
6. Quality metadata tips
7. Troubleshooting

---

## 6. API Routes (FastAPI)

```
GET  /api/profiles                         List profiles
POST /api/profiles                         Create profile
GET  /api/profiles/{id}                    Get profile
PUT  /api/profiles/{id}                    Update profile
DELETE /api/profiles/{id}                  Delete profile

GET  /api/profiles/{id}/tags               List profile tags
POST /api/profiles/{id}/tags               Add tag word
DELETE /api/profiles/{id}/tags/{tag_id}    Remove tag word

GET  /api/sources                          List sources
POST /api/sources                          Create source
PUT  /api/sources/{id}                     Update source
DELETE /api/sources/{id}                   Delete source
POST /api/sources/{id}/test                Test source connectivity

GET  /api/global-tags                      List global tags
POST /api/global-tags                      Add global tag
DELETE /api/global-tags/{id}              Remove global tag

GET  /api/llm-providers                    List LLM providers
POST /api/llm-providers                    Add provider
PUT  /api/llm-providers/{id}               Update provider
DELETE /api/llm-providers/{id}            Delete provider

POST /api/sessions                         Create session (script analysis starts)
GET  /api/sessions/{id}                    Get session state
PUT  /api/sessions/{id}/tags               Update tag list (after user edits)
POST /api/sessions/{id}/download           Start download job
GET  /api/sessions/{id}/progress           SSE stream for download progress
PUT  /api/sessions/{id}/curation           Update kept/dropped status of items
POST /api/sessions/{id}/sweep              Trigger pre-export upscale/aspect-fit sweep
GET  /api/sessions/{id}/sweep-progress     SSE stream for sweep progress
POST /api/sessions/{id}/export/zip         Trigger ZIP creation → returns download URL
POST /api/sessions/{id}/export/video       Trigger ffmpeg stitch → returns download URL
DELETE /api/sessions/{id}                  Clean up tmp folder

GET  /api/library/sources                  List local_folder sources
GET  /api/library/{source_id}/files        List files in local folder (paginated)
GET  /api/library/{source_id}/files/{uid}  Get file metadata
POST /api/library/{source_id}/files/{uid}/tag  Save tags for a file
GET  /api/library/preview/{source_id}/{filename}  Serve file for preview

GET  /api/settings                         Get app settings
PUT  /api/settings                         Update app settings

GET  /api/docs/adapter                     Serve adapter guide markdown
```

---

## 7. Error Handling

- All API errors return `{ "error": "...", "detail": "..." }` with appropriate HTTP status
- Download failures per item are non-fatal: item is marked `status: "failed"` and skipped
- If all items fail for a tag, that tag is added to `missing_tags`
- ffmpeg errors surface as a session `status: "error"` with `error_message` field
- LLM provider failures cascade to next provider in priority order; final fallback is algorithmic
- Playwright scraper failures (blocked, timeout) are caught, logged, and the source is marked as `unreachable` for that session (not globally disabled)

---

## 8. Windows-Specific Considerations

- All file paths use `pathlib.Path` — never string concatenation with `/` or `\`
- `tmp/` folder is created relative to the app's working directory (not system temp) for predictability
- ffmpeg binary: check `bin/ffmpeg.exe` first, then `where ffmpeg` on PATH
- Real-ESRGAN binary: user-supplied path only (not bundled); app checks at startup if path is set and binary is executable; if check fails, silently falls back to lanczos and shows a warning badge in Settings
- Playwright on Windows: use `chromium` browser, `--no-sandbox` flag
- File rename on Windows: rename must handle `PermissionError` if file is open in another process — retry up to 3 times with 500ms delay
- Long paths: ensure app directory is not deeply nested to avoid 260-char MAX_PATH issues

---

## 9. V1 Explicit Out-of-Scope Items

The following are documented as future features and must NOT be implemented in V1:

- Video transitions (crossfade, wipe, etc.)
- Ken Burns / pan-zoom on images
- Background music/audio track
- Session persistence / project save-and-reopen
- User authentication
- Cloud storage integration
- Multi-user support
- Subtitle/transcript overlay
- Scheduled or batch processing
- Browser extension

---

## 10. Non-Functional Requirements

- App must start cold in < 5 seconds on a modern Windows machine
- Script analysis (algorithmic) must complete in < 3 seconds for scripts up to 5,000 words
- Download phase streams progress in real-time (no full-page reload)
- Video stitch for 20 clips at 1080p must complete in < 60 seconds on a machine with ffmpeg hardware acceleration available
- Tmp folder cleanup must run reliably on session end even if the user closes the browser tab (use FastAPI lifespan events + a cleanup-on-next-start sweep for orphaned tmp folders older than 24h)
- All user-facing text in English
- No telemetry, no network calls except to configured sources and LLM providers

---

## 11. Implementation Order for Agent

Build in this sequence to keep each phase independently testable:

1. **Project scaffold** — FastAPI app, SQLite + SQLAlchemy models, Alembic migrations, React + Vite frontend wired to FastAPI, `start.bat`
2. **Settings + LLM providers** — CRUD for LLM providers and global tags
3. **Sources CRUD** — All source types, source test endpoint
4. **Profile CRUD** — Profile editor with tags panel and source assignment
5. **Algorithmic analyzer** — spaCy integration, fuzzy matching with rapidfuzz, tag extraction pipeline
6. **LLM analyzer** — Provider cascade, prompt builder, JSON response parser
7. **Source adapters** — Pexels, Pixabay, Unsplash (API), SerpAPI scraper, Playwright scraper, local folder reader, custom adapter relay
8. **Download orchestrator** — Per-tag source search, quality scoring, best-item selection, tmp folder management, SSE progress
9. **Dashboard session flow** — All 5 steps (setup → tag review → download → curation → export)
10. **Video stitcher** — ffmpeg pipeline, single-pass normalization filter graphs (all 5 cases), box_zoom mode, black_overlay mode, image-to-clip conversion, concat
11. **Upscaler** — resolution check sweep, Real-ESRGAN integration (with lanczos fallback), pre-export sweep SSE progress, sweep summary UI, ZIP processed-image export naming
12. **Library tagger** — Local folder browser, media viewer, tagging UI, rename + sidecar write, new word prompt
13. **Adapter docs page** — Markdown renderer, bundled guide
14. **Polish** — Error states, loading states, missing tags export, cleanup sweep

