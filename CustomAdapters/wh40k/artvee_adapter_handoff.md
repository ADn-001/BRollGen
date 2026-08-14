# artvee.com Custom Adapter — Handoff Notes

This adapter is a local Flask server (`artvee_adapter.py`, v1.1) registered as a Custom Source in B-Roll Engine. It serves public domain historical artworks scraped from `https://artvee.com/` — paintings, illustrations, posters, and drawings aggregated from major museums worldwide (Rijksmuseum, Met, Art Institute of Chicago, Smithsonian, and others). Running locally on `http://localhost:3001`.

## What this adapter is and isn't

It returns still images only. There is no video content on the source site, so `media_type` will always be `"image"` and any search with `media_type=video` short-circuits to an empty result list immediately — that's expected, not a bug.

The adapter never automatically selects or downloads anything. `/search` returns a ranked list of candidates and stops there. `/download` only runs when the app explicitly calls it with a chosen `id`. The app has full control over which result gets downloaded and when.

The site does not require login or an API key to browse or download. All content is public domain.

## `/search` — what it does and what comes back

`GET /search?q=<query>&limit=<n>&media_type=<any|image|video>`

Internally tries three strategies in order, falling back only if the previous one returns nothing: keyword search (`/?s=query`), category page (`/c/query-slug/`), then topic page (`/topics/query-slug/`). Paginates up to 5 pages of keyword results when needed to reach `limit`. The response doesn't indicate which strategy fired.

Response shape:

```json
{
  "results": [
    {
      "id": "persia-antiquity",
      "title": "Persia Antiquity — Adolf Rosenberg",
      "media_type": "image",
      "preview_url": null,
      "download_url": "http://127.0.0.1:3001/download?id=persia-antiquity",
      "width": null,
      "height": null,
      "duration_seconds": null,
      "file_size_bytes": null,
      "source_page_url": "https://artvee.com/dl/persia-antiquity/"
    }
  ]
}
```

Field-level notes before consuming this:

`preview_url` is always `null`. Artvee's search result pages contain no thumbnail images in their HTML — thumbnails only appear on individual artwork pages, which would require a separate browser fetch per result. Since that would make every search dramatically slower, preview URLs are not populated. If your UI needs a thumbnail before download, call `/download` for the specific result you want and use the returned image directly.

`title` is a composite of the artwork title and artist name joined with an em dash, extracted from the article's CSS class metadata rather than child elements. Treat it as a display string — if you need them separated, split on `" — "`, though that's fragile if a title itself contains that sequence.

`width`, `height`, `duration_seconds`, and `file_size_bytes` are always `null`. Dimensions aren't knowable without downloading the image, and file size isn't available either. Don't use these fields to pre-filter by resolution.

`id` is the artwork's URL slug (e.g. `persia-antiquity`). This is what you pass to `/download`. It's also used internally to look up the full artwork page URL from a session cache — see the sequencing note below.

`limit` is capped server-side at 50. An empty `"results": []` is normal and means no matches were found across all three strategies, not a failure. A non-2xx HTTP status with an `"error"` field is the actual failure signal.

## `/download` — what it does and how to use it

`GET /download?id=<id>`

The `id` must be one returned from a prior `/search` call. On success, returns the raw full-resolution image as the HTTP response body — binary bytes, correct `Content-Type` (typically `image/jpeg`), not JSON, not a redirect. Consume the response body directly as image data.

**Sequencing dependency**: `/search` must be called before `/download` for any given `id` within the same running server session. The adapter caches a slug-to-page-URL mapping in memory when `/search` runs. If the server has been restarted since the relevant search, or if you call `/download` with an `id` that was never returned by `/search` in this session, the adapter falls back to guessing the page URL as `https://artvee.com/dl/<id>/` — which usually works since Artvee slugs match their URLs, but isn't guaranteed for arbitrary IDs.

**Why downloads take longer than searches**: the download route has to load the full artwork page in a fresh headless Chromium browser *and* download the image in that same browser session. It cannot use a plain HTTP request for the image download because Artvee serves full-res files via AWS S3 pre-signed URLs where the signature is tied to the browser session's request headers. Splitting the page load and the image download across two different HTTP clients causes a 403 from S3. The adapter handles this correctly by keeping the browser alive for both steps, but it means `/download` is noticeably slower than a typical adapter — budget 5–15 seconds per call.

On failure, `/download` returns JSON with an `"error"` key and an HTTP error status (`404` if the artwork page couldn't be parsed, `502` for other failures). Always check the response `Content-Type` or status code before treating the body as image bytes.

## Known limitations

Each `/search` or `/download` call launches and fully tears down its own headless Chromium instance. There is no shared persistent browser. This is intentional (prevents thread-safety crashes) but means every call pays a ~1–2s browser startup cost on top of page load time.

A 1.2-second politeness delay is built into every page fetch. Paginated searches (multiple pages of results) multiply this cost — a 5-page search takes proportionally longer.

`preview_url` being null means the app cannot show thumbnails in a result picker without first downloading. For workflows where the agent is auto-selecting the best match rather than presenting choices to a human, this is fine — just pick the most relevant result by title and call `/download` directly.

All content on Artvee is public domain. Artist attribution is embedded in `title`. There are no usage restrictions, but if B-Roll Engine surfaces attribution to end users, the artist name in the title field is the only attribution data this adapter exposes.
