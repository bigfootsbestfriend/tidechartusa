"""Fish recorded near each station, for the "Fish in these waters" list on station pages.

Source: GBIF occurrence records (gbif.org), limited to records released under CC0 or CC BY 4.0, so they can be used
on a commercial site with attribution. (iNaturalist's own API terms don't allow commercial use, and its CC BY-NC
records are left out here.) Ray-finned fish (their 46 GBIF orders) and sharks and rays (class 121) within 15 km of the station,
widened to 40 km where fewer than 8 species turn up. Each species is tagged salt / brackish / fresh water from
WoRMS (marinespecies.org).

Resumable: per-station answers are cached in data/species_raw/ and lookups in data/species_names.json.
Writes collector/species.json (committed, like places.json):
    {"sp": {gbifKey: [common name, scientific name, habitat "s"|"b"|"f"|"?"]},
     "st": {stationId: [radius km, [[gbifKey, records], ...]]}}

    python3 collector/species.py                 # every station in data/stations.json
    python3 collector/species.py --limit 20      # quick test
"""

import argparse
import json
import sys
import threading
import time
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"
RAW = DATA / "species_raw"
NAMES = DATA / "species_names.json"
OUT = ROOT / "collector" / "species.json"
UA = "Shorebite/1.0 (shorebite.com; hello@shorebite.com)"
GBIF = "https://api.gbif.org/v1"
# GBIF's backbone leaves ray-finned fish without a class, so they're matched by their 46 orders (Perciformes, Gadiformes,
# Pleuronectiformes...), plus class 121 for sharks, rays and skates.
BONY_ORDERS = ('494', '495', '496', '497', '498', '499', '537', '538', '547', '548', '549', '550', '587', '588', '589', '590', '708', '772', '773', '774', '888', '889', '890', '1067', '1068', '1069', '1103', '1104', '1105', '1106', '1107', '1153', '1162', '1163', '1164', '1165', '1166', '1167', '1305', '1306', '1307', '1308', '1310', '1311', '1312', '1313')
FISH = BONY_ORDERS + ("121",)
LICENSES = ("CC0_1_0", "CC_BY_4_0")
lock = threading.Lock()


def get(url, tries=5):
    for n in range(tries):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": UA})
            return json.loads(urllib.request.urlopen(req, timeout=20).read() or "null")
        except urllib.error.HTTPError as ex:
            if ex.code in (204, 404):
                return None
            if n == tries - 1:
                raise
            time.sleep((15 if ex.code == 429 else 3) * (n + 1))
        except Exception:
            if n == tries - 1:
                raise
            time.sleep(3 * (n + 1))


def near(lat, lng, km):
    q = [("geoDistance", f"{lat:.4f},{lng:.4f},{km}km"), ("occurrenceStatus", "PRESENT"), ("hasGeospatialIssue", "false"),
         ("limit", "0"), ("facet", "speciesKey"), ("facetLimit", "60")]
    q += [("taxonKey", k) for k in FISH] + [("license", lic) for lic in LICENSES]
    d = get(f"{GBIF}/occurrence/search?{urllib.parse.urlencode(q)}")
    return [[int(c["name"]), c["count"]] for c in ((d or {}).get("facets") or [{}])[0].get("counts", [])]


def station(s):
    p = RAW / f"{s['id']}.json"
    if p.exists():
        return
    try:
        r, rows = 15, near(s["lat"], s["lng"], 15)
        if len(rows) < 8:
            r, rows = 40, near(s["lat"], s["lng"], 40)
    except Exception as ex:  # GBIF busy: skip for now, the next run picks it up
        print(f"  skipped {s['id']}: {str(ex)[:60]}", flush=True)
        return
    p.write_text(json.dumps([r, rows]))


def english_name(key, sp):
    if sp.get("vernacularName"):
        return sp["vernacularName"]
    d = get(f"{GBIF}/species/{key}/vernacularNames?limit=100") or {}
    for v in d.get("results", []):
        if v.get("language") == "eng" and v.get("vernacularName"):
            return v["vernacularName"]
    return ""


# WoRMS answers already looked up for the app (scientific name -> [marine, brackish, fresh]), if present.
WORMS_CACHE = Path.home() / "Work/tideapp/raw_worms.json"
WORMS = json.loads(WORMS_CACHE.read_text()) if WORMS_CACHE.exists() else {}


def habitat(sci):
    if sci in WORMS and WORMS[sci]:
        m, b, f = WORMS[sci][:3]
        return "s" if m else "b" if b else "f" if f else "?"
    d = get(f"https://www.marinespecies.org/rest/AphiaRecordsByName/{urllib.parse.quote(sci)}?like=false&marine_only=false")
    if not d:
        return "?"
    a = next((x for x in d if x.get("status") == "accepted"), d[0])
    if a.get("isMarine"):
        return "s"
    if a.get("isBrackish"):
        return "b"
    if a.get("isFreshwater"):
        return "f"
    return "?"


def lookup(key, names):
    try:
        sp = get(f"{GBIF}/species/{key}") or {}
    except Exception:
        return
    sci = sp.get("canonicalName") or sp.get("scientificName") or ""
    if sp.get("rank") not in (None, "SPECIES") or not sci:
        names[str(key)] = None
        return
    common = english_name(key, sp)
    common = " ".join(w if w.isupper() else w[:1].upper() + w[1:] for w in common.split()) if common else ""
    with lock:
        names[str(key)] = [common, sci, habitat(sci)]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int)
    ap.add_argument("--workers", type=int, default=4)
    args = ap.parse_args()
    RAW.mkdir(parents=True, exist_ok=True)
    stations = json.loads((DATA / "stations.json").read_text())["stations"]
    if args.limit:
        stations = stations[: args.limit]
    todo = [s for s in stations if not (RAW / f"{s['id']}.json").exists()]
    print(f"{len(todo)} of {len(stations)} stations to look up", flush=True)
    with ThreadPoolExecutor(args.workers) as pool:
        for n, _ in enumerate(pool.map(station, todo), 1):
            if n % 200 == 0:
                print(f"  {n}/{len(todo)}", flush=True)

    names = json.loads(NAMES.read_text()) if NAMES.exists() else {}
    per = {s["id"]: json.loads((RAW / f"{s['id']}.json").read_text()) for s in stations if (RAW / f"{s['id']}.json").exists()}
    keys = {k for _, rows in per.values() for k, _ in rows} - {int(k) for k in names}
    print(f"{len(keys)} species to name", flush=True)
    with ThreadPoolExecutor(args.workers) as pool:
        for n, _ in enumerate(pool.map(lambda k: lookup(k, names), sorted(keys)), 1):
            if n % 200 == 0:
                print(f"  {n}/{len(keys)}", flush=True)
                NAMES.write_text(json.dumps(names))
    NAMES.write_text(json.dumps(names))

    sp, st = {}, {}
    for sid, (r, rows) in per.items():
        keep = [[k, c] for k, c in rows if names.get(str(k))]
        if keep:
            st[sid] = [r, keep[:40]]
            for k, _ in keep[:40]:
                sp[str(k)] = names[str(k)]
    OUT.write_text(json.dumps({"sp": sp, "st": st}, separators=(",", ":")))
    print(f"wrote {OUT.name}: {len(st)} stations, {len(sp)} species", flush=True)


if __name__ == "__main__":
    sys.exit(main())
