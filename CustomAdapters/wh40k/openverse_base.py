"""
openverse_base.py  --  Shared helpers for all Openverse adapters
================================================================
Handles:
  - OAuth2 client_credentials token fetch + auto-refresh
  - Openverse image search
  - Response parsing to B-Roll Engine format
  - Image download proxy

OAuth2 setup (one-time):
  1. Register at: POST https://api.openverse.org/v1/auth_tokens/register/
     Body (JSON): {"name": "BRollEngine", "description": "...", "email": "you@example.com"}
     Response:    {"client_id": "...", "client_secret": "..."}
  2. Set in Sources UI api_key field as:  client_id:client_secret
     OR set env vars:  OPENVERSE_CLIENT_ID  and  OPENVERSE_CLIENT_SECRET

The adapter auto-exchanges credentials for a bearer token and silently
refreshes it before expiry. Zero ongoing human intervention required.

Anonymous fallback:
  If no credentials are configured, requests proceed anonymously.
  Anonymous access is capped at 20 results per page by Openverse.
"""

import io
import logging
import os
import time

import requests
from flask import request as flask_request, has_request_context

log = logging.getLogger(__name__)

OPENVERSE_API_BASE = "https://api.openverse.org/v1/"
ANON_MAX_PAGE_SIZE = 20
AUTH_MAX_PAGE_SIZE = 500
MAX_PAGES = 5
UA_HEADERS = {"User-Agent": "BRollEngine/1.0 (Openverse adapter; local b-roll curation)"}


def _load_env_file() -> None:
    """
    Load .env if present (OPENVERSE_CLIENT_ID / OPENVERSE_CLIENT_SECRET).
    Searches this module's directory, then the repo root (two levels up).
    Never overrides already-set environment variables.
    """
    here = os.path.dirname(os.path.abspath(__file__))
    for candidate in (here, os.path.dirname(os.path.dirname(here))):
        env_path = os.path.join(candidate, ".env")
        if not os.path.isfile(env_path):
            continue
        with open(env_path, encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                key, _, value = line.partition("=")
                key = key.strip()
                value = value.strip().strip('"').strip("'")
                if key and key not in os.environ:
                    os.environ[key] = value
        return


_load_env_file()

# ---------------------------------------------------------------------------
# Token cache — module-level so all adapters sharing this module benefit.
# Stores (access_token: str, expires_at: float).
# ---------------------------------------------------------------------------
_token_cache: tuple[str, float] | None = None


# ---------------------------------------------------------------------------
# Credential / token helpers
# ---------------------------------------------------------------------------

def _get_credentials() -> tuple[str, str] | None:
    """
    Return (client_id, client_secret) from the current request or env vars.

    Sources UI stores the value in the Authorization: Bearer header as:
        client_id:client_secret
    Env var fallback uses OPENVERSE_CLIENT_ID + OPENVERSE_CLIENT_SECRET.
    """
    if has_request_context():
        auth = flask_request.headers.get("Authorization", "")
        if auth.startswith("Bearer "):
            key = auth[7:].strip()
            if ":" in key:
                client_id, client_secret = key.split(":", 1)
                if client_id and client_secret:
                    return client_id, client_secret

    client_id = os.environ.get("OPENVERSE_CLIENT_ID", "").strip()
    client_secret = os.environ.get("OPENVERSE_CLIENT_SECRET", "").strip()
    if client_id and client_secret:
        return client_id, client_secret

    return None


def _fetch_token(client_id: str, client_secret: str) -> tuple[str, float] | None:
    """Exchange client credentials for a bearer token. Returns (token, expires_at)."""
    try:
        resp = requests.post(
            f"{OPENVERSE_API_BASE}auth_tokens/token/",
            data={
                "grant_type": "client_credentials",
                "client_id": client_id,
                "client_secret": client_secret,
            },
            timeout=10,
        )
    except requests.RequestException as exc:
        log.error("Token fetch failed: %s", exc)
        return None

    if resp.status_code != 200:
        log.error("Token fetch returned %d: %s", resp.status_code, resp.text[:200])
        return None

    data = resp.json()
    access_token = data.get("access_token", "")
    expires_in = int(data.get("expires_in", 36000))  # default 10h
    if not access_token:
        log.error("Token response missing access_token: %s", data)
        return None

    log.info("Obtained Openverse access token (expires in %ds)", expires_in)
    return access_token, time.time() + expires_in


def build_auth_headers() -> dict:
    """
    Return Authorization headers for the current request.
    Automatically fetches/refreshes the OAuth2 token.
    Returns empty dict for anonymous access.
    """
    global _token_cache

    creds = _get_credentials()
    if not creds:
        return {}

    client_id, client_secret = creds

    # Refresh if missing or expiring within 60 seconds
    if _token_cache is None or _token_cache[1] < time.time() + 60:
        result = _fetch_token(client_id, client_secret)
        if result is None:
            log.warning("Token refresh failed; falling back to anonymous access")
            return {}
        _token_cache = result

    return {"Authorization": f"Bearer {_token_cache[0]}"}


def is_authenticated() -> bool:
    """Return True if credentials are configured (regardless of token state)."""
    return _get_credentials() is not None


# ---------------------------------------------------------------------------
# Search
# ---------------------------------------------------------------------------

def openverse_search(
    query: str,
    limit: int = 20,
    source: str | None = None,
) -> list[dict] | None:
    """
    Search Openverse images, paginating when the requested limit exceeds the
    per-page cap (20 anonymous, 500 authenticated).

    Args:
        query:  Search query string.
        limit:  Max results to return.
        source: Openverse source slug (e.g. "nasa", "wikimedia", "flickr").
                Pass None to search all sources.

    Returns:
        List of raw Openverse result dicts, or None on API error.
    """
    headers = build_auth_headers()
    headers.update(UA_HEADERS)
    max_page_size = AUTH_MAX_PAGE_SIZE if headers.get("Authorization") else ANON_MAX_PAGE_SIZE
    page_size = min(limit, max_page_size)

    params: dict = {
        "q": query,
        "page_size": page_size,
    }
    if source:
        params["source"] = source

    results: list[dict] = []
    page = 1
    while len(results) < limit and page <= MAX_PAGES:
        try:
            resp = requests.get(
                f"{OPENVERSE_API_BASE}images/",
                params={**params, "page": page},
                headers=headers,
                timeout=15,
            )
        except requests.RequestException as exc:
            log.error("Openverse search request failed: %s", exc)
            return None

        if resp.status_code != 200:
            log.error("Openverse search returned %d: %s", resp.status_code, resp.text[:200])
            return None if not results else results

        data = resp.json()
        page_results = data.get("results", [])
        if not page_results:
            break
        results.extend(page_results)
        page += 1

    return results[:limit]


# ---------------------------------------------------------------------------
# Parsing
# ---------------------------------------------------------------------------

def parse_result(item: dict) -> dict:
    """
    Convert a raw Openverse image result to B-Roll Engine adapter format.

    download_url is built from the current request's Host header so it is
    reachable both natively (localhost:<port>) and under Docker (where the
    backend reaches the adapter by its Compose service name).

    Stores the direct image URL in the private '_direct_url' key so the
    adapter can cache it for its /download endpoint.
    """
    width = item.get("width") or 0
    height = item.get("height") or 0
    quality_score = width * height if (width and height) else 0

    tags = [
        t["name"] for t in (item.get("tags") or [])
        if isinstance(t, dict) and t.get("name")
    ]

    license_url = item.get("license_url") or ""
    license_name = item.get("license") or ""
    license_str = license_url if license_url else license_name

    return {
        "id":            item.get("id", ""),
        "title":         item.get("title") or "",
        "thumbnail_url": item.get("thumbnail") or "",
        "source_url":    item.get("foreign_landing_url") or "",
        "download_url":  f"http://{flask_request.host}/download?id={item.get('id', '')}",
        "license":       license_str,
        "width":         width,
        "height":        height,
        "quality_score": quality_score,
        "tags":          tags,
        "provider":      item.get("provider") or "",
        "source":        item.get("source") or "",
        # Private: cached by adapter for /download
        "_direct_url":   item.get("url") or "",
    }


# ---------------------------------------------------------------------------
# Download proxy
# ---------------------------------------------------------------------------

def download_image(url: str) -> tuple[io.BytesIO, str, str]:
    """
    Fetch an image from a direct URL.

    Returns:
        (BytesIO buffer, content_type, file_extension)

    Raises:
        requests.HTTPError on non-2xx response.
        requests.RequestException on network error.
    """
    resp = requests.get(url, headers=UA_HEADERS, timeout=30, stream=True)
    resp.raise_for_status()

    content_type = resp.headers.get("Content-Type", "image/jpeg").split(";")[0].strip()
    ext_map = {
        "image/jpeg": "jpg",
        "image/png":  "png",
        "image/gif":  "gif",
        "image/webp": "webp",
        "image/tiff": "tiff",
        "image/svg+xml": "svg",
    }
    ext = ext_map.get(content_type, "jpg")

    buf = io.BytesIO(resp.content)
    buf.seek(0)
    return buf, content_type, ext
