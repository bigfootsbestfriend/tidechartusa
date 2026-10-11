"""Download a full calendar year of high/low predictions for every US station, for the printable
"<year> tide table" pages. Predictions for a year don't change, so the yearly workflow runs this once a
month and keeps the result in the GitHub Actions cache; the nightly build restores it.

    python3 collector/year.py 2027            # -> data/year/2027/<station id>.json
    python3 collector/year.py 2027 --limit 20 # quick test
"""

import argparse
import json
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fetch import STATIONS_URL, get, us_state  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
URL = ("https://api.tidesandcurrents.noaa.gov/api/prod/datagetter?product=predictions&application=shorebite"
       "&datum=MLLW&time_zone=lst_ldt&units=english&interval=hilo&format=json&station={id}"
       "&begin_date={y}0101&end_date={y}1231")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("year", type=int)
    ap.add_argument("--limit", type=int)
    ap.add_argument("--workers", type=int, default=4)
    ap.add_argument("--minutes", type=float, help="stop starting new downloads after this long (the rest waits for the next run)")
    args = ap.parse_args()
    out = ROOT / "data" / "year" / str(args.year)
    out.mkdir(parents=True, exist_ok=True)
    stations = [s for s in get(STATIONS_URL)["stations"] if us_state(s) and s.get("lat") is not None]
    todo = [s for s in stations if not (out / f"{s['id']}.json").exists()][: args.limit]

    stop_at = time.time() + args.minutes * 60 if args.minutes else None

    def one(s):
        if stop_at and time.time() > stop_at:
            return False
        try:
            preds = get(URL.format(id=s["id"], y=args.year)).get("predictions")
            if not preds:
                return False
            # "MM-DD HH:MM" local time, height in feet, H or L.
            (out / f"{s['id']}.json").write_text(json.dumps(
                [[p["t"][5:], round(float(p["v"]), 2), p["type"]] for p in preds], separators=(",", ":")))
            return True
        except Exception as ex:
            print(f"failed {s['id']}: {str(ex)[:100]}", file=sys.stderr)
            return False

    t0 = time.time()
    with ThreadPoolExecutor(args.workers) as pool:
        ok = sum(pool.map(one, todo))
    have = len(list(out.glob("*.json")))
    print(f"{args.year}: fetched {ok}/{len(todo)} in {time.time() - t0:.0f}s; {have} stations on disk"
          + (" (stopped at the time limit; the next run continues)" if stop_at and time.time() > stop_at else ""))


if __name__ == "__main__":
    main()
