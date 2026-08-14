"""
loc_debug.py — run this locally to see exactly what the LOC API returns.
Prints raw status, headers, and the first 3000 chars of the response body.
"""
import requests, json

HEADERS = {
    "User-Agent": "Mozilla/5.0 (compatible; BRollEngine/1.0)",
    "Accept": "application/json",
}

def check(label, url, params=None):
    print(f"\n{'='*60}")
    print(f"  {label}")
    print(f"  URL: {url}")
    if params:
        print(f"  Params: {params}")
    print('='*60)
    try:
        p = dict(params or {})
        p.setdefault("fo", "json")
        r = requests.get(url, params=p, headers=HEADERS, timeout=15)
        print(f"  Status: {r.status_code}")
        print(f"  Content-Type: {r.headers.get('Content-Type')}")
        print(f"  Body ({len(r.text)} chars):")
        print(r.text[:3000])

        if r.status_code == 200:
            try:
                data = r.json()
                results = data.get("results", [])
                print(f"\n  --> Parsed OK. results count: {len(results)}")
                if results:
                    print(f"  --> First result keys: {list(results[0].keys())}")
                    print(f"  --> First result id: {results[0].get('id')}")
                    print(f"  --> First result title: {results[0].get('title','')[:80]}")
                    print(f"  --> First result image_url: {results[0].get('image_url')}")
            except Exception as e:
                print(f"  --> JSON parse failed: {e}")
    except Exception as e:
        print(f"  --> Request failed: {e}")

# Test 1: photos endpoint with search
check(
    "Photos endpoint — search 'ancient persia'",
    "https://www.loc.gov/photos/",
    {"q": "ancient persia", "c": 3}
)

# Test 2: general search endpoint (fallback)
check(
    "General search endpoint — search 'ancient persia' + image filter",
    "https://www.loc.gov/search/",
    {"q": "ancient persia", "fa": "original_format:photo,+print,+drawing", "c": 3}
)

# Test 3: item endpoint for a known LOC item
check(
    "Item endpoint — known LOC photo item",
    "https://www.loc.gov/item/2014645339/",
)

print("\n\nDone. Paste all output above back to the AI.")
