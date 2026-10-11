"""Beaches, boat ramps, marinas and fishing piers near each tide station, from OpenStreetMap
(© OpenStreetMap contributors, ODbL: credited on every page that shows them).

One Overpass query per 1° square that has stations in it, politely spaced. Raw answers are kept in a cache
directory so an interrupted run picks up where it stopped. Places change slowly, so the result is committed:

    python3 collector/places.py /tmp/overpass-cache     # writes collector/places.json
"""

import json
import math
import sys
import time
import urllib.parse
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fetch import STATIONS_URL, get, us_state  # noqa: E402

OUT = Path(__file__).resolve().parent / "places.json"
API = "https://overpass-api.de/api/interpreter"
UA = "TideChartUSA/1.0 (hello@tidechartusa.com; one-off batch, ~1 query per few seconds)"
RADIUS = 6       # miles
PER_KIND = 4
QUERY = """[out:json][timeout:120];
(
  nwr["natural"="beach"]["name"]({b});
  nwr["leisure"="slipway"]({b});
  nwr["leisure"="marina"]["name"]({b});
  nwr["man_made"="pier"]["name"]({b});
  nwr["leisure"="fishing"]({b});
);
out center tags;"""


def miles(a, b):
    la1, lo1, la2, lo2 = map(math.radians, (a[0], a[1], b[0], b[1]))
    h = math.sin((la2 - la1) / 2) ** 2 + math.cos(la1) * math.cos(la2) * math.sin((lo2 - lo1) / 2) ** 2
    return 3958.8 * 2 * math.asin(math.sqrt(h))


def kind_of(tags):
    if tags.get("natural") == "beach":
        return "beach"
    if tags.get("leisure") == "slipway":
        return "ramp"
    if tags.get("leisure") == "marina":
        return "marina"
    if tags.get("man_made") == "pier" or tags.get("leisure") == "fishing":
        return "pier"
    return None


def fetch_cell(cache, la, lo):
    f = cache / f"{la}_{lo}.json"
    if f.exists():
        return json.loads(f.read_text())
    # Pad the square so stations near its edge still see places just across the line.
    pad = 0.1
    b = f"{la - pad},{lo - pad},{la + 1 + pad},{lo + 1 + pad}"
    data = urllib.parse.urlencode({"data": QUERY.format(b=b)}).encode()
    for n in range(5):
        try:
            req = urllib.request.Request(API, data=data, headers={"User-Agent": UA})
            j = json.loads(urllib.request.urlopen(req, timeout=180).read())
            f.write_text(json.dumps(j["elements"]))
            return j["elements"]
        except Exception as ex:
            print(f"cell {la},{lo} try {n + 1}: {str(ex)[:80]}", file=sys.stderr)
            time.sleep(30 * (n + 1))
    return None


def main():
    cache = Path(sys.argv[1])
    cache.mkdir(parents=True, exist_ok=True)
    stations = [s for s in get(STATIONS_URL)["stations"] if us_state(s) and s.get("lat") is not None]
    cells = sorted({(math.floor(s["lat"]), math.floor(s["lng"])) for s in stations})
    print(f"{len(stations)} stations in {len(cells)} cells")
    places = {}
    for i, (la, lo) in enumerate(cells):
        cached = (cache / f"{la}_{lo}.json").exists()
        els = fetch_cell(cache, la, lo)
        if els is None:
            continue
        for e in els:
            tags = e.get("tags", {})
            k = kind_of(tags)
            lat = e.get("lat") or (e.get("center") or {}).get("lat")
            lng = e.get("lon") or (e.get("center") or {}).get("lon")
            if k and lat is not None:
                places[(e["type"], e["id"])] = (k, tags.get("name", ""), lat, lng)
        if not cached:
            time.sleep(4)
        if i % 25 == 0:
            print(f"{i + 1}/{len(cells)} cells, {len(places)} places", flush=True)

    grid = {}
    for k, name, lat, lng in places.values():
        grid.setdefault((math.floor(lat * 4), math.floor(lng * 4)), []).append((k, name, lat, lng))
    out = {}
    for s in stations:
        found = []
        gy, gx = math.floor(s["lat"] * 4), math.floor(s["lng"] * 4)
        for dy in (-1, 0, 1):
            for dx in (-1, 0, 1):
                for k, name, lat, lng in grid.get((gy + dy, gx + dx), []):
                    d = miles((s["lat"], s["lng"]), (lat, lng))
                    if d <= RADIUS:
                        found.append((d, k, name, lat, lng))
        found.sort()
        keep, seen = [], set()
        for d, k, name, lat, lng in found:
            key = (k, name.lower()) if name else (k, round(lat, 3), round(lng, 3))
            if key in seen or sum(1 for x in keep if x[0] == k) >= PER_KIND:
                continue
            seen.add(key)
            keep.append([k, name, round(lat, 5), round(lng, 5), round(d, 1)])
        if keep:
            out[s["id"]] = keep
    OUT.write_text(json.dumps(out, separators=(",", ":"), ensure_ascii=False))
    print(f"{len(places)} places; {len(out)}/{len(stations)} stations have something nearby")


if __name__ == "__main__":
    main()
