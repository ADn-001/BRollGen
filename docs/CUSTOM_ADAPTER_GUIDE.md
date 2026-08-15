# B-Roll Engine — Custom Adapter Guide

## 1. What is a Custom Adapter?

A custom adapter is a lightweight HTTP server (written in any language) that B-Roll Engine calls to search for and download media. The engine acts as the client: it sends search queries to your adapter and downloads the results. You own the server and can point it at any data source — a private stock library, an internal CDN, a web scraper, or any other media collection.

---

## 2. Protocol Reference

### `GET /health`

Liveness check. The engine calls this when you click "Test Connection" in the Sources UI, and also whenever a niche profile using your adapter is selected on the Dashboard (see §9, Auto-Launch).

**Response (200):**
```json
{ "status": "ok", "name": "My Custom Source", "version": "1.0" }
```

---

### `GET /search?q={query}&limit={n}&media_type={image|video|any}`

Search for media matching `q`. Return up to `limit` results.

| Parameter    | Type   | Required | Description                        |
|-------------|--------|----------|------------------------------------|
| `q`         | string | yes      | Search query                       |
| `limit`     | int    | yes      | Max results to return              |
| `media_type`| string | no       | `"image"` / `"video"` / `"any"`    |

**Response (200):**
```json
{
  "results": [
    {
      "id": "unique_string",
      "title": "Optional description",
      "media_type": "image",
      "preview_url": "https://example.com/thumb.jpg",
      "download_url": "https://example.com/full.jpg",
      "width": 1920,
      "height": 1080,
      "duration_seconds": null,
      "file_size_bytes": 204800,
      "source_page_url": "https://example.com/item/123"
    }
  ]
}
```

All fields except `id`, `media_type`, and `download_url` are optional but improve quality scoring.

---

### `GET /download?id={id}`

Stream the binary file with the correct `Content-Type` header.

If `download_url` in the search result is a direct file URL, B-Roll Engine will download it directly without calling this endpoint.

---

## 3. Quality Metadata Tips

The engine ranks candidates by `quality_score`:
- **Images:** `width × height` (higher = better)
- **Videos:** `width × height` (bitrate is not read at search time)
- **Fallback:** `file_size_bytes × 0.001` when width/height are unavailable
- **Zero score:** if all three are absent, the candidate scores `0.0` and will always lose to any source that returns dimensions

Return `width`, `height`, and `file_size_bytes` whenever possible for accurate ranking.

### When your search API doesn't return dimensions

Some sources (e.g. the Library of Congress) only expose dimensions at item-fetch time, not in search results. If you return `null` for `width`, `height`, and `file_size_bytes`, your adapter's results will always score `0.0` and be eliminated by any competing source that does return dimensions — even if your actual images are higher quality.

Two ways to handle this:

**Option A — Use a placeholder in your search response.** If you know the typical resolution of your source's images, return a representative value directly in the search JSON. For example, if your source typically serves 3000×2000 images, return `"width": 3000, "height": 2000` as a static default. The engine will replace these with the real dimensions after the file is downloaded.

**Option B — Set "Default Quality Score" in the Sources UI.** Without any code changes in your adapter, open Sources → your custom adapter → set the **Default Quality Score** field to a numeric value. The engine applies this as a fallback score for any candidate that computes to `0.0` (i.e. all three metadata fields are absent). Use the following as reference points when choosing a value:

| Reference point | Approximate score |
|---|---|
| Pexels typical full-res (5472×3648) | ~20,000,000 |
| Pixabay typical full-res (3840×2160) | ~8,300,000 |
| LOC placeholder (3000×2000) | 6,000,000 |
| Pexels compressed preview (800×530) | ~424,000 |

Option A is preferred when you can do it — it's self-contained in the adapter. Option B is the no-code fix for adapters you can't or don't want to modify.

---

## 4. Python Example (Flask)

```python
from flask import Flask, jsonify, request, send_file
import requests, io

app = Flask(__name__)

LIBRARY = [
    {"id": "001", "title": "Mountain sunrise", "media_type": "image",
     "url": "https://picsum.photos/id/10/1920/1080", "width": 1920, "height": 1080, "size": 512000},
    {"id": "002", "title": "Ocean waves", "media_type": "image",
     "url": "https://picsum.photos/id/15/1920/1080", "width": 1920, "height": 1080, "size": 480000},
]

@app.route("/health")
def health():
    return jsonify({"status": "ok", "name": "Flask Example Adapter", "version": "1.0"})

@app.route("/search")
def search():
    q = request.args.get("q", "").lower()
    limit = int(request.args.get("limit", 10))
    results = [
        {"id": item["id"], "media_type": item["media_type"],
         "download_url": item["url"], "preview_url": item["url"],
         "width": item["width"], "height": item["height"],
         "file_size_bytes": item["size"], "title": item["title"]}
        for item in LIBRARY if q in item["title"].lower()
    ]
    return jsonify({"results": results[:limit]})

@app.route("/download")
def download():
    item_id = request.args.get("id")
    item = next((i for i in LIBRARY if i["id"] == item_id), None)
    if not item:
        return jsonify({"error": "not found"}), 404
    data = requests.get(item["url"]).content
    return send_file(io.BytesIO(data), mimetype="image/jpeg",
                     download_name=f"{item_id}.jpg")

if __name__ == "__main__":
    app.run(port=8080)
```

---

## 5. Node.js Example (Express)

```javascript
const express = require("express");
const axios = require("axios");
const app = express();

const LIBRARY = [
  { id: "001", title: "Mountain sunrise", mediaType: "image",
    url: "https://picsum.photos/id/10/1920/1080", width: 1920, height: 1080, size: 512000 },
  { id: "002", title: "Ocean waves", mediaType: "image",
    url: "https://picsum.photos/id/15/1920/1080", width: 1920, height: 1080, size: 480000 },
];

app.get("/health", (req, res) => {
  res.json({ status: "ok", name: "Express Example Adapter", version: "1.0" });
});

app.get("/search", (req, res) => {
  const q = (req.query.q || "").toLowerCase();
  const limit = parseInt(req.query.limit) || 10;
  const results = LIBRARY
    .filter(item => item.title.toLowerCase().includes(q))
    .slice(0, limit)
    .map(item => ({
      id: item.id, media_type: item.mediaType,
      download_url: item.url, preview_url: item.url,
      width: item.width, height: item.height,
      file_size_bytes: item.size, title: item.title,
    }));
  res.json({ results });
});

app.get("/download", async (req, res) => {
  const item = LIBRARY.find(i => i.id === req.query.id);
  if (!item) return res.status(404).json({ error: "not found" });
  const response = await axios.get(item.url, { responseType: "stream" });
  res.setHeader("Content-Type", "image/jpeg");
  response.data.pipe(res);
});

app.listen(8080, () => console.log("Adapter running on :8080"));
```

---

## 6. Shell Script Example

```bash
#!/usr/bin/env bash
# Minimal adapter using netcat (for testing only — not production-ready)
# Usage: ./adapter.sh

PORT=8080

while true; do
  REQUEST=$(nc -l -p $PORT -q 1)
  PATH_LINE=$(echo "$REQUEST" | head -1)

  if echo "$PATH_LINE" | grep -q "GET /health"; then
    BODY='{"status":"ok","name":"Shell Adapter","version":"1.0"}'
  elif echo "$PATH_LINE" | grep -q "GET /search"; then
    BODY='{"results":[{"id":"sh001","media_type":"image","download_url":"https://picsum.photos/1920/1080","width":1920,"height":1080}]}'
  else
    BODY='{"error":"not found"}'
  fi

  printf "HTTP/1.1 200 OK\r\nContent-Type: application/json\r\nContent-Length: ${#BODY}\r\n\r\n$BODY" | nc -l -p $PORT -q 1
done
```

---

## 7. Authentication

If you set an Auth Token in the source configuration, B-Roll Engine sends it in every request:

```
Authorization: Bearer <your_token>
```

Validate it in your adapter on every request.

---

## 8. Testing Your Adapter

```bash
# Health check
curl http://localhost:8080/health

# Search
curl "http://localhost:8080/search?q=mountain&limit=5&media_type=image"

# With auth token
curl -H "Authorization: Bearer mytoken" "http://localhost:8080/search?q=ocean&limit=3"

# Download
curl "http://localhost:8080/download?id=001" -o result.jpg
```

---

## 9. Auto-Launch: `adapter_script_path`

When you select a niche profile on the Dashboard, B-Roll Engine automatically calls `POST /api/profiles/{id}/adapters/start`, which health-checks every `custom_adapter` source linked to that profile and, if one isn't responding, tries to launch it for you.

To opt in, set **Adapter Script Path** in the Sources UI (Sources → your custom adapter → "Adapter Script Path (for auto-launch)"). You can either type the full path of your adapter's Python entry-point script directly, e.g.:

```
D:\yt_vids\automation ecosystem\BRollGen\CustomAdapters\wh40k\40k_adapter.py
```

or drag-and-drop / browse to upload the `.py` file itself via `POST /api/sources/{id}/upload/adapter-script` — the app saves it under `CustomAdapters/uploaded/<source_id>/` and fills the path field in for you automatically. Both routes end up setting the exact same `config.adapter_script_path` value, so the rest of this section applies identically either way. The source needs to already exist (have an ID) before the upload option is available, since the target folder is keyed by source ID — save the source with just a Name first if you're creating it fresh.

What happens on profile selection:

1. The engine calls `GET {adapter_url}/health`. If it returns 200, nothing else happens — your adapter is already running.
2. If the health check fails and `adapter_script_path` is set, the engine runs `python <adapter_script_path>` as a background subprocess (no console window on Windows).
3. It polls `/health` every 0.5s for up to 10 seconds.
4. If your adapter is still not healthy after 10 seconds, session setup is **not blocked** — you'll just see a `start_timeout` status logged to the browser console, and the search results from that source will simply come back empty until you start it manually.

This field is only used for local (non-Docker) auto-launch. It has no effect when running under Docker Compose — see §12.

Your script only needs to be a normal, blocking, run-forever server process (`app.run(port=...)` for Flask, `app.listen(...)` for Express, etc.) — no special shutdown hooks are required. When the main B-Roll Engine app process exits, it terminates every adapter subprocess it launched.

---

## 10. Persistent Browser Pattern (Recommended for Playwright-Based Adapters)

If your adapter scrapes a website with Playwright instead of calling a clean JSON API, launching a fresh headless browser on every request is slow — often several seconds of pure browser-boot overhead per search or download. The two Playwright-based adapters bundled with B-Roll Engine (`CustomAdapters/wh40k/40k_adapter.py`, `artvee_adapter.py`) solve this with a **dedicated worker-thread + job-queue** pattern, and we recommend the same approach for your own Playwright-based adapters. (The other three bundled adapters — Wikimedia, NASA, All Openverse — use the Openverse JSON API and need no browser; see §11.)

**Why not just share one `Browser` object across Flask's request threads?** Playwright's *sync* API (`playwright.sync_api`) pins a `Browser`/`Page` to the OS thread that created it. Flask's default dev server runs each request in its own thread (`threaded=True`), so a second request thread trying to touch a `Browser` created on a different thread crashes with `greenlet.error: cannot switch to a different thread`. A simple `threading.Lock` around browser access does *not* fix this — a lock only serializes access, it doesn't move execution onto the browser's owning thread.

**The fix:** one dedicated background thread owns the `Browser` for the adapter's entire lifetime. Flask request threads never touch Playwright objects directly — they submit a job (a plain function) to a queue and block on a `concurrent.futures.Future` for the result. The worker thread pulls jobs off the queue and runs them, one at a time, on the same thread that launched the browser.

Skeleton (see the bundled adapters for the full working version):

```python
import atexit
import queue
import threading
from concurrent.futures import Future

from playwright.sync_api import sync_playwright

_job_queue: "queue.Queue[tuple[callable, Future]]" = queue.Queue()
_worker_thread: threading.Thread | None = None
_browser_init_failed = False
_pw_instance = None
_browser = None
_browser_lock = threading.Lock()  # guards only the one-time launch check


def _browser_worker_loop():
    global _pw_instance, _browser
    _pw_instance = sync_playwright().start()
    _browser = _pw_instance.chromium.launch(headless=True)
    while True:
        task_fn, fut = _job_queue.get()
        try:
            fut.set_result(task_fn(_browser))
        except Exception as exc:
            fut.set_exception(exc)


def _ensure_worker_started():
    global _worker_thread, _browser_init_failed
    with _browser_lock:
        if _worker_thread is None and not _browser_init_failed:
            try:
                _worker_thread = threading.Thread(target=_browser_worker_loop, daemon=True)
                _worker_thread.start()
            except Exception:
                _browser_init_failed = True


def _run_on_persistent_browser(task_fn, timeout=30):
    """task_fn(browser) -> result. Runs on the worker thread; blocks the caller."""
    _ensure_worker_started()
    if _browser_init_failed:
        raise RuntimeError("persistent browser unavailable")
    fut: Future = Future()
    _job_queue.put((task_fn, fut))
    return fut.result(timeout=timeout)


def _shutdown_browser():
    if _browser is not None:
        try:
            _browser.close()
        except Exception:
            pass
    if _pw_instance is not None:
        try:
            _pw_instance.stop()
        except Exception:
            pass


atexit.register(_shutdown_browser)
```

Key points if you adopt this pattern:

- **Submit whole task functions, not bare URLs.** If your scrape needs multiple steps against the same page context (e.g. navigate to an artwork page, then read a signed download URL that's only valid from that same session), submit one function that does the entire sequence, so it all runs atomically on the worker thread without racing another request.
- Each context (`browser.new_context()`) is safe to create concurrently without a lock once the browser itself is launched — contexts are Playwright's own isolation boundary. The lock in the skeleton above only protects the one-time browser launch.
- **Always keep a stateless fallback.** Wrap calls to `_run_on_persistent_browser` in a `try/except` that falls back to a fresh `sync_playwright()` context per request if the persistent path raises or times out. This means one broken page navigation can't wedge your adapter — it degrades to "slow but working" instead of failing outright.
- Register `atexit.register(_shutdown_browser)` so the browser process doesn't leak when the adapter process is killed (including when B-Roll Engine terminates it on app shutdown, per §9).

---

## 11. Bundled Openverse API Adapters (ports 3002 / 3003 / 3005)

Three bundled adapters query the Openverse API (openverse.org — 600M+ openly licensed images) instead of scraping. They share one module, `openverse_base.py`, which handles OAuth2 token fetch/refresh, pagination, parsing, and the download proxy.

| Adapter | Port | Behavior |
|---------|------|----------|
| `wikimedia_adapter.py` | 3002 | Openverse `source=wikimedia` — Wikimedia Commons |
| `nasa_adapter.py` | 3003 | Openverse `source=nasa` — NASA public domain imagery |
| `openverse_adapter.py` | 3005 | Openverse, no source filter — the full catalog |

### Library of Congress / British Library

Openverse has **no `loc` or `british` source slug**. Both institutions publish through Flickr, which Openverse aggregates under `source=flickr`. Reach their images through the **All Openverse** adapter (3005) — its unfiltered search surfaces their Flickr Commons uploads. The Flickr API itself was recently paywalled and is not used by any adapter.

### Authentication (optional but recommended)

Anonymous access works but caps results at 20 per page. Register once for a client:

```bash
curl -X POST https://api.openverse.org/v1/auth_tokens/register/ \
  -H "Content-Type: application/json" \
  -d '{"name":"BRollGen V1","description":"Local b-roll curation tool","email":"you@example.com"}'
```

The response contains `client_id` and `client_secret`. Supply them either way:

- **`.env` file** (repo root): copy `.env.example` to `.env` and fill in `OPENVERSE_CLIENT_ID` / `OPENVERSE_CLIENT_SECRET`. The adapters read it on startup (`.env` is gitignored).
- **Source Auth Token** (Sources UI): set to `client_id:client_secret`. This header value takes precedence over `.env`.

Each adapter's `/health` response includes `"authenticated": true|false` so you can confirm credentials were detected.

### Docker

Each Openverse adapter runs as its own Compose service (`adapter-wikimedia`, `adapter-nasa`, `adapter-openverse`), built from the same parameterized `CustomAdapters/wh40k/Dockerfile` — see §12. The `download_url` the adapters return is derived from the request's Host header, so it is correct both natively (`localhost:300x`) and in Docker (Compose service name). When running authenticated under Docker, pass `OPENVERSE_CLIENT_ID` / `OPENVERSE_CLIENT_SECRET` as env vars on the adapter containers — the repo-root `.env` is not mounted into them.

---

## 12. Dockerizing Your Adapter

If you want your adapter to run as its own container (matching how the bundled `wh40k` adapters are deployed — see the project's `DOCKER_SETUP.md`), the pattern used for all three bundled adapters is a single parameterized `Dockerfile` with an `ARG` selecting which script to run:

```dockerfile
# CustomAdapters/wh40k/Dockerfile
FROM python:3.11-slim

ARG ADAPTER_SCRIPT
ENV ADAPTER_SCRIPT=${ADAPTER_SCRIPT}

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
RUN playwright install --with-deps chromium

COPY . .

CMD python ${ADAPTER_SCRIPT}
```

Then in `docker-compose.yml`, each adapter service builds the same image with a different `ADAPTER_SCRIPT` build arg and its own port and healthcheck:

```yaml
adapter-myadapter:
  build:
    context: ./CustomAdapters/my_adapter_dir
    dockerfile: Dockerfile
    args:
      ADAPTER_SCRIPT: my_adapter.py
  ports:
    - "3003:3003"
  healthcheck:
    test: ["CMD", "python", "-c", "import urllib.request; urllib.request.urlopen('http://localhost:3003/health')"]
    interval: 10s
    timeout: 5s
    retries: 5
    start_period: 30s
  restart: unless-stopped
```

Two things to remember when your adapter runs inside Docker rather than as a local process:

- **`adapter_script_path` auto-launch (§9) does nothing here** — it's a local-only feature. Your container's own `CMD` starts your adapter directly.
- **Update the `adapter_url` in the Sources UI to the Compose service name**, not `localhost`. Inside the `app` container, `localhost` refers to the `app` container itself — sibling containers are reached by their service name (e.g. `http://adapter-myadapter:3003`). See `DOCKER_SETUP.md` for the full localhost-vs-container-name table.

---

## 13. Troubleshooting

| Error | Cause | Fix |
|-------|-------|-----|
| Connection refused | Adapter not running | Start your adapter process, or configure `adapter_script_path` for auto-launch (§9) |
| HTTP 401 Unauthorized | Wrong/missing token | Check the Auth Token in source config |
| Empty results | Query not matching | Check your search logic; try exact match |
| Quality score = 0 / adapter never wins selection | Search results missing `width`, `height`, and `file_size_bytes` — candidate scores 0.0 and loses to any source that returns dimensions | Return dimensions in search results (Option A), or set **Default Quality Score** in Sources UI (Option B) — see §3 |
| Slow downloads | Large files | Stream the response rather than buffering |
| `greenlet.error: cannot switch to a different thread` | Playwright `Browser`/`Page` touched from a different thread than the one that launched it | Adopt the persistent worker-thread pattern in §10 instead of sharing a Playwright object across Flask's request threads |
| Adapter shows `start_timeout` after profile selection | Adapter takes longer than 10s to become healthy, or `adapter_script_path` points to the wrong file | Start the adapter manually and check its own console output for the real error; verify the path in Sources |
