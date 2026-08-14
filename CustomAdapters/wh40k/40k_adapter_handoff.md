# 40k.gallery Custom Adapter — Handoff Notes

This adapter is a local Flask server (`40k_adapter.py`, v2.1) that B-Roll Engine talks to as a Custom Source. It scrapes Warhammer 40K fan/concept artwork from `https://40k.gallery/`. Running locally on `http://localhost:3000`.

## What this adapter is and isn't

It returns still images only. There is no video content on the source site, so `media_type` will always be `"image"` and any search with `media_type=video` short-circuits to an empty result list — that's expected, not a bug.

The site sits behind Cloudflare, and its HTML pages (search/category/tag) actively block plain HTTP requests. To get around that, every fetch of an HTML page runs through a real headless Chromium browser (Playwright), not a simple `requests.get()`. This makes every `/search` and `/download` call meaningfully slower than a typical adapter — budget on the order of several seconds per call, not milliseconds. If B-Roll Engine has its own timeout on adapter calls, it should be generous (10-15s+) for this source specifically.

By contrast, the actual image *files* are hosted on a separate CDN subdomain (`artwork.40k.gallery`) that is not behind the same protection, so once the page HTML is in hand, the final binary download itself is fast.

## `/search` — what it does and what comes back

`GET /search?q=<query>&limit=<n>&media_type=<any|image|video>`

Internally it tries three strategies in order, falling back only if the previous one returns nothing: a keyword search against the site's native search, a category-page lookup, then a tag-page lookup, using a slugified version of the query for the latter two. Don't assume which strategy fired — the response doesn't indicate that, it just returns whatever it found.

Response shape:

```json
{
  "results": [
    {
      "id": "ultramarines-32",
      "title": "Ultramarines — Rodrigo Lorenzo López",
      "media_type": "image",
      "preview_url": "https://artwork.40k.gallery/wp-content/uploads/2026/05/Ultramarines-768x961.jpg",
      "download_url": "http://127.0.0.1:3000/download?id=ultramarines-32",
      "width": 768,
      "height": 961,
      "duration_seconds": null,
      "file_size_bytes": null,
      "source_page_url": "https://40k.gallery/ultramarines-32/"
    }
  ]
}
```

A few field-level things worth knowing before consuming this:

`title` is a composite of the artwork's title and artist name joined with an em dash, not just the artwork's title alone — if you need them separately, you'd have to split on `" — "`, which is a bit fragile. Treat the whole string as a display label rather than parsing it.

`width` and `height` describe the **preview/thumbnail** image, not the full-resolution file. They're parsed directly out of the thumbnail filename (e.g. `-768x961.jpg`), so they're reliable, but they will not match the dimensions of whatever you eventually get back from `/download`. Don't use these to decide whether a full-res image meets a resolution requirement — there's currently no way to know the full-res dimensions without actually calling `/download`.

`duration_seconds` and `file_size_bytes` are always `null`. There's no video, so duration is structurally meaningless here, and file size isn't knowable until after the download completes — these fields exist only to satisfy the adapter protocol's expected schema shape, not because this source can populate them.

`limit` is capped server-side at 50 regardless of what's requested.

An empty `"results": []` is a normal, valid response — it means no matches were found across all three fallback strategies (or that the query was empty / media_type was "video"), not that something broke. A non-2xx status with an `"error"` field is the actual failure signal.

## `/download` — what it does and how to use it

`GET /download?id=<id>`

The `id` must be one returned from a prior `/search` call (it's the artwork's URL slug, e.g. `ultramarines-32`). This is a hard sequencing dependency: the adapter caches a slug → page-URL mapping in memory at search time, and `/download` looks up that cache to know which page to re-visit for the full-res image. **`/search` must be called before `/download` for a given id, in the same running process.** If the server has been restarted since the relevant search, or the id was never returned by `/search` in this session, the cache misses and the adapter falls back to guessing the page URL as `https://40k.gallery/<id>/` — which usually works since slugs match page URLs, but isn't guaranteed for an id picked at random rather than from real search output.

On success, this returns the raw image file directly as the HTTP response body (binary, correct `Content-Type` set, e.g. `image/jpeg`) — not JSON, not a redirect, not another link to follow. The agent driving this should download the response body directly. The dimensions of the image you get here are the *true* full-resolution ones, which can be noticeably larger than the `width`/`height` reported by `/search` (commonly 2x the preview size or more, based on the artwork seen so far — e.g. a 768×961 preview corresponding to a 1534×1920 actual file).

On failure, it returns JSON instead of an image, with an HTTP error status — `404` if no full-res image could be located for that id, `502` if the located image URL failed to actually download. Always check the response `Content-Type` or status code before treating the body as image bytes; do not assume every `/download` response is a valid image just because the request succeeded at the HTTP level.

## Known limitations to be aware of

Each `/search` or `/download` call launches and fully tears down its own headless Chromium instance — there's deliberately no shared/persistent browser, which avoids a threading crash but means there's no way to speed this up by batching; treat each call as independently expensive.

There's a fixed 1-second delay built into every page fetch as a politeness measure against Cloudflare. Pagination during search (when more results are needed to hit `limit`) is capped at 5 pages, so very high `limit` values on broad queries may still return fewer results than requested if the site simply doesn't have that many matches within 5 pages.

This source provides artwork sourced from individual artists credited by name on the site. If B-Roll Engine surfaces attribution or licensing info to end users, the artist name embedded in `title` is the only attribution data this adapter currently exposes — there's no separate license or usage-rights field.
