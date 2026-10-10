"""Download NOAA tide prediction stations and their high/low predictions.

Writes data/stations.json and data/pred/<station id>.json. NOAA CO-OPS data is a US
government work (public domain). Exits non-zero if too many stations fail, so the
nightly workflow keeps yesterday's site instead of publishing a half-empty one.

    python3 collector/fetch.py              # every US station
    python3 collector/fetch.py --limit 40   # quick local test
"""

import argparse
import datetime as dt
import json
import sys
import time
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"
STATIONS_URL = "https://api.tidesandcurrents.noaa.gov/mdapi/prod/webapi/stations.json?type=tidepredictions"
PRED_URL = ("https://api.tidesandcurrents.noaa.gov/api/prod/datagetter?product=predictions"
            "&application=tidechartusa&datum=MLLW&time_zone=lst_ldt&units=english"
            "&interval=hilo&format=json&station={id}&begin_date={begin}&range={hours}")
UA = "TideChartUSA/1.0 (static tide chart site; contact via GitHub bigfootsbestfriend/tidechartusa)"

# US states and territories. NOAA leaves "state" blank for a few US islands, so those are
# matched by name; every other blank-state station is outside the US and skipped.
US_CODES = {"AL", "AK", "CA", "CT", "DC", "DE", "FL", "GA", "HI", "LA", "MA", "MD", "ME", "MS",
            "NC", "NH", "NJ", "NY", "OR", "PA", "RI", "SC", "TX", "VA", "WA", "PR", "VI", "GU",
            "AS", "FM", "MP"}
BLANK_STATE_US = {"GUAM": "GU", "MIDWAY": "UM", "WAKE ISLAND": "UM", "JOHNSTON ATOLL": "UM",
                  "PAGO PAGO": "AS", "SAIPAN": "MP", "TINIAN": "MP", "ROTA": "MP"}

DAYS = 33  # starts yesterday so every US time zone still has "today" when the site is built


def get(url, tries=5):
    for n in range(tries):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": UA})
            return json.loads(urllib.request.urlopen(req, timeout=40).read())
        except urllib.error.HTTPError as ex:
            # NOAA answers 403/429 when it thinks we're going too fast: back off properly.
            if n == tries - 1:
                raise
            time.sleep((20 if ex.code in (403, 429) else 3) * (n + 1))
        except Exception:
            if n == tries - 1:
                raise
            time.sleep(3 * (n + 1))


def us_state(s):
    if s.get("state") in US_CODES:
        return s["state"]
    if not s.get("state"):
        name = s["name"].upper()
        for key, code in BLANK_STATE_US.items():
            if key in name:
                return code
    return None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, help="only fetch this many stations (testing)")
    ap.add_argument("--workers", type=int, default=3)
    args = ap.parse_args()

    stations = []
    for s in get(STATIONS_URL)["stations"]:
        st = us_state(s)
        if not st or s.get("lat") is None:
            continue
        stations.append({"id": s["id"], "name": s["name"].strip(), "state": st, "lat": s["lat"],
                         "lng": s["lng"], "type": s.get("type") or "", "ref": s.get("reference_id") or "",
                         "tzcorr": s.get("timezonecorr")})
    stations.sort(key=lambda s: (s["state"], s["name"]))
    if args.limit:
        stations = stations[: args.limit]

    begin = (dt.datetime.now(dt.timezone.utc).date() - dt.timedelta(days=1)).strftime("%Y%m%d")
    out = DATA / "pred"
    out.mkdir(parents=True, exist_ok=True)

    def one(s):
        try:
            j = get(PRED_URL.format(id=s["id"], begin=begin, hours=DAYS * 24))
            preds = j.get("predictions")
            if not preds:
                return s["id"], j.get("error", {}).get("message", "no predictions")
            (out / f"{s['id']}.json").write_text(json.dumps(
                [[p["t"], round(float(p["v"]), 2), p["type"]] for p in preds], separators=(",", ":")))
            return s["id"], None
        except Exception as ex:
            return s["id"], str(ex)[:120]

    with ThreadPoolExecutor(args.workers) as pool:
        results = list(pool.map(one, stations))
    failed = {sid: err for sid, err in results if err}
    # Second, slower pass for anything that failed (usually throttling).
    retry = [s for s in stations if s["id"] in failed and "No Predictions" not in failed[s["id"]]]
    if retry:
        print(f"retrying {len(retry)} stations one at a time")
        time.sleep(60)
        for s in retry:
            sid, err = one(s)
            if err:
                failed[sid] = err
            else:
                failed.pop(sid, None)
            time.sleep(1)
    ok = [s for s in stations if s["id"] not in failed]
    (DATA / "stations.json").write_text(json.dumps(
        {"fetched": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"), "begin": begin,
         "stations": ok}, indent=0))
    for sid, err in list(failed.items())[:20]:
        print(f"failed {sid}: {err}", file=sys.stderr)
    print(f"{len(ok)} stations saved, {len(failed)} failed")
    if len(failed) > 0.05 * max(1, len(stations)):
        sys.exit("too many failures; not publishing")


if __name__ == "__main__":
    main()
