"""Nearest town for each tide station, and the towns that get their own "Tides near <town>" page.

People search "Pacifica tide chart", not NOAA's "Point San Pedro", so every station page names its town and
each coastal town gets a page gathering its nearby stations. Towns come from GeoNames (cities500, CC BY 4.0:
credited in the footer and on the about page). Towns hardly change, so the result is committed:

    curl -O https://download.geonames.org/export/dump/cities500.zip && unzip cities500.zip
    python3 collector/towns.py /path/to/cities500.txt    # writes collector/towns.json
"""

import json
import math
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUT = Path(__file__).resolve().parent / "towns.json"
# GeoNames files territories under their own country codes.
TERRITORY = {"PR": "PR", "VI": "VI", "GU": "GU", "AS": "AS", "MP": "MP"}
KEEP = {"PPL", "PPLA", "PPLA2", "PPLA3", "PPLA4", "PPLC", "PPLL", "PPLS", "PPLF"}
ASSIGN_MILES = 15     # a station's town must be this close
PAGE_MILES = 15       # stations listed on a town page
BIG_TOWN = 10000      # towns this big near the coast get a page even if no station picked them


def miles(a, b):
    la1, lo1, la2, lo2 = map(math.radians, (a[0], a[1], b[0], b[1]))
    h = math.sin((la2 - la1) / 2) ** 2 + math.cos(la1) * math.cos(la2) * math.sin((lo2 - lo1) / 2) ** 2
    return 3958.8 * 2 * math.asin(math.sqrt(h))


def load_places(path):
    places = []
    with open(path, encoding="utf-8") as f:
        for line in f:
            c = line.rstrip("\n").split("\t")
            if len(c) < 15 or c[7] not in KEEP:
                continue
            cc, admin1 = c[8], c[10]
            state = admin1 if cc == "US" else TERRITORY.get(cc)
            if not state or len(state) != 2:
                continue
            try:
                places.append({"name": c[1], "st": state, "lat": float(c[4]), "lng": float(c[5]), "pop": int(c[14] or 0)})
            except ValueError:
                continue
    return places


def main():
    places = load_places(sys.argv[1])
    # NOAA's current station list (not data/stations.json, which may be a partial local download).
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    from fetch import STATIONS_URL, get, us_state
    stations = [s for s in get(STATIONS_URL)["stations"] if us_state(s) and s.get("lat") is not None]
    cells = {}
    for p in places:
        cells.setdefault((int(p["lat"]), int(p["lng"])), []).append(p)

    def near(lat, lng, limit):
        out = []
        for dy in (-1, 0, 1):
            for dx in (-1, 0, 1):
                for p in cells.get((int(lat) + dy, int(lng) + dx), []):
                    d = miles((lat, lng), (p["lat"], p["lng"]))
                    if d <= limit:
                        out.append((d, p))
        return out

    key = lambda p: f'{p["st"]}|{p["name"]}'
    towns, assign = {}, {}
    for s in stations:
        cand = near(s["lat"], s["lng"], ASSIGN_MILES)
        if not cand:
            continue
        # Nearest wins, weighted toward towns people have heard of, and toward the station's own state
        # (a Manhattan pier shouldn't be "near" a New Jersey town across the river).
        state = us_state(s)
        d, p = min(cand, key=lambda dp: dp[0] / math.log10(max(dp[1]["pop"], 10)) ** 1.5 * (1 if dp[1]["st"] == state else 2.5))
        k = key(p)
        towns[k] = p
        assign[s["id"]] = [k, round(d, 1)]
    for s in stations:
        for d, p in near(s["lat"], s["lng"], 8):
            if p["pop"] >= BIG_TOWN:
                towns.setdefault(key(p), p)
    out = {"stations": assign, "towns": {k: [p["name"], p["st"], round(p["lat"], 4), round(p["lng"], 4), p["pop"]]
                                         for k, p in sorted(towns.items())}}
    OUT.write_text(json.dumps(out, indent=0, ensure_ascii=False))
    print(f"{len(places)} places; {len(assign)}/{len(stations)} stations have a town; {len(towns)} town pages")


if __name__ == "__main__":
    main()
