"""Beaches, boat ramps, marinas and fishing piers near each tide station, from OpenStreetMap
(© OpenStreetMap contributors, ODbL: credited on every page that shows them).

Two ways to get the places. Places change slowly, so the result is committed either way.

From Geofabrik extracts (recommended: no rate limits). Download the coastal states' .osm.pbf files from
download.geofabrik.de and install pyosmium (pip install osmium), then:

    python3 collector/places.py --pbf ~/osm/*.osm.pbf  # writes collector/places.json

From the public Overpass API: one query per 1° square that has stations in it, politely spaced. Raw answers are
kept in a cache directory so an interrupted run picks up where it stopped. Overpass is often too busy for this:

    python3 collector/places.py /tmp/overpass-cache
"""

import json
import math
import re
import sys
import time
import urllib.parse
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fetch import STATIONS_URL, get, us_state  # noqa: E402

OUT = Path(__file__).resolve().parent / "places.json"
API = "https://overpass-api.de/api/interpreter"
UA = "Shorebite/1.0 (hello@shorebite.com; one-off batch, ~1 query per few seconds)"
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


# Names that are working docks, wrecks or military, not somewhere a visitor can go.
JUNK = re.compile(r"\bruins?\b|coast guard|uscg|patrol|navy|naval|military|firing|dolphin|heliport|maintenance|facility|spill|barge|vessel|cargo|container|terminal|industrial|refinery|^\d|^p-?\d|^(pier|berth|wharf|dock) \d+[a-z]?$|^.{1,2}$", re.I)


def wanted(tags):
    """Same selection as QUERY: named beaches, marinas and piers; every slipway and fishing spot. Leaves out
    private or military beaches and piers, and junk names."""
    k = kind_of(tags)
    name = tags.get("name", "")
    if not k or (name and JUNK.search(name)) or tags.get("military") or tags.get("landuse") == "military":
        return None
    if k in ("beach", "pier") and tags.get("access") in ("private", "no", "military"):
        return None
    if k in ("beach", "marina") or (k == "pier" and tags.get("man_made") == "pier" and tags.get("leisure") != "fishing"):
        return k if tags.get("name") else None
    return k


def from_pbf(paths):
    """Places from local OpenStreetMap extracts. Ways and multipolygons are placed at the average of their points."""
    import osmium
    places = {}
    for path in paths:
        fp = (osmium.FileProcessor(str(path))
              .with_locations()
              .with_areas(osmium.filter.KeyFilter("natural", "leisure", "man_made"))
              .with_filter(osmium.filter.KeyFilter("natural", "leisure", "man_made")))
        n0 = len(places)
        for o in fp:
            tags = dict(o.tags)
            k = wanted(tags)
            if not k:
                continue
            pts = []
            if o.is_node():
                pts = [o.location]
            elif o.is_way():
                pts = [n.location for n in o.nodes]
            elif o.is_area() and not o.from_way():   # closed ways are handled as ways
                pts = [n.location for ring in o.outer_rings() for n in ring]
            else:
                continue
            pts = [q for q in pts if q.valid()]
            if not pts:
                continue
            key = ("r", o.orig_id()) if o.is_area() else (o.type_str(), o.id)
            places[key] = (k, tags.get("name", ""), sum(q.lat for q in pts) / len(pts), sum(q.lon for q in pts) / len(pts))
        print(f"{Path(path).name}: {len(places) - n0} places", flush=True)
    return places


def fetch_cell(cache, la, lo):
    f = cache / f"{la}_{lo}.json"
    if f.exists():
        return json.loads(f.read_text())
    # Pad the square so stations near its edge still see places just across the line.
    pad = 0.1
    b = f"{la - pad},{lo - pad},{la + 1 + pad},{lo + 1 + pad}"
    data = urllib.parse.urlencode({"data": QUERY.format(b=b)}).encode()
    for n in range(2):
        try:
            req = urllib.request.Request(API, data=data, headers={"User-Agent": UA})
            j = json.loads(urllib.request.urlopen(req, timeout=180).read())
            f.write_text(json.dumps(j["elements"]))
            return j["elements"]
        except Exception as ex:
            print(f"cell {la},{lo} try {n + 1}: {str(ex)[:80]}", file=sys.stderr)
            time.sleep(10)
    return None


def main():
    stations = [s for s in get(STATIONS_URL)["stations"] if us_state(s) and s.get("lat") is not None]
    if sys.argv[1] == "--pbf":
        write(stations, from_pbf(sys.argv[2:]))
    else:
        write(stations, from_overpass(stations, Path(sys.argv[1])))


def from_overpass(stations, cache):
    cache.mkdir(parents=True, exist_ok=True)
    cells = sorted({(math.floor(s["lat"]), math.floor(s["lng"])) for s in stations})
    print(f"{len(stations)} stations in {len(cells)} cells")
    # The public Overpass server is often busy: make passes over the squares still missing, resting between them.
    for attempt in range(12):
        missing = [c for c in cells if not (cache / f"{c[0]}_{c[1]}.json").exists()]
        print(f"pass {attempt + 1}: {len(missing)} squares to fetch", flush=True)
        if not missing:
            break
        for la, lo in missing:
            if fetch_cell(cache, la, lo) is not None:
                time.sleep(4)
        if any(not (cache / f"{c[0]}_{c[1]}.json").exists() for c in cells):
            time.sleep(600)
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
    return places


def write(stations, places):
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
            # One entry per name, and unnamed ones only if no same-kind place is within about 250 yards.
            if (k, name.lower()) in seen or sum(1 for x in keep if x[0] == k) >= PER_KIND:
                continue
            if not name and any(x[0] == k and miles((lat, lng), (x[2], x[3])) < 0.15 for x in keep):
                continue
            if name:
                seen.add((k, name.lower()))
            keep.append([k, name, round(lat, 5), round(lng, 5), round(d, 1)])
        if keep:
            out[s["id"]] = keep
    OUT.write_text(json.dumps(out, separators=(",", ":"), ensure_ascii=False))
    print(f"{len(places)} places; {len(out)}/{len(stations)} stations have something nearby")


if __name__ == "__main__":
    main()
