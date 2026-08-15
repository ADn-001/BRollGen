"""
openverse_adapter.py  --  B-Roll Engine Custom Adapter  v1.0
=============================================================
All Openverse — searches the full 600M+ image pool with no source filter.

Sources include: Flickr Commons, Wikimedia Commons, NASA, Europeana,
  Smithsonian, iNaturalist, Rawpixel, Brooklyn Museum, Cleveland Museum,
  and many more. All content is openly licensed or public domain.

More info:  https://openverse.org/about

Authentication (optional, recommended):
  Register once at https://api.openverse.org/v1/auth_tokens/register/ to get
  client_id + client_secret. Set in Sources UI api_key field as:
      client_id:client_secret
  or set env vars OPENVERSE_CLIENT_ID / OPENVERSE_CLIENT_SECRET.
  Without credentials: anonymous access, capped at 20 results/request.

Run:
    pip install flask requests
    python openverse_adapter.py

Port: 3005  (40k=3000, artvee=3001, wikimedia=3002, nasa=3003, openverse=3005)
"""

import logging
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import openverse_base as ov

from flask import Flask, jsonify, request, send_file

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------
PORT = 3005
# No SOURCE filter — searches all of Openverse

app = Flask(__name__)
logging.basicConfig(level=logging.INFO, format="%(levelname)s  %(message)s")
log = logging.getLogger(__name__)

# id -> direct image URL, populated during /search
_url_cache: dict[str, str] = {}

# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@app.route("/health")
def health():
    return jsonify({
        "status":      "ok",
        "name":        "All Openverse Adapter",
        "version":     "1.0",
        "description": (
            "Searches the full Openverse catalog: 600M+ openly licensed images "
            "from Flickr, Wikimedia Commons, NASA, Europeana, Smithsonian, "
            "iNaturalist, and many more. No source filter applied. "
            "Optional OAuth2 credentials unlock larger result sets."
        ),
        "authenticated": ov.is_authenticated(),
    })


@app.route("/search")
def search():
    q          = request.args.get("q", "").strip()
    limit      = min(int(request.args.get("limit", 10)), 50)
    media_type = request.args.get("media_type", "any")

    if not q:
        return jsonify({"results": [], "error": "Query parameter 'q' is required"}), 400
    if media_type == "video":
        return jsonify({"results": []})

    log.info("Searching all Openverse for %r (limit=%d)", q, limit)
    raw = ov.openverse_search(query=q, limit=limit, source=None)
    if raw is None:
        return jsonify({"results": [], "error": "Openverse API error"}), 502

    results = []
    for item in raw[:limit]:
        parsed = ov.parse_result(item)
        direct_url = parsed.pop("_direct_url", "")
        if direct_url and parsed["id"]:
            _url_cache[parsed["id"]] = direct_url
        results.append(parsed)

    log.info("Returning %d results for %r", len(results), q)
    return jsonify({"results": results})


@app.route("/download")
def download():
    image_id = request.args.get("id", "").strip()

    if not image_id:
        return jsonify({"error": "Missing 'id' parameter"}), 400

    url = _url_cache.get(image_id)
    if not url:
        return jsonify({"error": f"No cached URL for id '{image_id}'. Run a search first."}), 404

    log.info("Downloading %s from %s", image_id, url)
    try:
        buf, content_type, ext = ov.download_image(url)
        return send_file(buf, mimetype=content_type, download_name=f"{image_id}.{ext}")
    except Exception as exc:
        log.error("Download failed: %s", exc)
        return jsonify({"error": str(exc)}), 502


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    print("=" * 60)
    print("  All Openverse Adapter  v1.0")
    print(f"  http://localhost:{PORT}")
    print("=" * 60)
    print()
    print("  Searches all of Openverse -- 600M+ openly licensed images.")
    print("  No source filter: broadest possible results.")
    print()
    authed = ov.is_authenticated()
    print(f"  Auth: {'OAuth2 credentials detected' if authed else 'anonymous (max 20 results/request)'}")
    print()
    print("  Test with:")
    print(f"    curl http://localhost:{PORT}/health")
    print(f'    curl "http://localhost:{PORT}/search?q=ancient+rome&limit=5"')
    print(f'    curl "http://localhost:{PORT}/download?id=<id from search>" -o out.jpg')
    print()
    app.run(host="0.0.0.0", port=PORT, debug=False, threaded=True)
