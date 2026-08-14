# B-Roll Engine — User Guide

B-Roll Engine is a locally-hosted web app that turns a video script (or a plain list of search terms) into a curated folder of B-roll images and video clips, pulled from whatever media sources you configure — stock APIs, a Google Image scraper, your own custom scrapers, or your own local media library.

Everything runs on your machine at `http://127.0.0.1:7420`. Nothing is uploaded anywhere except the search/download requests you configure to your own sources and, optionally, an LLM provider for tag extraction.

---

## 1. Setup

### 1.1 First-time install

From the project folder (`D:\yt_vids\automation ecosystem\BRollGen`):

1. Run `install.bat` once. This creates a Python virtual environment (`.venv`), installs backend dependencies, and installs frontend dependencies.
2. Run `start.bat` any time you want to launch the app. It will:
   - Apply any pending database migrations (`alembic upgrade head`)
   - Rebuild the frontend (`npm run build`) so your browser always has the latest UI
   - Start the backend at `http://127.0.0.1:7420` and open it in your default browser

You don't need to keep a terminal for the frontend separately — the built frontend is served directly by the FastAPI backend in production mode (`start.bat`'s flow). If you're actively developing the frontend, you can instead run the Vite dev server (`npm run dev` in `frontend/`) which proxies API calls to the backend.

### 1.2 ffmpeg

You do not need ffmpeg installed for anything in the current app. B-Roll Engine does not do any video processing (no stitching, no re-encoding, no upscaling) — it only downloads and exports files as-is. An earlier version had ffmpeg/Real-ESRGAN options in Settings for a video-stitching pipeline; that pipeline and its UI were removed (see §4 and §8).

### 1.3 Custom scraper adapters (optional)

If you're using any `custom_adapter` sources (see §5), those run as separate small server processes. You can either start them manually, or configure each one with an **Adapter Script Path** in the Sources page so B-Roll Engine launches them for you automatically whenever you select a profile that uses them (see §5.4).

The bundled example adapters (Warhammer 40K gallery, Artvee, Library of Congress) live in `CustomAdapters/wh40k/` and run on ports 3000, 3001, and 3002 respectively.

---

## 2. The Session Workflow (Dashboard)

The Dashboard (`/`) is where you actually generate B-roll. It's a 5-step wizard: **Setup → Tags → Download → Review → Export**.

### Step 1 — Setup

Pick a **Niche Profile** first (see §4 for what a profile is and how to create one). Selecting a profile:
- Pre-fills the item count (N) from the profile's default
- Automatically attempts to start any custom adapters linked to that profile (silent — check your browser console if you want to see the result; a failed auto-start never blocks you from continuing)

Then choose an **Input Mode**:

- **📄 Script Analysis** — paste your full video script into the textarea. B-Roll Engine will scan it and automatically extract N search tags (see §6 for exactly how). You also set:
  - **Item Count (N)** — how many tags/B-roll items you want, defaults to the profile's default
  - **Analysis Method** — Algorithmic (spaCy, fast, offline, no API cost) or LLM (calls your configured LLM provider first, falls back to spaCy if it fails)
  - **Allow Duplicate Tags** toggle — off by default. When off, if the same word appears multiple times in your script it only becomes one tag. When on, each occurrence becomes its own tag slot (the downloader will try to find that many *distinct* files for that word, reusing the best match if it can't find enough).

- **🏷️ Direct Tag List** — skip script analysis entirely. Type or paste your search terms directly, one per line (or comma-separated). This is the fastest path if you already know exactly what you want to search for and don't need automatic extraction. Click "Show example" for a sample list and format hint.

Click **Analyze Script** (or **Use N Tags →** in Direct Tag List mode) to move to Step 2.

### Step 2 — Tag Review

Shows every extracted (or typed) tag as a chip, labeled by where it came from (PRO = profile wordlist, GLO = global wordlist, NLP = spaCy, LLM = language model, MAN = manually added). You can:
- Remove any tag
- Add new tags manually
- (Tags can't be reordered or edited in place here — remove and re-add if you need to fix a word)

The count must reach your item count N before "Proceed to Download" is enabled. If script analysis came up short, add the remaining tags manually here.

### Step 3 — Download

A progress bar and live status line stream in real time over Server-Sent Events. The status line shows exactly what's happening, e.g.:

```
Searching: "emperor" (1 of 8)
Downloading: "emperor" from loc.gov (1 of 8)
```

This updates continuously as the download orchestrator works through each tag against every enabled, profile-linked source. You'll automatically advance to Step 4 once the session status becomes `awaiting_review`.

### Step 4 — Review

A grid of every downloaded item. Click any card to toggle it between **Keep** and **Drop** — dropped items are excluded from export but not deleted from disk until the session is cleaned up. "Keep All" / "Drop All" buttons are available for bulk changes.

If the profile has **Redundant Source Download** turned on (§4), instead of one flat grid you'll see items grouped by tag, with one card per source that returned a result for that tag — so you can compare and pick the best version(s) per tag rather than getting only the single globally-best pick.

If any tags returned zero results across every source, a red "Missing tags" panel appears with an **Export as .txt** button that downloads a plain-text report.

Click **Proceed to Export** (disabled if you've dropped every item).

### Step 5 — Export

Two independent export buttons — you can use either or both:

- **📦 Download ZIP** — the standard export. Files are zero-padded and numbered in script order, with the tag appended: `001_space_marine.jpg`, `002_ultramarines.mp4`, etc.
- **🎬 Export for VideoStitch** — a second ZIP intended for a separate VideoStitch application. Same content, same script-order numbering, but **without** zero-padding: `1_space_marine.jpg`, `10_ultramarines.mp4`, `100_chaos_warp.gif`.

Both exports use the files exactly as downloaded — B-Roll Engine does not resize, crop, upscale, or re-encode anything. What you download is what your sources gave you.

When you're done with a session, you can discard it (its `tmp/<session_id>/` folder is cleaned up automatically after 24 hours by a startup sweep, or immediately via `DELETE /api/sessions/{id}` if you build that into a workflow — there's currently no "delete session" button in the Dashboard UI itself, so orphaned session folders age out on their own).

---

## 3. Media Sources (`/sources`)

Sources are where B-Roll Engine actually pulls media from. Configure them once here, then attach the ones you want to each Niche Profile.

| Type | What it is | Config fields |
|---|---|---|
| **Pexels** | Pexels stock API | API Key |
| **Pixabay** | Pixabay stock API | API Key |
| **Unsplash** | Unsplash stock API | Access Key |
| **SerpAPI / Playwright** | Google Images — via SerpAPI if you have a key, otherwise a Playwright-driven scraper of Google Image search | SerpAPI Key (optional), Max results per query |
| **Custom Adapter** | Your own HTTP server implementing the adapter protocol (see §5) | Adapter Base URL, Auth Token (optional), Adapter Script Path — typed or uploaded (optional, for auto-launch) |
| **Local Folder** | A folder of your own media, uploaded into the app | Upload area (drag-and-drop or Browse Folder), Enabled file extensions (optional filter) |

Every source (except Local Folder, which has no network calls) has a **Request Delay** setting: leave it blank for a randomized 2–30 second delay between consecutive requests to that source (a reasonable default to avoid rate limits), set it to `0` to disable the delay entirely, or set a fixed number of seconds.

Each source card shows a live enabled/disabled indicator and its configured delay. Click **Edit** to change settings, and once a source is saved you can click **Test Connection** to verify it's reachable — this calls the source's health/connectivity check without doing a real search.

**Local Folder sources take an upload, not a typed path.** Older versions of the app expected a Windows path to a folder already sitting on the machine running the backend — that broke down the moment the backend ran somewhere else (a WSL/Linux shell, a Docker container) instead of directly on your Windows machine. Now you upload the files themselves: click **+ Add Source**, choose **Local Folder**, give it a **Name**, and click **Save** — the source needs to exist (get an ID) before the upload area unlocks, so on a brand-new source you'll see a one-line prompt telling you to save first. Once saved, drag a folder from Windows Explorer straight onto the upload area, or click **Browse Folder…** to pick one through the native folder picker; either way every file inside (including nested subfolders) gets uploaded. Files are stored flat inside the app once uploaded — subfolder names aren't preserved — because the local-folder search itself only ever looks at files directly inside the source's folder, never recursing into subfolders, so keeping the nesting around wouldn't do anything useful. Re-uploading adds to the existing library rather than replacing it; same-name files are kept as separate copies (never silently overwritten), and a **Clear library** link appears once there's something to clear. Existing tags and sidecar `.json` files created through the Local Library page (§9) live inside this same uploaded folder and survive re-uploads of other files. If you want a clean replace instead of a merge, click **Clear library** before uploading the new folder.

**Deleting a source cleans up its uploaded files too.** For a Local Folder source, deleting it removes the source's entire uploaded media library from disk; for a Custom Adapter source with an uploaded (not manually-pathed) adapter script, deleting it removes that uploaded script file too. Both live in an app-managed directory keyed by the source's ID, and deleting the source takes that whole directory with it — nothing is left behind to accumulate on disk. (If a file happens to be open in another program at that exact moment, the source itself still deletes successfully; only the on-disk cleanup can fail, and it fails silently rather than blocking the delete — you'd need to remove that one file by hand in that rare case.)

---

## 4. Niche Profiles (`/profiles`)

A **Niche Profile** bundles together: which sources to search, your custom wordlist of tags, and a handful of download behavior toggles. You'll typically make one profile per recurring content theme (e.g. "Warhammer 40K", "Nature Documentary", "Tech Reviews").

### Creating a profile

Click **+ New Profile**, then fill in:

**Basic Info**
- **Name** (required, must be unique) and optional **Description**
- **Default Item Count (N)** — pre-fills the Dashboard's item count when this profile is selected

(Earlier versions of this app also had Output Resolution, Min Resolution, Aspect Fit, and Upscale Method fields here, left over from a video-stitching/upscaling pipeline that was removed. Those fields did nothing — B-Roll Engine only ever downloads and exports files as-is — so they were removed from both the editor and the database. If you're reading an older doc or screenshot that shows them, they no longer exist.)

**Behaviour**
- **Multi-item per tag** (default ON) — download the single best-quality result across all sources for each tag. Turn this OFF to instead collect every result from every source for that tag (more items, more variety, but much larger download volume).
- **Deduplicate repeated tags** (default ON) — the profile-level default for the "Allow Duplicate Tags" toggle you see per-session on the Dashboard. A session can override this.
- **Redundant Source Download** (default OFF) — when ON, ignores the multi-item/dedupe logic above and instead downloads the best-1 result from **every enabled source** for each tag, so you get one candidate per source per tag rather than one globally-best pick. The Review step (§2, Step 4) automatically switches to a grouped-by-tag layout when this is on. Useful when you want to compare quality/style across sources rather than trust the automatic scorer.
- **Enable LLM tag extraction** — whether this profile is allowed to use an LLM provider for script analysis (only relevant if you choose "LLM" as the analysis method for a session).

**Profile Tags**

Your profile's own wordlist — see §6 for exactly how these are used in tag extraction. You can add words one at a time, or **Import CSV / TXT** a whole list at once (see §7 for the exact file format).

**Sources**

Check the boxes for every source this profile should search. There's no explicit priority-ordering UI beyond selection order at save time, but internally sources are searched in the order you selected them (lower priority number = searched first) — every enabled source is always searched for every tag; priority only affects consistent ordering, since the app always compares results across all sources rather than stopping at the first hit.

Click **Save Profile**. Existing profiles can be edited or deleted from the profile list (deleting a profile also removes its tags and source links).

---

## 5. Registering New Custom Adapters

A custom adapter is your own small HTTP server that implements a three-endpoint protocol (`/health`, `/search`, `/download`). This is how you plug in a private stock library, an internal media CDN, or a hand-written scraper for a site the built-in sources don't cover.

The full protocol spec, with copy-pasteable Python/Flask, Node/Express, and shell examples, plus guidance on the persistent-Playwright-browser pattern used by the bundled adapters and how to Dockerize your own, lives in `docs/CUSTOM_ADAPTER_GUIDE.md` — it's also served in-app at **Adapter Docs** in the sidebar (`/docs/adapter`). This section covers the app-side registration steps only.

### 5.1 The protocol, in brief

Your server must implement:

- `GET /health` → `{"status": "ok", "name": "...", "version": "..."}`
- `GET /search?q={query}&limit={n}&media_type={image|video|any}` → `{"results": [{...}]}` — each result needs at minimum `id`, `media_type`, `download_url`; `width`, `height`, `file_size_bytes`, `preview_url`, `title` are optional but improve quality ranking
- `GET /download?id={id}` → streams the binary file (only called if `download_url` isn't already a direct file URL)

If you set an Auth Token in the source config, B-Roll Engine sends `Authorization: Bearer <token>` on every request — validate it in your server.

### 5.2 Registering it as a Source

1. Go to **Sources** → **+ Add Source**.
2. Set **Type** to `Custom Adapter`.
3. Give it a **Name** and click **Save** — the source needs an ID before the script upload option below unlocks.
4. Fill in **Adapter Base URL** (e.g. `http://localhost:8080`) and, if your adapter checks it, an **Auth Token**.
5. Optionally set **Adapter Script Path** — either type an existing path directly, or drag your `.py` file onto the upload area / click **Browse File…** to upload it (the app saves it under a managed `CustomAdapters/uploaded/` folder and fills the path in for you automatically). Either method works the same way for auto-launch — see §5.4.
6. Click **Test Connection** to confirm your `/health` endpoint responds.

### 5.3 Attaching it to a Profile

A registered source does nothing until a profile uses it. Open (or create) a Niche Profile, check the box for your new custom adapter source under **Sources**, and save.

### 5.4 Auto-launch on profile selection

If you set **Adapter Script Path** to the full path of your adapter's Python entry-point script, B-Roll Engine will automatically try to start it whenever you select a profile that uses it: it health-checks first, and only launches a subprocess if the health check fails. It polls for up to 10 seconds; if your adapter still isn't healthy after that, session setup is never blocked — you'll just need to start it manually and your source will simply return no results until it's up. This is a local-only convenience; it has no effect when the app runs under Docker (see §5.5).

### 5.5 Running your adapter in Docker

If you deploy the whole app with `docker-compose` (see `DOCKER_SETUP.md`), each adapter should run as its own container, and you'll need to switch its `adapter_url` in the Sources UI from `http://localhost:PORT` to its Compose service name (e.g. `http://adapter-myadapter:PORT`), since containers can't reach each other via `localhost`. The bundled adapters' `Dockerfile` pattern (one image, parameterized by an `ADAPTER_SCRIPT` build arg) is documented in `docs/CUSTOM_ADAPTER_GUIDE.md` §11 if you want to package your own adapter the same way.

---

## 6. How the Tag System Works

"Tags" are just search terms — the words or short phrases that get sent to your sources' `/search` endpoints. There are two ways to produce them: **Script Analysis** (automatic extraction from a script) and **Direct Tag List** (you type them yourself and skip extraction entirely — see Dashboard §2, Step 1).

When you use Script Analysis, the extraction pipeline runs in this order, stopping as soon as it has N tags:

1. **Profile wordlist scan.** Your profile's own tag list (§4) is fuzzy-matched against the script text (using rapidfuzz, ~85% similarity threshold) — so close misspellings or slight variations still match. Matches are recorded in the order they first appear in the script.
2. **Global wordlist scan.** If the profile wordlist alone doesn't reach N tags, the app fuzzy-matches your **Global Word List** (Settings page, §8) against the script the same way, to fill remaining slots.
3. **LLM or algorithmic fallback**, depending on your chosen Analysis Method:
   - **LLM primary**: sends your script, your profile wordlist, and your global wordlist to your configured LLM provider (cascading through providers by priority if one fails — see §8) with a prompt asking for exactly N concrete, visual, filmable tags, ordered by first appearance. If every LLM provider fails, it falls back to the algorithmic method below.
   - **Algorithmic primary**: never calls an LLM at all. Instead runs spaCy (`en_core_web_sm`) named-entity recognition and noun-chunk extraction over the script, scores each candidate (+2 if it fuzzy-matches the profile wordlist, +1 for the global wordlist, +1 for being a named entity, +0.5 for being a noun chunk), deduplicates by lemma, and takes the top N by score (ties broken by first appearance).
4. **Manual fill.** If the pipeline still comes up short of N (rare, but possible for very short or abstract scripts), you finish the count yourself in the Tag Review step (§2, Step 2) — the UI shows exactly how many more you need.

**Duplicate handling:** if "Allow Duplicate Tags" is off (the default), a word that appears multiple times in the script only produces one tag. If it's on, each occurrence becomes its own tag slot, and during download the app tries to find that many *distinct* files for that word across your sources — reusing the best-available file to fill any slot it can't find a unique match for.

Whichever method fills a tag, the Tag Review chip shows a 3-letter source label so you always know where each tag came from: `PRO` (profile wordlist), `GLO` (global wordlist), `NLP` (spaCy), `LLM` (language model), or `MAN` (you typed it manually).

---

## 7. Writing New Tag Files

Both the **Profile Tags** panel (Profiles page) and the **Global Word List** (Settings page) support importing a wordlist from a file instead of typing entries one at a time, via their **Import CSV / TXT** buttons.

The parser accepts two formats and auto-detects which one you gave it:

- **Plain text (`.txt`)** — one tag per line:
  ```
  space marine
  ultramarines
  chaos warp storm
  primarch
  ```
- **CSV (`.csv`)** — only the **first column** of each row is used; extra columns are ignored:
  ```
  space marine,notes,whatever
  ultramarines,,
  chaos warp storm
  ```

Detection rule: if *any* line in the file contains a comma, the whole file is parsed as CSV (first column only per row); otherwise it's treated as one-tag-per-line plain text. So don't mix a comma into a `.txt`-style file unless you intend the whole thing to be read as CSV.

Other parsing rules that apply to both formats:
- Every entry is lowercased and whitespace-trimmed automatically — you don't need to pre-format casing.
- Blank lines are skipped.
- A UTF-8 byte-order-mark (BOM), which some spreadsheet programs add when exporting CSVs, is stripped automatically.
- Duplicates against your existing list (profile-scoped for Profile Tags, global for the Global Word List) are silently skipped, not added twice — the import result tells you how many were **added** vs. **skipped**.

There's no fixed line/row limit; import as large a list as you want.

---

## 8. Settings (`/settings`)

### Analysis
- **Analysis Method** — the app-wide default for script analysis (Algorithmic or LLM-primary), overridable per session on the Dashboard.

(The ffmpeg Path and Real-ESRGAN Binary Path fields that used to sit here have been removed — they belonged to the same removed video-stitching/upscaling pipeline mentioned in §4. Real-ESRGAN's Test button, in particular, was calling a backend endpoint that no longer exists.)

### LLM Providers

Add one or more providers that script analysis can call when Analysis Method is set to LLM. Supported provider types: `openai`, `anthropic`, `gemini`, `ollama`, `custom`. Each has a Label, API Key, optional Base URL (required for `ollama`/`custom`), Model name, a Priority (lower number = tried first), and an Enabled toggle. If multiple providers are enabled, the app tries them in priority order and falls through to the next on failure; if all fail, it falls back to the algorithmic (spaCy) method automatically so a session never hard-fails just because an LLM call didn't work.

API keys are currently stored as plain text in the local SQLite database (`# SECURITY: api_key stored as plain text in v1 — encrypt in v2` is a known, intentional limitation noted in the codebase for a future version) — this is fine for a single-user local app but worth knowing if you ever share the database file.

### Global Word List

A supplementary tag list used as the second pass in tag extraction (§6), after any given profile's own wordlist is exhausted. Add words individually or import a file (§7) — the same **Import CSV / TXT** button and parsing rules apply here as on the Profiles page.

---

## 9. Local Library (`/library`)

The Local Library tagger lets you preview, tag, and manage your own personal media collection stored on a `local_folder` source (registered and uploaded on the Sources page first — see §3). The page is a single top-to-bottom flow:

1. **Source picker** — at the top, pick which uploaded `local_folder` library to browse. Only sources with at least one file uploaded will show anything below.
2. **Preview** — the currently selected file's image (or GIF) renders directly; video files get a playable, looping `<video>` player with controls.
3. **Controls, directly under the preview:**
   - **← Prev / Next →** step sequentially through every file in the library without going back to the card grid.
   - The **tag chips** row shows the tags currently applied to the selected file — click a chip's ✕ to remove it.
   - **Niche Profile tag buttons** — pick a profile from the **Niche Profile** dropdown (the same profiles you build on the Profiles page, §4) and a row of buttons appears below it, one per tag word in that profile's wordlist. Click a button to add that tag to the file; click it again to remove it (the button highlights while active) — a quick way to tag using a niche's existing vocabulary without typing.
   - The **free-text tag box** underneath is the fallback for anything the selected profile's buttons don't cover — type a word and press Enter or comma to add it as a chip, exactly like before.
   - A **Quality Grade** picker: U (ultra) / H (high) / M (medium) / L (low) / none.
   - **Save Tagged Name** writes a sidecar `.json` file next to the media file recording its tags, quality grade, media type, and original filename, and renames the file on disk to match the tagging convention. Your folder structure otherwise stays intact.
   - **Delete** permanently removes the currently selected file (and its sidecar, if any) from disk — you'll be asked to confirm first.
   - If you typed (or clicked) any tag word that isn't already in the Global Word List, a **New Tags Detected** modal pops up after saving, letting you add those new words straight to the Global Word List (or skip — the tag still applies to the file either way).
4. **File grid** — below the controls, every file in the library appears as a small card: a thumbnail filling about 70% of the card (images/GIFs render directly; videos show a 🎬 placeholder), with the filename and a small red ✕ delete button in the remaining strip. An **Untagged** badge marks anything that hasn't been tagged yet. Click any card to load that file into the preview and controls above.
5. **Upload more files** — the same drag-and-drop-or-browse upload area used elsewhere in the app (§3.4) lets you add more files to the currently selected library at any time, without leaving the page.
6. **Download Folder** — at the very bottom, downloads a ZIP of every media file currently in the selected library, using each file's current (already tag-renamed) filename. Sidecar `.json` files aren't included — the tags travel as part of the filename itself. Disabled until the library has at least one file.

When a `local_folder` source is searched during a normal download session, it reads these sidecar files (and falls back to fuzzy-matching filenames if a sidecar is missing) to find matches for each tag, ranked by quality grade first and file size second.

---

## 10. Quick Reference — Everything at a Glance

| Page | What you do there |
|---|---|
| **Dashboard** (`/`) | Run a session: paste a script or type tags → review extracted tags → watch download progress → curate results → export a ZIP |
| **Profiles** (`/profiles`) | Define a reusable bundle of sources + tag list + download behavior toggles |
| **Sources** (`/sources`) | Configure the actual media backends (stock APIs, scrapers, custom adapters, local folders) |
| **Local Library** (`/library`) | Browse and tag your own local media folders so they can be searched as a source |
| **Settings** (`/settings`) | App-wide LLM providers, global tag list, analysis method default |
| **Adapter Docs** (`/docs/adapter`) | In-app copy of `docs/CUSTOM_ADAPTER_GUIDE.md` — protocol reference for writing your own adapters |

---

## 11. Troubleshooting Quick Hits

- **A session's tag count won't reach N.** Your profile/global wordlists and the automatic extraction method didn't find enough matches — add the rest manually in the Tag Review step, or lower N for that session.
- **A tag returned zero results.** Check the Missing Tags panel in the Review step — it lists exactly which tags failed and lets you export a `.txt` report. Try broadening that tag's wording, enabling more sources on the profile, or checking whether a relevant custom adapter is actually running.
- **A custom adapter source keeps failing / "All connection attempts failed."** This just means nothing is listening on the adapter's URL yet — **Test Connection is a plain health-check GET request, it never starts anything.** The app only auto-launches an adapter when you pick that source's profile from the Dashboard's profile dropdown (and only if **Adapter Script Path** is set — type it or upload the `.py` file on the Sources page, see §5.4). To debug a launch problem directly, run the script yourself first and watch its output: `.venv\Scripts\python.exe CustomAdapters\uploaded\<source_id>\<script>.py` (or wherever it lives) — this surfaces real startup errors that auto-launch would otherwise hide, since a failed/timed-out auto-launch just logs a warning and moves on rather than blocking session setup. Once you see it bind to its port, Test Connection (or just running the session) should succeed.
- **Adapter URL: `localhost` vs. Docker service name.** A custom adapter source's **Adapter Base URL** must match how you're currently running the app: `http://localhost:<port>` when running natively (`start.bat`), or `http://<compose-service-name>:<port>` (e.g. `http://adapter-wh40k:3000`) when running under `docker-compose` — `localhost` inside the `app` container refers to the `app` container itself, not its sibling adapter containers. See `DOCKER_SETUP.md`'s "Adapter URLs" section for the full table. Switching between native and Docker means switching this URL back and forth to match.
- **Downloads seem slow.** That's very likely the intentional per-source rate-limit delay (§3) doing its job to avoid hammering a source's rate limits — set it lower (or to `0`) on the Sources page if you're confident the source can handle it.
- **I don't see any upscaling/resizing/video-stitching options working.** Correct — that subsystem was removed from the app. Downloads are exported exactly as received from the source; see the profile Basic Info note in §4.
- **A local_folder source's upload area is greyed out.** It needs a saved source ID first — enter a Name, click Save, then the upload area unlocks. See §3.
