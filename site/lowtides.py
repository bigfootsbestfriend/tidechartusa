"""Tide pooling: each spot's best daylight low tides over the next 12 months.

A low is good for tide pooling when it's among the spot's lowest 10% of low tides for the coming year and comes
between an hour after sunrise and sunset (people go out in the hour before the low). Working from each spot's own
predictions gives the right season everywhere, e.g. winter afternoons in Southern California, spring and summer
mornings in Oregon and Washington.
"""

import datetime as dt

import astro

LOW = 0.10  # lows at or below this percentile of the next 12 months' lows count as tide pool lows


def lows_for(raws, tz, lat, lng, today):
    """{"cut", "good": [(datetime, height)] (one per day, soonest first), "months": {"YYYY-MM": days},
    "lowest": (datetime, height)}, or None without (nearly) a year of predictions."""
    end = today + dt.timedelta(days=365)
    lows, days_seen = [], set()
    for year, raw in raws.items():
        for t, v, k in raw:
            try:
                w = dt.datetime.strptime(f"{year}-{t}", "%Y-%m-%d %H:%M").replace(tzinfo=tz)
            except ValueError:
                continue
            if not today <= w.date() < end:
                continue
            days_seen.add(w.date())
            if k == "L":
                lows.append((w, v))
    if len(days_seen) < 300 or not lows:
        return None
    vals = sorted(v for _, v in lows)
    cut = vals[int(LOW * (len(vals) - 1))]
    best = {}
    for w, v in lows:
        if v > cut:
            continue
        d = w.date()
        rise, sset = astro.sun(lat, lng, d, tz)
        # Tide pooling happens in the hour or so before the low, so it needs light from an hour before it.
        if not rise or not rise + dt.timedelta(hours=1) <= w <= sset:
            continue
        if d not in best or v < best[d][1]:
            best[d] = (w, v)
    good = [best[d] for d in sorted(best)]
    if not good:
        return None
    months = {}
    for w, _ in good:
        months[f"{w:%Y-%m}"] = months.get(f"{w:%Y-%m}", 0) + 1
    return {"cut": cut, "good": good, "months": months, "lowest": min(good, key=lambda x: x[1])}


def runs(good):
    """Group good days into runs (a day or two apart): [(first_dt, last_dt, lowest (dt, v))]."""
    out = []
    for w, v in good:
        if out and (w.date() - out[-1][1].date()).days <= 2:
            first, _, lo = out[-1]
            out[-1] = (first, w, lo if lo[1] <= v else (w, v))
        else:
            out.append((w, w, (w, v)))
    return out
