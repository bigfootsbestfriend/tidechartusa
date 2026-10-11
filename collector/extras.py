"""Extra data for the station pages, fetched after fetch.py. All sources are US government (public domain).

- Tidal currents: the nearest NOAA current prediction station (within 10 miles) for each tide
  station, with 8 days of slack / max flood / max ebb predictions -> data/currents/<id>.json
- Sensors: which tide stations measure water temperature or water level live -> data/sensors.json
  (the visitor's browser fetches the live readings itself)
- Marine forecast zone for each station -> collector/marine_zones.json. Zones hardly ever change,
  so this file is committed and only new stations are looked up.
- Nearest NDBC buoy within 40 miles -> data/buoys.json (linked, since NDBC doesn't allow browser fetches)

Nothing here is fatal: if a source fails, the pages are built without that section.

    python3 collector/extras.py
"""

import datetime as dt
import json
import math
import re
import sys
import time
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fetch import UA, get  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"
ZONES = Path(__file__).resolve().parent / "marine_zones.json"
MD = "https://api.tidesandcurrents.noaa.gov/mdapi/prod/webapi/stations.json?type="
CUR_URL = ("https://api.tidesandcurrents.noaa.gov/api/prod/datagetter?product=currents_predictions"
           "&application=tidechartusa&interval=MAX_SLACK&units=english&time_zone=lst_ldt&format=json"
           "&station={id}&bin={bin}&begin_date={begin}&range={hours}")
NWS_UA = "TideChartUSA/1.0 (hello@crossplayguide.com)"
CUR_DAYS = 8


def miles(a, b):
    la1, lo1, la2, lo2 = map(math.radians, (a[0], a[1], b[0], b[1]))
    h = math.sin((la2 - la1) / 2) ** 2 + math.cos(la1) * math.cos(la2) * math.sin((lo2 - lo1) / 2) ** 2
    return 3958.8 * 2 * math.asin(math.sqrt(h))


def nearest(pt, items, limit):
    """items: list of (lat, lng, value). Returns (miles, value) of the closest within limit, else None."""
    best = None
    for la, lo, v in items:
        if abs(la - pt[0]) > 1 or abs(lo - pt[1]) > 1.5:
            continue
        d = miles(pt, (la, lo))
        if d <= limit and (best is None or d < best[0]):
            best = (d, v)
    return best


def currents(stations):
    raw = get(MD + "currentpredictions")["stations"]
    pick = {}
    for c in raw:
        if c.get("type") not in ("H", "S") or c.get("lat") is None:
            continue
        depth = c["depth"] if c.get("depth") is not None else 999
        if c["id"] not in pick or depth < pick[c["id"]]["depth"]:
            pick[c["id"]] = {"id": c["id"], "name": c["name"].strip(), "lat": c["lat"], "lng": c["lng"],
                             "bin": c["currbin"], "depth": depth}
    items = [(c["lat"], c["lng"], c["id"]) for c in pick.values()]
    link = {}
    for s in stations:
        hit = nearest((s["lat"], s["lng"]), items, 10)
        if hit:
            link[s["id"]] = [hit[1], round(hit[0], 1)]
    need = sorted({cid for cid, _ in link.values()})
    begin = (dt.datetime.now(dt.timezone.utc).date() - dt.timedelta(days=1)).strftime("%Y%m%d")
    out = DATA / "currents"
    out.mkdir(parents=True, exist_ok=True)

    def one(cid):
        c = pick[cid]
        try:
            j = get(CUR_URL.format(id=cid, bin=c["bin"], begin=begin, hours=CUR_DAYS * 24))
            cp = (j.get("current_predictions") or {}).get("cp")
            if not cp:
                return cid, False
            c["flood"], c["ebb"] = cp[0].get("meanFloodDir"), cp[0].get("meanEbbDir")
            (out / f"{cid}.json").write_text(json.dumps(
                [[p["Time"], round(float(p["Velocity_Major"]), 2), p["Type"][0].upper()] for p in cp],
                separators=(",", ":")))
            return cid, True
        except Exception:
            return cid, False

    with ThreadPoolExecutor(3) as pool:
        ok = {cid for cid, good in pool.map(one, need) if good}
    meta = {cid: pick[cid] for cid in ok}
    links = {sid: v for sid, v in link.items() if v[0] in ok}
    (DATA / "currents.json").write_text(json.dumps({"stations": meta, "links": links}, separators=(",", ":")))
    print(f"currents: {len(ok)}/{len(need)} current stations, linked to {len(links)} tide stations")


def sensors():
    out = {}
    for key, kind in (("wt", "watertemp"), ("wl", "waterlevels")):
        try:
            out[key] = sorted({s["id"] for s in get(MD + kind)["stations"]})
        except Exception as ex:
            print(f"sensors {kind} failed: {ex}", file=sys.stderr)
            out[key] = []
    (DATA / "sensors.json").write_text(json.dumps(out, separators=(",", ":")))
    print(f"sensors: {len(out['wt'])} water temp, {len(out['wl'])} water level")


def nws(url):
    req = urllib.request.Request(url, headers={"User-Agent": NWS_UA, "Accept": "application/geo+json"})
    return json.loads(urllib.request.urlopen(req, timeout=30).read())


def zone_at(lat, lng):
    """Marine zone containing the point, else the first found nudging out up to ~12 miles (docks sit on land)."""
    for r in (0, 0.03, 0.08, 0.18):
        for dy, dx in ([(0, 0)] if r == 0 else [(1, 0), (-1, 0), (0, 1), (0, -1), (1, 1), (1, -1), (-1, 1), (-1, -1)]):
            for _ in range(3):
                try:
                    j = nws(f"https://api.weather.gov/zones?type=marine&point={lat + dy * r:.4f},{lng + dx * r:.4f}")
                    break
                except Exception:
                    time.sleep(2)
            else:
                return None
            for f in j.get("features", []):
                p = f["properties"]
                offices = p.get("forecastOffices") or []
                office = offices[0].rsplit("/", 1)[-1] if offices else ""
                return [p["id"], p["name"], office]
    return []


def marine_zones(stations, budget=900):
    cache = json.loads(ZONES.read_text()) if ZONES.exists() else {}
    todo = [s for s in stations if s["id"] not in cache][:budget]

    def one(s):
        return s["id"], zone_at(s["lat"], s["lng"])

    with ThreadPoolExecutor(4) as pool:
        for sid, z in pool.map(one, todo):
            if z is not None:  # None = network trouble; try again next run
                cache[sid] = z
    ZONES.write_text(json.dumps(dict(sorted(cache.items())), indent=0))
    have = sum(1 for s in stations if cache.get(s["id"]))
    print(f"marine zones: looked up {len(todo)}, {have}/{len(stations)} stations have a zone")


def buoys(stations):
    req = urllib.request.Request("https://www.ndbc.noaa.gov/activestations.xml", headers={"User-Agent": UA})
    xml = urllib.request.urlopen(req, timeout=60).read().decode("utf-8", "replace")
    items = []
    for m in re.finditer(r"<station ([^>]+?)/?>", xml):
        a = dict(re.findall(r'(\w+)="([^"]*)"', m.group(1)))
        if a.get("type") == "buoy" and a.get("met") == "y" and a.get("lat"):
            items.append((float(a["lat"]), float(a["lon"]), [a["id"], a.get("name", "").strip()]))
    out = {}
    for s in stations:
        hit = nearest((s["lat"], s["lng"]), items, 40)
        if hit:
            out[s["id"]] = [*hit[1], round(hit[0])]
    (DATA / "buoys.json").write_text(json.dumps(out, separators=(",", ":")))
    print(f"buoys: {len(items)} active weather buoys, linked to {len(out)} stations")


def main():
    stations = json.loads((DATA / "stations.json").read_text())["stations"]
    for name, fn in (("currents", lambda: currents(stations)), ("sensors", sensors),
                     ("marine zones", lambda: marine_zones(stations)), ("buoys", lambda: buoys(stations))):
        try:
            fn()
        except Exception as ex:
            print(f"{name} failed: {ex}", file=sys.stderr)


if __name__ == "__main__":
    main()
