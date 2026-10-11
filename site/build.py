"""Build the static site from data/ into _site/.

    python3 site/build.py
    SITE_URL=https://tidechartusa.com python3 site/build.py   # after the domain is live

Stdlib only. Every station gets a page with today's chart, a week of tide times, a month
tide table, sun and moon, and a short write-up computed from its own predictions.
"""

import datetime as dt
import html
import json
import math
import os
import re
import shutil
import statistics
import sys
import unicodedata
from pathlib import Path
from urllib.parse import urlparse
from zoneinfo import ZoneInfo

sys.path.insert(0, str(Path(__file__).resolve().parent))
import astro  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"
OUT = ROOT / "_site"
STATIC = Path(__file__).resolve().parent / "static"

# Flip to True when Mike approves launch: drops noindex and publishes the sitemap.
LAUNCHED = False
SITE_URL = os.environ.get("SITE_URL", "https://bigfootsbestfriend.github.io/tidechartusa").rstrip("/")
BASE = urlparse(SITE_URL).path.rstrip("/") + "/"
SITE_NAME = "Tide Chart USA"
# Email signups (alerts/ Worker). Empty hides every signup form; set once Resend is verified.
ALERTS_API = os.environ.get("ALERTS_API", "")

STATES = {
    "AL": "Alabama", "AK": "Alaska", "CA": "California", "CT": "Connecticut", "DC": "Washington, D.C.",
    "DE": "Delaware", "FL": "Florida", "GA": "Georgia", "HI": "Hawaii", "LA": "Louisiana",
    "MA": "Massachusetts", "MD": "Maryland", "ME": "Maine", "MS": "Mississippi", "NC": "North Carolina",
    "NH": "New Hampshire", "NJ": "New Jersey", "NY": "New York", "OR": "Oregon", "PA": "Pennsylvania",
    "RI": "Rhode Island", "SC": "South Carolina", "TX": "Texas", "VA": "Virginia", "WA": "Washington",
    "PR": "Puerto Rico", "VI": "U.S. Virgin Islands", "GU": "Guam", "AS": "American Samoa",
    "FM": "Micronesia", "MP": "Northern Mariana Islands", "UM": "U.S. Pacific Islands",
}
NO_DST = {"HI": "Pacific/Honolulu", "PR": "America/Puerto_Rico", "VI": "America/St_Thomas",
          "GU": "Pacific/Guam", "MP": "Pacific/Saipan", "AS": "Pacific/Pago_Pago"}
BY_OFFSET = {-4: "America/Puerto_Rico", -5: "America/New_York", -6: "America/Chicago", -7: "America/Denver",
             -8: "America/Los_Angeles", -9: "America/Anchorage", -10: "America/Adak", -11: "Pacific/Midway",
             10: "Pacific/Chuuk", 11: "Pacific/Pohnpei", 12: "Pacific/Wake"}

# Small words kept lower case when NOAA's ALL-CAPS station names are tidied.
SMALL = {"of", "the", "and", "at", "on", "in", "de", "del", "la", "to", "for"}
KEEP_CAPS = {"USCG", "NOAA", "CG", "AFB", "NAS", "USS", "NE", "NW", "SE", "SW", "NNE", "NNW", "SSE", "SSW",
             "ENE", "ESE", "WNW", "WSW", "II", "III", "ICW", "RR", "SR", "US"}


def esc(s):
    return html.escape(str(s), quote=True)


def slugify(s):
    s = unicodedata.normalize("NFKD", s).encode("ascii", "ignore").decode().lower()
    return re.sub(r"[^a-z0-9]+", "-", s).strip("-")


def tidy(name):
    """NOAA names are a mix of 'PAGO PAGO Harbor' and 'Miami Beach, Biscayne Bay'. Fix the shouting."""
    def fix(word, first):
        core = re.sub(r"[^A-Za-z]", "", word)
        if len(core) > 1 and core.isupper() and core not in KEEP_CAPS:
            word = word.lower()
            if first or core.lower() not in SMALL:
                word = re.sub(r"[a-z]", lambda m: m.group().upper(), word, count=1)
                word = re.sub(r"(?<=[-'.(/])[a-z]", lambda m: m.group().upper(), word)
        return word
    words = re.split(r"(\s+)", name.strip())
    out, first = [], True
    for w in words:
        if w.isspace():
            out.append(" ")
            continue
        out.append(fix(w, first))
        first = False
    s = "".join(out)
    s = re.sub(r"\s+,", ",", s)
    return re.sub(r"\s{2,}", " ", s)


def zone_for(st):
    if st["state"] in NO_DST:
        return ZoneInfo(NO_DST[st["state"]])
    off = st.get("tzcorr")
    if st["state"] == "UM" and off == -10:
        return ZoneInfo("Pacific/Honolulu")
    if off in BY_OFFSET:
        return ZoneInfo(BY_OFFSET[off])
    return dt.timezone(dt.timedelta(hours=off or 0))


def miles(a, b):
    la1, lo1, la2, lo2 = map(math.radians, (a["lat"], a["lng"], b["lat"], b["lng"]))
    h = math.sin((la2 - la1) / 2) ** 2 + math.cos(la1) * math.cos(la2) * math.sin((lo2 - lo1) / 2) ** 2
    return 3958.8 * 2 * math.asin(math.sqrt(h))


def clock(t):
    return t.strftime("%I:%M %p").lstrip("0")


def ft(v):
    return f"{v:.1f} ft".replace("-0.0", "0.0")


def day_label(d, short=False):
    return d.strftime("%a %b %-d") if short else d.strftime("%A, %B %-d")


# ---------- page shell ----------

CSS_VER = "12"


def page(title, desc, path, body, *, crumbs=None, scripts=(), extra_head=""):
    url = SITE_URL + "/" + path
    robots = "" if LAUNCHED else '<meta name="robots" content="noindex, nofollow">'
    ld = ""
    if crumbs:
        items = [{"@type": "ListItem", "position": i + 1, "name": n, "item": SITE_URL + "/" + p}
                 for i, (n, p) in enumerate(crumbs)]
        ld = '<script type="application/ld+json">' + json.dumps(
            {"@context": "https://schema.org", "@type": "BreadcrumbList", "itemListElement": items}) + "</script>"
        trail = " › ".join(
            f'<a href="{BASE}{p}">{esc(n)}</a>' if i < len(crumbs) - 1 else f"<span>{esc(n)}</span>"
            for i, (n, p) in enumerate(crumbs))
        body = f'<nav class="crumbs" aria-label="Breadcrumb">{trail}</nav>' + body
    js = "".join(f'<script src="{BASE}static/{s}?v={CSS_VER}" defer></script>' for s in scripts)
    return f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{esc(title)}</title>
<meta name="description" content="{esc(desc)}">
{robots}
<link rel="canonical" href="{esc(url)}">
<link rel="icon" href="{BASE}static/favicon.svg" type="image/svg+xml">
<link rel="manifest" href="{BASE}manifest.webmanifest">
<link rel="apple-touch-icon" href="{BASE}static/icon-192.png">
<meta name="theme-color" content="#0b5c7a">
<link rel="stylesheet" href="{BASE}static/style.css?v={CSS_VER}">
<meta property="og:title" content="{esc(title)}">
<meta property="og:description" content="{esc(desc)}">
<meta property="og:url" content="{esc(url)}">
<meta property="og:type" content="website">
{ld}{extra_head}
</head>
<body>
<header class="top"><div class="wrap">
<a class="brand" href="{BASE}"><svg viewBox="0 0 32 32" aria-hidden="true"><path d="M2 20c4 0 4-4 8-4s4 4 8 4 4-4 8-4 4 4 4 4v8H2z"/></svg>{SITE_NAME}</a>
<nav><a href="{BASE}states/">States</a><a href="{BASE}how-to-read-a-tide-chart/">How to read</a></nav>
</div></header>
<main class="wrap">
{body}
</main>
<footer class="foot"><div class="wrap">
<p>Tide and current predictions and live readings from <a href="https://tidesandcurrents.noaa.gov/">NOAA CO-OPS</a>, buoys from <a href="https://www.ndbc.noaa.gov/">NOAA NDBC</a>, marine forecasts from the <a href="https://www.weather.gov/marine/">National Weather Service</a>. Predictions refresh every night. Predictions are not observations: wind, pressure and river flow can move the real water level. <strong>Not for navigation.</strong></p>
<p><a href="{BASE}about/">About</a> · <a href="{BASE}privacy/">Privacy</a> · <a href="{BASE}how-to-read-a-tide-chart/">How to read a tide chart</a> · Not affiliated with NOAA.</p>
</div></footer>
{js}
<script src="{BASE}static/app.js?v={CSS_VER}" defer></script>
</body>
</html>
"""


def write(path, text):
    p = OUT / path
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text)


# ---------- tide curve ----------

def curve_points(events, t0, t1, step=600):
    """Cosine interpolation between high/low events: the usual way tide tables are drawn."""
    pts = []
    ev = events
    i = 0
    t = t0
    while t <= t1:
        while i + 1 < len(ev) and ev[i + 1][0] <= t:
            i += 1
        if i + 1 >= len(ev) or ev[i][0] > t:
            t += step
            continue
        (ta, ha, _), (tb, hb, _) = ev[i], ev[i + 1]
        f = (t - ta) / (tb - ta)
        pts.append((t, ha + (hb - ha) * (1 - math.cos(math.pi * f)) / 2))
        t += step
    return pts


def svg_chart(events, t0, t1, tz, sunrise=None, sunset=None):
    """Server-side SVG for one day; static/tide.js redraws it with a 'now' marker in the browser."""
    pts = curve_points(events, t0, t1)
    if len(pts) < 2:
        return ""
    W, H, PAD_L, PAD_B, PAD_T = 640, 220, 34, 26, 22
    lo = min(p[1] for p in pts)
    hi = max(p[1] for p in pts)
    span = (hi - lo) or 1
    lo -= span * 0.12
    hi += span * 0.15

    def x(t):
        return PAD_L + (t - t0) / (t1 - t0) * (W - PAD_L - 6)

    def y(v):
        return PAD_T + (hi - v) / (hi - lo) * (H - PAD_T - PAD_B)

    line = " ".join(f"{x(t):.1f},{y(v):.1f}" for t, v in pts)
    area = f"M{x(pts[0][0]):.1f},{H - PAD_B} L" + line.replace(" ", " L") + f" L{x(pts[-1][0]):.1f},{H - PAD_B} Z"
    parts = [f'<svg class="chart" viewBox="0 0 {W} {H}" role="img" aria-label="Tide height through the day">']
    if sunrise and sunset:
        a, b = x(max(t0, sunrise.timestamp())), x(min(t1, sunset.timestamp()))
        parts.append(f'<rect class="day" x="{a:.1f}" y="{PAD_T}" width="{max(0, b - a):.1f}" height="{H - PAD_T - PAD_B}"/>')
    for hr in (0, 6, 12, 18, 24):
        tx = x(t0 + hr * 3600)
        label = {0: "12 AM", 6: "6 AM", 12: "12 PM", 18: "6 PM", 24: ""}[hr]
        parts.append(f'<line class="grid" x1="{tx:.1f}" x2="{tx:.1f}" y1="{PAD_T}" y2="{H - PAD_B}"/>')
        if label:
            parts.append(f'<text class="ax" x="{tx + 3:.1f}" y="{H - 8}">{label}</text>')
    if lo < 0 < hi:
        parts.append(f'<line class="zero" x1="{PAD_L}" x2="{W - 6}" y1="{y(0):.1f}" y2="{y(0):.1f}"/>')
    parts.append(f'<path class="area" d="{area}"/><polyline class="line" points="{line}"/>')
    for t, v, kind in events:
        if t0 <= t <= t1:
            cx, cy = x(t), y(v)
            lab = f"{clock(dt.datetime.fromtimestamp(t, tz))} · {ft(v)}"
            ty = cy - 9 if kind == "H" else cy + 17
            anchor = "start" if cx < 90 else "end" if cx > W - 90 else "middle"
            parts.append(f'<circle class="pt {kind}" cx="{cx:.1f}" cy="{cy:.1f}" r="4"/>'
                         f'<text class="lab" x="{cx:.1f}" y="{ty:.1f}" text-anchor="{anchor}">{lab}</text>')
    parts.append(f'<text class="ax" x="2" y="{PAD_T + 4}">{ft(hi - span * 0.15)}</text>')
    parts.append("</svg>")
    return "".join(parts)


# ---------- per-station analysis ----------

def load_station(st):
    raw = json.loads((DATA / "pred" / f"{st['id']}.json").read_text())
    tz = zone_for(st)
    events = []
    for t, v, kind in raw:
        local = dt.datetime.strptime(t, "%Y-%m-%d %H:%M").replace(tzinfo=tz)
        events.append((local.timestamp(), v, kind))
    days = sorted({dt.datetime.fromtimestamp(t, tz).date() for t, _, _ in events})
    # The first and last days are partial (prediction window edges); keep full days only.
    days = days[1:-1]
    return tz, events, days


def describe(st, tz, events, days):
    """Facts for the write-up, all computed from this station's own predictions for `days`."""
    window = set(days)
    by_day = {}
    for t, v, k in events:
        d = dt.datetime.fromtimestamp(t, tz).date()
        if d in window:
            by_day.setdefault(d, []).append((t, v, k))
    inside = [e for d in days for e in by_day.get(d, [])]
    ranges = [abs(a[1] - b[1]) for a, b in zip(inside, inside[1:]) if a[2] != b[2]]
    full = [d for d in days if d in by_day]
    per_day = statistics.mean(sum(1 for e in by_day[d] if e[2] == "H") for d in full) if full else 0
    # Inequality: how different the two daily highs are, compared with the typical range.
    diffs = [abs(h[0][1] - h[1][1]) for d in full
             for h in [[e for e in by_day[d] if e[2] == "H"]] if len(h) >= 2]
    mean_range = statistics.mean(ranges) if ranges else 0
    if per_day < 1.5:
        kind = "diurnal"
    elif diffs and mean_range and statistics.mean(diffs) > 0.25 * mean_range:
        kind = "mixed"
    else:
        kind = "semidiurnal"
    # A day's range comes from the curve, not just that day's turns: a day with a single low
    # still has the water falling into it and rising out of it.
    day_ranges = []
    for d in full:
        a = dt.datetime.combine(d, dt.time(0), tz).timestamp()
        pts = [v for _, v in curve_points(events, a, a + 86400, step=1200)]
        if pts:
            day_ranges.append((max(pts) - min(pts), d))
    day_ranges.sort(reverse=True)
    big = []
    for r, d in day_ranges:
        if all(abs((d - b).days) >= 5 for _, b in big):
            big.append((r, d))
        if len(big) == 2:
            break
    return {"kind": kind, "mean_range": mean_range, "big": big,
            "small": day_ranges[-1] if day_ranges else None,
            "top_high": max((e for e in inside if e[2] == "H"), key=lambda e: e[1], default=None),
            "low_low": min((e for e in inside if e[2] == "L"), key=lambda e: e[1], default=None),
            "by_day": by_day, "minus": sum(1 for e in inside if e[2] == "L" and e[1] < 0)}


KIND_TEXT = {
    "semidiurnal": "two high tides and two low tides almost every day, and the two highs are close in height",
    "mixed": "two high tides and two low tides most days, but one high is clearly higher than the other "
             "(and one low clearly lower), which is called a mixed tide",
    "diurnal": "usually just one high tide and one low tide a day",
}


def writeup(st, name, f, tz):
    paras = []
    paras.append(f"{esc(name)} gets {KIND_TEXT[f['kind']]}. Over the next month the water typically rises or "
                 f"falls about <strong>{ft(f['mean_range'])}</strong> between a high and the next low.")
    if f["big"]:
        r, d = f["big"][0]
        s = (f"The biggest swings in this window come around <strong>{day_label(d)}</strong>, when the day's "
             f"range reaches {ft(r)}")
        if len(f["big"]) > 1:
            r2, d2 = f["big"][1]
            s += f", and again around {day_label(d2)} ({ft(r2)})"
        s += (". Those spring tides follow the new and full moon by a day or two." if f["kind"] == "semidiurnal" else
              ". Here the biggest ranges depend on the moon's phase and on how far north or south of the equator "
              "it is, so they don't always line up with the new and full moon.")
        if f["small"]:
            s += (f" The calmest day is {day_label(f['small'][1])}, with only {ft(f['small'][0])} between the "
                  f"day's highest and lowest water.")
        paras.append(s)
    if f["low_low"]:
        t, v, _ = f["low_low"]
        when = dt.datetime.fromtimestamp(t, tz)
        s = f"The lowest tide of the month is {ft(v)} at {clock(when)} on {day_label(when.date())}."
        if f["minus"]:
            s += (f" There are {f['minus']} minus tides (lows below the chart's zero line) in this window: "
                  f"the best times for tide pools, clamming and walking the flats.")
        paras.append(s)
    if f["top_high"]:
        t, v, _ = f["top_high"]
        when = dt.datetime.fromtimestamp(t, tz)
        paras.append(f"The highest predicted tide is {ft(v)} at {clock(when)} on {day_label(when.date())}. "
                     f"Onshore wind or a storm can push the real water level above that.")
    if st["type"] == "S":
        paras.append("This is a <em>subordinate</em> station: NOAA calculates its times and heights by "
                     "adjusting a nearby reference station, so expect them to be a few minutes or a few tenths "
                     "of a foot off on any given day.")
    else:
        paras.append("This is a <em>reference</em> (harmonic) station: NOAA predicts its tides directly from "
                     "years of measured water levels here, which makes it among the most reliable predictions "
                     "on the coast.")
    return "".join(f"<p>{p}</p>" for p in paras)


def daylight_lows(f, days, tz, sun_by_day, limit=6):
    out = []
    for d in days[:14]:
        rise, sset = sun_by_day.get(d, (None, None))
        if not rise:
            continue
        for t, v, k in f["by_day"].get(d, []):
            if k == "L" and rise.timestamp() <= t <= sset.timestamp():
                out.append((v, t))
    out.sort()
    return out[:limit]


COMPASS = ["N", "NNE", "NE", "ENE", "E", "ESE", "SE", "SSE", "S", "SSW", "SW", "WSW", "W", "WNW", "NW", "NNW"]


def compass(deg):
    return COMPASS[round((deg or 0) / 22.5) % 16] if deg is not None else ""


def currents_section(name, cur, week, tz):
    """Slack water and peak flood/ebb for the nearest NOAA current station, for the week shown."""
    if not cur:
        return ""
    meta, dist, events = cur
    by_day = {}
    for t, v, k in events:
        when = dt.datetime.strptime(t, "%Y-%m-%d %H:%M").replace(tzinfo=tz)
        by_day.setdefault(when.date(), []).append((when, v, k))
    rows = []
    for d in week:
        cells = []
        for when, v, k in by_day.get(d, []):
            if k == "S":
                cells.append(f'<span class="ev slack"><b>Slack</b> {clock(when)}</span>')
            else:
                flood = k == "F"
                cells.append(f'<span class="ev {"flood" if flood else "ebb"}"><b>{"Flood" if flood else "Ebb"}</b> '
                             f'{clock(when)} <i>{abs(v):.1f} kn</i></span>')
        rows.append(f'<tr data-day="{d.isoformat()}"><th scope="row">{day_label(d, True)}</th>'
                    f'<td class="evs">{"".join(cells) or "—"}</td></tr>')
    fl, eb = meta.get("flood"), meta.get("ebb")
    dirs = (f" The flood runs toward the {compass(fl)} ({fl}°) and the ebb toward the {compass(eb)} ({eb}°)."
            if fl is not None and eb is not None else "")
    peak = max((abs(v) for _, v, k in events if k in "FE"), default=0)
    depth = f" at {meta['depth']:.0f} ft depth" if meta.get("depth") not in (None, 999) else ""
    return f"""
<h2 id="currents">Tidal currents near {esc(name)}</h2>
<p>From NOAA's current predictions for <strong>{esc(tidy(meta['name']))}</strong>{depth}, {dist:.1f} miles away.
<b>Slack</b> is when the current turns and the water is calmest; <b>flood</b> runs in with the rising tide and <b>ebb</b> runs out
with the falling tide. Times are the peak of each run, in knots.{dirs} The strongest current this week is {peak:.1f} knots.</p>
<div class="scroll"><table class="tides week currents"><thead><tr><th>Day</th><th>Slack water and peak currents</th></tr></thead>
<tbody>{"".join(rows)}</tbody></table></div>
<p class="note">Current predictions can differ a lot over short distances: check the station location on NOAA before planning a passage.</p>"""


FISH_LABELS = ["Fair", "Fair", "Good", "Very good", "Excellent"]


def fish_day(st, d, tz, f, sun_by_day):
    """Solunar score (0-4) and major/minor periods for one day. Also feeds the trip planner."""
    mt = astro.moon_times(st["lat"], st["lng"], d, tz)
    majors = sorted(mt["over"] + mt["under"])
    minors = sorted(mt["rise"] + mt["set"])
    ph, lit = astro.moon(dt.datetime.combine(d, dt.time(12), tz))
    score = 2 if lit <= 10 or lit >= 90 else 1 if lit <= 25 or lit >= 75 else 0
    rise, sset = sun_by_day.get(d, (None, None))
    windows = [(m - dt.timedelta(hours=1), m + dt.timedelta(hours=1)) for m in majors] + \
              [(m - dt.timedelta(minutes=30), m + dt.timedelta(minutes=30)) for m in minors]
    if rise and any(a - dt.timedelta(hours=1) <= x <= b + dt.timedelta(hours=1)
                    for a, b in windows for x in (rise, sset)):
        score += 1
    turns = [dt.datetime.fromtimestamp(t, tz) for t, _, _ in f["by_day"].get(d, [])]
    if any(a <= x <= b for a, b in windows[:len(majors)] for x in turns):
        score += 1
    return min(score, 4), majors, minors


def fishing_section(st, name, week, tz, f, sun_by_day):
    """Solunar periods (moon overhead/underfoot = major, moonrise/moonset = minor) and a simple day rating."""
    rows = []
    for d in week:
        score, majors, minors = fish_day(st, d, tz, f, sun_by_day)
        label = FISH_LABELS[score]
        span = lambda a, b: f"{clock(a)}–{clock(b)}"
        maj = ", ".join(span(m - dt.timedelta(hours=1), m + dt.timedelta(hours=1)) for m in majors) or "—"
        mnr = ", ".join(span(m - dt.timedelta(minutes=30), m + dt.timedelta(minutes=30)) for m in minors) or "—"
        rows.append(f'<tr data-day="{d.isoformat()}"><th scope="row">{day_label(d, True)}</th>'
                    f'<td><span class="rate r{score}">{label}</span></td><td>{maj}</td><td>{mnr}</td></tr>')
    return f"""
<h2 id="fishing">Best fishing times at {esc(name)}</h2>
<p>Solunar periods for this spot: <b>major</b> periods (about two hours) are centred on the moon passing overhead or underfoot,
and <b>minor</b> periods (about an hour) on moonrise and moonset. Days near the new and full moon rate higher, and so does a
period that lines up with sunrise, sunset or a turn of the tide.</p>
<div class="scroll"><table class="tides week fishing"><thead><tr><th>Day</th><th>Rating</th><th>Major periods</th><th>Minor periods</th></tr></thead>
<tbody>{"".join(rows)}</tbody></table></div>
<p class="note">Solunar times are a rule of thumb many anglers use, not a guarantee. Moving water around a tide change usually matters as much.</p>"""


WX_CH = {"162.550": 1, "162.400": 2, "162.475": 3, "162.425": 4, "162.450": 5, "162.500": 6, "162.525": 7}
VHF = [("16", "Distress, safety and calling"), ("9", "Boater-to-boater calling"),
       ("22A", "Coast Guard safety broadcasts"), ("13", "Bridge-to-bridge (big ships, drawbridges)"),
       ("68, 69, 71, 72, 78A", "Recreational chat")]


FIPS = {"AL": "01", "AK": "02", "CA": "06", "CT": "09", "DE": "10", "DC": "11", "FL": "12", "GA": "13", "HI": "15",
        "LA": "22", "ME": "23", "MD": "24", "MA": "25", "MS": "28", "NH": "33", "NJ": "34", "NY": "36", "NC": "37",
        "OR": "41", "PA": "42", "RI": "44", "SC": "45", "TX": "48", "VA": "51", "WA": "53", "AS": "60", "GU": "66",
        "MP": "69", "PR": "72", "VI": "78"}


def same_code(county):
    """NWS county zone (CAC075) -> the 6-digit SAME code weather alert radios are programmed with (006075)."""
    if county and re.fullmatch(r"[A-Z]{2}C\d{3}", county[0]) and county[0][:2] in FIPS:
        return "0" + FIPS[county[0][:2]] + county[0][3:], county[1]
    return None


def radio_block(nwr, county=None):
    tx = "".join(f'<li><b>{esc(f)} MHz</b>{f" <span class=wxch>WX{WX_CH[f]}</span>" if f in WX_CH else ""} '
                 f'{esc(call)}, {esc(site)}, {esc(stt)} <i>({d} mi)</i></li>' for call, f, site, stt, d in nwr or [])
    tx_part = (f'<h3>NOAA Weather Radio</h3><ul class="radio-tx">{tx}</ul>'
               ) if nwr else ""
    same = same_code(county)
    if same:
        tx_part += (f'<p class="note">To get alerts on a weather alert radio, program county code <b>{same[0]}</b> '
                    f'({esc(same[1])}).</p>')
    vhf = "".join(f"<li><b>Ch {c}</b> {esc(t)}</li>" for c, t in VHF)
    return (f'<details class="radio" id="radio"><summary>{ico("radio")}Marine radio: weather channels and VHF</summary>{tx_part}<h3>VHF marine channels</h3><ul class="radio-vhf">{vhf}</ul>'
            f'<p class="note">Weather radio broadcasts are continuous; VHF channels are the US standard. '
            f'Local harbors and bridges may use others, so check your chart.</p></details>')


def signup_card(st, name, ctx):
    if not ALERTS_API:
        return ""
    warn = ("Weather warnings for this water (small craft advisories, gales, coastal flooding)"
            if ctx.get("zone") else "Weather warnings here (coastal flooding, high surf, storms)")
    return f"""
<section class="card signup" id="emails">
<h2>{ico("mail")}Get {esc(name)} tides by email</h2>
<form method="post" action="{ALERTS_API}/subscribe">
<input type="hidden" name="station" value="{esc(st["id"])}"><input type="hidden" name="name" value="{esc(name)}">
<input type="text" name="website" tabindex="-1" autocomplete="off" class="hp" aria-hidden="true">
<label class="opt"><input type="checkbox" name="weekly" value="1" checked> Weekly tide times, every Thursday</label>
<label class="opt"><input type="checkbox" name="warn" value="1" checked> {warn}</label>
<label class="opt"><input type="checkbox" name="lows" value="1" checked> A heads-up when the weekend has minus tides</label>
<div class="row"><input type="email" name="email" required placeholder="you@example.com" aria-label="Email address"><button type="submit">Sign me up</button></div>
<p class="note">Free. We'll email you to confirm first, and every email has a one-click unsubscribe. <a href="{BASE}privacy/">Privacy</a></p>
</form>
</section>"""


ALERTS_PAGE = """
<article class="prose alerts-page">
<h1>Tide emails</h1>
<div id="al-msg"><p>Sign up on any station page: look for <b>Get tides by email</b> under the fishing times.
You can choose a weekly tide email, weather warnings for that stretch of water, and a heads-up when the weekend has minus tides.</p></div>
<p><a href="{base}">Find your beach or harbor →</a></p>
</article>
<script>
(() => {{
  const api = {api!r}, box = document.getElementById("al-msg"), q = new URLSearchParams(location.search);
  const say = (h) => (box.innerHTML = "<p>" + h + "</p>");
  const msgs = {{
    check: "<b>Almost done.</b> Check your inbox for an email from hello@tidechartusa.com and click the button to confirm. (Look in spam or promotions if it's not there in a minute.)",
    invalid: "That email address didn't look right. Please go back and try again.",
    nothing: "Pick at least one kind of email, then try again.",
    error: "Something went wrong on our end. Please try again in a few minutes.",
  }};
  const post = (path, t) => fetch(api + path, {{ method: "POST", headers: {{ "content-type": "application/json" }}, body: JSON.stringify({{ t }}) }})
    .then((r) => r.json()).catch(() => ({{ state: "error" }}));
  if (q.get("confirm")) {{
    say("Confirming…");
    post("/confirm", q.get("confirm")).then((r) => say(r.state === "confirmed" ? "<b>You're subscribed.</b> Your first email arrives with the next update. Every email has an unsubscribe link."
      : r.state === "expired" ? "That link has expired. Please sign up again from the station page." : "That link didn't work. Please sign up again from the station page."));
  }} else if (q.get("unsub")) {{
    say("Unsubscribing…");
    post("/unsubscribe", q.get("unsub")).then((r) => say(r.state === "unsubscribed" ? "<b>Done.</b> You won't get those emails any more." : "That link didn't work. Reply to any of our emails and we'll remove you by hand."));
  }} else if (msgs[location.hash.slice(1)]) say(msgs[location.hash.slice(1)]);
  history.replaceState(null, "", location.pathname + location.hash);
}})();
</script>
"""


def live_section(st, name, ctx):
    zone, buoy, nwr = ctx.get("zone"), ctx.get("buoy"), ctx.get("nwr")
    wt, wl = st["id"] in ctx["sensors"].get("wt", ()), st["id"] in ctx["sensors"].get("wl", ())
    attrs = (f'data-st="{esc(st["id"])}" data-wt="{int(wt)}" data-wl="{int(wl)}" '
             f'data-lat="{st["lat"]:.4f}" data-lng="{st["lng"]:.4f}"')
    parts = ['<div class="lv-wx"><div id="lv-wx"><p>Loading the National Weather Service forecast… '
             f'<a href="https://forecast.weather.gov/MapClick.php?lat={st["lat"]:.4f}&amp;lon={st["lng"]:.4f}">'
             'Open it on weather.gov</a>.</p></div></div>']
    if zone:
        zid, zname, office = zone
        attrs += f' data-zone="{esc(zid)}" data-office="{esc(office)}"'
        parts.append(f'<div class="lv-fc"><h3>Marine forecast: {esc(zname)}</h3>'
                     f'<div id="lv-fc"><p>Loading the latest National Weather Service forecast… '
                     f'<a href="https://marine.weather.gov/MapClick.php?zoneid={esc(zid)}">Open it on weather.gov</a>.</p></div></div>')
    obs = []
    if wt:
        obs.append('<li id="lv-wt"><b>Water temperature</b> <span>—</span></li>')
    if wl:
        obs.append('<li id="lv-wl"><b>Water level now</b> <span>—</span></li>')
    if buoy:
        bid, bname, bdist = buoy
        obs.append(f'<li><b>Nearest weather buoy</b> <span><a href="https://www.ndbc.noaa.gov/station_page.php?station={esc(bid.lower())}">'
                   f'{esc(bname or bid)}</a> ({bdist} mi): waves, wind and water temperature</span></li>')
    if obs:
        parts.append(f'<ul class="facts lv-obs">{"".join(obs)}</ul>')
    parts.append(radio_block(nwr, ctx.get("county")))
    return f"""
<section class="card live" id="live" {attrs}>
<h2>{ico("forecast")}Weather and conditions at {esc(name)}</h2>
{"".join(parts)}
<p class="note">Live readings from NOAA and the National Weather Service, loaded when you open this page.</p>
</section>"""


def tab(label, icon, html_, pid=""):
    """A tab panel on station pages (tide.js builds the tab bar from these); empty sections get no tab."""
    if not html_.strip():
        return ""
    return (f'<section class="tab" data-tab="{label}"{f" id={chr(34)}{pid}{chr(34)}" if pid else ""}>'
            f'<template class="tab-ico">{ico(icon)}</template>{html_}</section>')


def jump_nav(items):
    """Sticky row of icon links to each part of a station page."""
    return '<nav class="jump" aria-label="On this page">' + "".join(
        f'<a href="#{target}">{ico(icon)}<span>{label}</span></a>' for label, icon, target in items) + "</nav>"


def station_page(st, ctx):
    tz, events, days = ctx["tz"], ctx["events"], ctx["days"]
    name = st["pretty"]
    state = STATES.get(st["state"], st["state"])
    today = ctx["today"] if ctx["today"] in days else days[0]
    f = describe(st, tz, events, days[days.index(today):days.index(today) + 31])
    sun_by_day = {d: astro.sun(st["lat"], st["lng"], d, tz) for d in days}

    def bounds(d):
        a = dt.datetime.combine(d, dt.time(0), tz).timestamp()
        b = dt.datetime.combine(d + dt.timedelta(days=1), dt.time(0), tz).timestamp()
        return a, b

    t0, t1 = bounds(today)
    rise, sset = sun_by_day.get(today, (None, None))
    chart = svg_chart(events, t0, t1, tz, rise, sset)
    today_rows = "".join(
        f'<li class="{k}"><b>{"High" if k == "H" else "Low"}</b> {clock(dt.datetime.fromtimestamp(t, tz))}'
        f' <span>{ft(v)}</span></li>' for t, v, k in f["by_day"].get(today, []))

    def tide_cells(d):
        return "".join(
            f'<span class="ev {k}"><b>{"H" if k == "H" else "L"}</b> {clock(dt.datetime.fromtimestamp(t, tz))}'
            f' <i>{ft(v)}</i></span>' for t, v, k in f["by_day"].get(d, []))

    def sun_cell(d):
        r, s = sun_by_day.get(d, (None, None))
        return f"{clock(r)} / {clock(s)}" if r else "—"

    def moon_cell(d):
        ph, lit = astro.moon(dt.datetime.combine(d, dt.time(12), tz))
        return f"{ph} ({lit}%)"

    start = days.index(today)
    week = days[start:start + 7]
    week_rows = "".join(
        f'<tr data-day="{d.isoformat()}"><th scope="row">{day_label(d, True)}</th><td class="evs">{tide_cells(d)}</td>'
        f'<td>{sun_cell(d)}</td><td>{moon_cell(d)}</td></tr>' for d in week)
    month = days[start:start + 31]
    month_rows = "".join(
        f'<tr data-day="{d.isoformat()}"><th scope="row">{day_label(d, True)}</th><td class="evs">{tide_cells(d)}</td>'
        f'<td>{sun_cell(d)}</td></tr>' for d in month)
    m_title = f"{month[0].strftime('%B %-d')} to {month[-1].strftime('%B %-d, %Y')}"

    dl = daylight_lows(f, days[start:], tz, sun_by_day)
    dl_html = ""
    if dl:
        dl_html = ("<h2 id=\"lows\">Best daylight low tides in the next two weeks</h2><p>The lowest water that falls between "
                   "sunrise and sunset, for tide pooling and beachcombing.</p><ol class='dl'>"
                   + "".join(f"<li><b>{ft(v)}</b> at {clock(dt.datetime.fromtimestamp(t, tz))} on "
                             f"{day_label(dt.datetime.fromtimestamp(t, tz).date())}</li>" for v, t in dl) + "</ol>")

    near = "".join(f'<li><a href="{BASE}{n["path"]}">{esc(n["pretty"])}</a> <span>{d:.0f} mi</span></li>'
                   for d, n in ctx["near"])
    ref = ""
    if st["type"] == "S" and ctx.get("ref"):
        r = ctx["ref"]
        ref = f'<p>Reference station: <a href="{BASE}{r["path"]}">{esc(r["pretty"])}</a>.</p>'

    def sun_epochs(d):
        r, s = sun_by_day.get(d, (None, None))
        return [int(r.timestamp()), int(s.timestamp())] if r else [0, 0]

    data = {"ev": [[int(t), v, k] for t, v, k in events], "name": f"{name}, {st['state']}", "id": st["id"],
            "days": {d.isoformat(): [*map(int, bounds(d)), *sun_epochs(d), day_label(d)] for d in month}}
    # Trip planner: fishing score and major periods for two weeks, and the nearest current predictions.
    fish = {}
    for d in days[start:start + 14]:
        sc, majors, _ = fish_day(st, d, tz, f, sun_by_day)
        fish[d.isoformat()] = [sc, [int(m.timestamp()) for m in majors]]
    data["fish"] = fish
    if ctx.get("cur"):
        meta, cdist, cev = ctx["cur"]
        data["cur"] = {"name": tidy(meta["name"]), "mi": cdist, "ev": [
            [int(dt.datetime.strptime(t, "%Y-%m-%d %H:%M").replace(tzinfo=tz).timestamp()), v, k] for t, v, k in cev]}
    title = f"{name}, {st['state']} Tide Chart & Tide Times"
    desc = (f"Today's high and low tide times for {name}, {state}, with a tide chart, a 7-day tide table, "
            f"sunrise and sunset, and the month ahead. From NOAA station {st['id']}.")
    gmap = f"https://www.google.com/maps?q={st['lat']},{st['lng']}"
    week_html = f"""<h2 id="week">Tide times this week</h2>
<div class="scroll"><table class="tides week"><thead><tr><th>Day</th><th>High and low tides</th><th>Sunrise / sunset</th><th>Moon</th></tr></thead>
<tbody>{week_rows}</tbody></table></div>"""
    month_html = f"""<h2 id="month">Tide table: {m_title}</h2>
<p class="tools"><button type="button" data-print>Print this tide table</button> <button type="button" data-ics>Add tides to my calendar (.ics)</button></p>
<div class="scroll"><table class="tides month"><thead><tr><th>Day</th><th>High and low tides</th><th>Sunrise / sunset</th></tr></thead>
<tbody>{month_rows}</tbody></table></div>
<p class="note">Heights are in feet above mean lower low water (MLLW), the zero line on most US nautical charts. A minus height means the water drops below that line.</p>"""
    cur_html = currents_section(name, ctx.get("cur"), week, tz)
    fish_html = fishing_section(st, name, week, tz, f, sun_by_day)
    jumps = [("Today", "chart", "today"), ("Plan a trip", "plan", "plan"), ("Weather", "forecast", "live"), ("Week", "week", "week")]
    jumps += [("Currents", "current", "currents")] if cur_html else []
    jumps += [("Fishing", "fish", "fishing")]
    jumps += [("Low tides", "low", "lows")] if dl_html else []
    jumps += [("Month", "cal", "month"), ("Radio", "radio", "radio")]
    jumps += [("Email me", "mail", "emails")] if ALERTS_API else []
    body = f"""
<article class="station">
<h1>{esc(name)} tide chart</h1>
<p class="sub">{esc(state)} · NOAA station {esc(st['id'])} · times in local time ({esc(dt.datetime.combine(today, dt.time(12), tz).strftime('%Z'))})</p>
{jump_nav(jumps)}
<section class="alerts-banner" id="alerts" aria-live="polite" hidden><template class="i-warn">{ico("warn")}</template><template class="i-check">{ico("check")}</template></section>
<div class="pagetools"><div class="acts-row" id="acts-row" hidden><button type="button" data-save>{ico("star")}<span>Save offline</span></button><button type="button" data-pocket>{ico("print")}<span>Print pocket card</span></button><button type="button" data-install hidden>{ico("phone")}<span>Install app</span></button></div>
<div class="units" id="units" hidden><span>Units</span><button type="button" data-u="ft">ft</button><button type="button" data-u="m">m</button><span class="sep"></span><button type="button" data-u="12">12h</button><button type="button" data-u="24">24h</button></div></div>

<section class="today card" id="today">
<div class="today-head"><h2>{ico("chart")}<span id="today-title">Tides today, {day_label(today)}</span></h2><p class="now" id="now" hidden></p></div>
<div class="daypick" id="daypick" hidden></div>
<div id="chart">{chart}</div>
<ul class="tlist" id="tlist">{today_rows}</ul>
<div class="dayextra" id="dayextra"></div>
<p class="sunline" id="sunline">Sunrise {clock(rise) if rise else '—'} · Sunset {clock(sset) if sset else '—'} · {moon_cell(today)}</p>
</section>

<section class="card plan" id="plan" hidden>
<h2>{ico("plan")}Plan a trip</h2>
<p class="sub">Pick what you want to do and we'll rank the next two weeks for it.</p>
<div class="acts" role="radiogroup" aria-label="Activity">
<button type="button" data-act="pool" aria-pressed="true">{ico("pool")}Tide pooling</button>
<button type="button" data-act="fish" aria-pressed="false">{ico("fish")}Fishing</button>
<button type="button" data-act="kayak" aria-pressed="false">{ico("kayak")}Kayak / paddle</button>
<button type="button" data-act="walk" aria-pressed="false">{ico("walk")}Beach walk</button>
</div>
<ol class="plan-list" id="plan-list"></ol>
<p class="note" id="plan-note"></p>
</section>

{live_section(st, name, ctx)}

<div class="tabs" data-tabs>
{tab("This week", "week", week_html)}
{tab("Currents", "current", cur_html)}
{tab("Fishing", "fish", fish_html)}
{tab("Low tides", "low", dl_html)}
{tab("Month", "cal", month_html, "month-tab")}
</div>

{signup_card(st, name, ctx)}

<h2>About the tides at {esc(name)}</h2>
{writeup(st, name, f, tz)}

<h2>Station details</h2>
<ul class="facts">
<li>NOAA station ID: <a href="https://tidesandcurrents.noaa.gov/noaatidepredictions.html?id={esc(st['id'])}">{esc(st['id'])}</a></li>
<li>Type: {"subordinate (adjusted from a reference station)" if st['type'] == 'S' else "reference (harmonic)"}</li>
<li>Location: <a href="{gmap}">{st['lat']:.4f}, {st['lng']:.4f}</a></li>
</ul>
{ref}
{"<h2>Nearby tide stations</h2><ul class='near'>" + near + "</ul>" if near else ""}
</article>
<script type="application/json" id="tide-data">{json.dumps(data, separators=(",", ":"))}</script>
"""
    crumbs = [("Home", ""), (state, f"tides/{slugify(state)}/"), (name, st["path"])]
    return page(title, desc, st["path"], body, crumbs=crumbs, scripts=("units.js", "tide.js", "live.js", "planner.js"))


# ---------- other pages ----------

def state_page(code, stations):
    state = STATES.get(code, code)
    refs = sum(1 for s in stations if s["type"] == "R")
    items = "".join(f'<li data-n="{esc(s["pretty"].lower())}"><a href="{BASE}{s["path"]}">{esc(s["pretty"])}</a>'
                    f'{" <span class=tag>reference</span>" if s["type"] == "R" else ""}</li>'
                    for s in sorted(stations, key=lambda s: s["pretty"].lower()))
    body = f"""
<h1>{esc(state)} tide charts</h1>
<p class="lede">Tide times and charts for {len(stations)} NOAA tide stations in {esc(state)}. {refs} are reference
stations with their own long-term measurements; the rest are calculated from the nearest reference station.</p>
<label class="filter"><span>Filter</span><input type="search" placeholder="Type a town, bay or inlet" data-filter></label>
<ul class="stations">{items}</ul>
"""
    path = f"tides/{slugify(state)}/"
    return path, page(f"{state} Tide Charts & Tide Times ({len(stations)} stations)",
                      f"High and low tide times, tide charts and tide tables for {len(stations)} places in {state}, from NOAA.",
                      path, body, crumbs=[("Home", ""), (state, path)], scripts=("site.js",))


def states_index(groups):
    items = "".join(f'<li><a href="{BASE}tides/{slugify(STATES.get(c, c))}/">{esc(STATES.get(c, c))} <span>{len(g)}</span></a></li>'
                    for c, g in sorted(groups.items(), key=lambda kv: STATES.get(kv[0], kv[0])))
    return items


POPULAR = ["9414290", "8518750", "9447130", "8723214", "8661070", "1612340"]
REGIONS = [("Northeast", "ME NH MA RI CT NY NJ PA DE MD DC VA"), ("Southeast & Gulf", "NC SC GA FL AL MS LA TX"),
           ("West Coast", "CA OR WA"), ("Alaska & Hawaii", "AK HI"), ("Islands", "PR VI GU AS MP FM UM")]
ICON = {
    "chart": '<path d="M3 17c3 0 3-6 6-6s3 6 6 6 3-6 6-6"/><path d="M3 21h18"/>',
    "current": '<path d="M3 8h13l-3-3M3 8l0 0"/><path d="M21 16H8l3 3"/>',
    "fish": '<path d="M3 12c3-4 7-5 11-3l5-3v12l-5-3c-4 2-8 1-11-3z"/><circle cx="8" cy="11" r="1"/>',
    "forecast": '<path d="M7 18h10a4 4 0 0 0 0-8 6 6 0 0 0-11.5 1.5A3.5 3.5 0 0 0 7 18z"/>',
    "temp": '<path d="M10 14V5a2 2 0 0 1 4 0v9a4 4 0 1 1-4 0z"/><path d="M12 14v3"/>',
    "cal": '<rect x="3" y="5" width="18" height="16" rx="2"/><path d="M3 10h18M8 3v4M16 3v4"/>',
    "week": '<path d="M4 6h16M4 12h16M4 18h10"/>',
    "low": '<path d="M12 3v10m-4-4 4 4 4-4"/><path d="M3 19c2 0 2-2 4.5-2s2.5 2 4.5 2 2-2 4.5-2 2.5 2 4.5 2"/>',
    "radio": '<rect x="3" y="9" width="18" height="12" rx="2"/><path d="M7 9l10-5"/><circle cx="15" cy="15" r="2.5"/><path d="M6 13h4M6 17h4"/>',
    "plan": '<circle cx="12" cy="12" r="9"/><path d="m15.5 8.5-2 5-5 2 2-5z"/>',
    "pool": '<path d="M3 15c2 0 2-2 4.5-2s2.5 2 4.5 2 2-2 4.5-2 2.5 2 4.5 2"/><path d="M8 9a2 2 0 1 0 0-.01M15 7l1.5 3h-3z"/>',
    "kayak": '<path d="M2 15c4 2 16 2 20 0"/><path d="M5 20 19 6"/><path d="M17 4l3 3M4 17l3 3"/>',
    "walk": '<circle cx="13" cy="4" r="2"/><path d="m9 21 2-6 3 3v3M8 11l3-4 3 2 3 1M11 7l-1 5"/>',
    "star": '<path d="m12 3 2.7 5.6 6.1.9-4.4 4.3 1 6.1L12 17l-5.4 2.9 1-6.1-4.4-4.3 6.1-.9z"/>',
    "print": '<path d="M7 9V3h10v6"/><rect x="3" y="9" width="18" height="8" rx="2"/><path d="M7 14h10v7H7z"/>',
    "phone": '<rect x="6" y="2" width="12" height="20" rx="2.5"/><path d="M11 18h2"/>',
    "warn": '<path d="M12 3 2 20h20z"/><path d="M12 10v4M12 17h.01"/>',
    "check": '<circle cx="12" cy="12" r="9"/><path d="m8 12 3 3 5-6"/>',
    "mail": '<rect x="3" y="5" width="18" height="14" rx="2"/><path d="m3 7 9 6 9-6"/>',
}


def ico(name, cls="ico"):
    return f'<svg class="{cls}" viewBox="0 0 24 24" aria-hidden="true">{ICON[name]}</svg>'
FEATURES = [("chart", "Today's tide chart", "A live curve with a now marker, the next high or low, and whether the water is rising or falling."),
            ("current", "Tidal currents", "Slack water and peak flood and ebb in knots, from the nearest NOAA current station."),
            ("fish", "Best fishing times", "Daily major and minor solunar periods with a simple rating for each day."),
            ("forecast", "Marine forecast", "The National Weather Service forecast and any small craft advisories for that stretch of water."),
            ("temp", "Live water conditions", "Water temperature and the measured water level against the prediction, where NOAA has sensors."),
            ("cal", "Print or add to calendar", "A month tide table you can print, or every high and low in your phone's calendar.")]


def spark(events, t0, t1, w=260, h=64):
    pts = curve_points(events, t0, t1, step=900)
    if not pts:
        return ""
    vs = [v for _, v in pts]
    lo, hi = min(vs), max(vs)
    span = (hi - lo) or 1
    xy = [((t - t0) / (t1 - t0) * w, h - 6 - (v - lo) / span * (h - 12)) for t, v in pts]
    line = "M" + " L".join(f"{x:.1f},{y:.1f}" for x, y in xy)
    return (f'<svg class="spark" viewBox="0 0 {w} {h}" preserveAspectRatio="none" aria-hidden="true">'
            f'<path class="fill" d="{line} L{w},{h} L0,{h} Z"/><path class="line" d="{line}"/></svg>')


def home(groups, total, popular):
    cards = []
    for st, tz, events, today in popular:
        a = dt.datetime.combine(today, dt.time(0), tz).timestamp()
        evs = [(dt.datetime.fromtimestamp(t, tz), v, k) for t, v, k in events if a <= t < a + 86400]
        times = "".join(f'<li class="{k}"><b title="{"High" if k == "H" else "Low"}">{"▲" if k == "H" else "▼"}</b> {clock(w)} <i>{ft(v)}</i></li>'
                        for w, v, k in evs)
        cards.append(f'<a class="spot" href="{BASE}{st["path"]}"><span class="spot-name">{esc(st["pretty"])}'
                     f'<small>{esc(STATES.get(st["state"], st["state"]))}</small></span>{spark(events, a, a + 86400)}'
                     f'<ul>{times}</ul></a>')
    feats = "".join(f'<div class="feat"><svg viewBox="0 0 24 24" aria-hidden="true">{ICON[i]}</svg>'
                    f'<h3>{t}</h3><p>{d}</p></div>' for i, t, d in FEATURES)
    regions = []
    for label, codes in REGIONS:
        items = [(STATES.get(c, c), c) for c in codes.split() if c in groups]
        if items:
            regions.append(f'<div class="region"><h3>{label}</h3><ul>' + "".join(
                f'<li><a href="{BASE}tides/{slugify(n)}/">{esc(n)} <span>{len(groups[c])}</span></a></li>'
                for n, c in items) + "</ul></div>")
    day = popular[0][3] if popular else None
    body = f"""
<section class="hero-sea">
<svg class="waves" viewBox="0 0 1200 120" preserveAspectRatio="none" aria-hidden="true">
<path class="w1" d="M0 60 C150 20 300 100 450 60 S750 20 900 60 1050 100 1200 60 1350 20 1500 60 V120 H0Z"/>
<path class="w2" d="M0 80 C150 50 300 110 450 80 S750 50 900 80 1050 110 1200 80 1350 50 1500 80 V120 H0Z"/>
</svg>
<div class="hero-in">
<h1>Tide times for every beach, bay and harbor in the US</h1>
<p>{total:,} NOAA stations with today's tide chart, currents, fishing times and the marine forecast. Updated every night.</p>
<div class="search big"><input type="search" placeholder="Search a beach, harbor or town" aria-label="Search tide stations" data-search autocomplete="off"><div class="results" data-results hidden></div></div>
<button type="button" class="locate" data-locate><svg viewBox="0 0 24 24" aria-hidden="true"><circle cx="12" cy="12" r="3"/><path d="M12 2v3M12 19v3M2 12h3M19 12h3"/><circle cx="12" cy="12" r="8"/></svg>Find tides near me</button>
<p class="locate-msg" data-locate-msg hidden></p>
</div>
</section>

<section class="saved" id="saved" hidden><h2 class="sec">{ico("star")}Your saved spots <span>· work offline</span></h2><div class="saved-list" id="saved-list"></div></section>

<h2 class="sec">Popular spots{f' <span>· {day_label(day)}</span>' if day else ''}</h2>
<div class="spots">{"".join(cards)}</div>

<h2 class="sec">On every station page</h2>
<div class="feats">{feats}</div>

<h2 class="sec">Browse by state</h2>
<div class="regions">{"".join(regions)}</div>

<a class="guide-cta" href="{BASE}how-to-read-a-tide-chart/"><b>New to tide charts?</b> Learn what MLLW, minus tides and spring tides mean in two minutes →</a>
"""
    return page("Tide Charts & Tide Times for Every US Beach and Harbor",
                f"Free tide charts, high and low tide times, currents, fishing times and marine forecasts for {total:,} NOAA stations across the US.",
                "", body, scripts=("units.js", "site.js"))


GUIDE = """
<article class="prose">
<h1>How to read a tide chart</h1>
<p class="lede">A tide chart shows how high the water will be at a spot through the day. Here is what each part means and how to use it.</p>

<h2>The curve</h2>
<p>The wavy line is the predicted water height. Peaks are <strong>high tides</strong> and dips are <strong>low tides</strong>.
The time between a high and the next low is usually a little over six hours, so on most of the US coast you get two of each a day.
The steepest part of the curve, halfway between a high and a low, is when the water rises or falls fastest.</p>

<h2>The numbers</h2>
<p>Heights are measured in feet from a zero line called <strong>mean lower low water (MLLW)</strong>: the average of the lowest
tide of each day over many years. It's the same zero used on most US nautical charts, so a charted depth plus the tide height
is roughly the water you'll have. A <strong>minus tide</strong> (for example -1.2 ft) means the water drops below that average
low, uncovering more beach, rocks and flats than usual.</p>

<h2>Why the two highs differ</h2>
<p>On the Pacific coast, in Alaska and in Hawaii, one high tide each day is usually much higher than the other. That's a
<strong>mixed tide</strong>. Most of the Atlantic coast has two highs of similar height (<strong>semidiurnal</strong>), and parts
of the Gulf of Mexico get just one high and one low a day (<strong>diurnal</strong>). Each station page here says which kind it has.</p>

<h2>Spring and neap tides</h2>
<p>Around the new and full moon the sun and moon pull in line, so highs are higher and lows are lower. Those are
<strong>spring tides</strong> (nothing to do with the season). Around the quarter moons the range shrinks: <strong>neap tides</strong>.
Station pages list the days with the biggest swings in the month ahead.</p>

<h2>Predictions vs. what you'll see</h2>
<p>These are NOAA's astronomical predictions. Strong onshore wind, low air pressure or heavy river flow can raise the water
above the prediction, and offshore wind can drop it. For boating, check current conditions and official notices too.
<strong>This site is not for navigation.</strong></p>

<h2>Subordinate and reference stations</h2>
<p>NOAA measures water levels for years at <strong>reference stations</strong> and predicts their tides directly. Thousands of
other spots are <strong>subordinate stations</strong>: their times and heights are worked out by adjusting the nearest reference
station. They're good for planning but can be off by a few minutes or a few tenths of a foot.</p>
</article>
"""

ABOUT = """
<article class="prose">
<h1>About Tide Chart USA</h1>
<p>Tide Chart USA turns NOAA's tide predictions into fast, readable pages for every US tide station: a chart for today,
the week ahead, a month table, sunrise and sunset, and the best daylight low tides.</p>
<p>The predictions come from the <a href="https://tidesandcurrents.noaa.gov/">NOAA Center for Operational Oceanographic Products and Services (CO-OPS)</a>.
We download them every night, so each page always shows the next month. Sunrise, sunset and moon phase are calculated from each station's position.</p>
<p>We are not affiliated with NOAA. Predictions are not observations, and this site is not for navigation.</p>
</article>
"""

PRIVACY = """
<article class="prose">
<h1>Privacy</h1>
<p>This site has no accounts. The only personal information we collect is your email address, if you sign up for tide emails.</p>
<h2>Tide emails</h2>
<p>When you sign up we store your email address, the station you picked and which emails you want. We use them only to send those emails.
The list is kept in our Cloudflare database and the emails are sent through Resend. We never sell or share it.
Every email has a one-click unsubscribe link, which deletes your subscription. You can also email hello@tidechartusa.com to be removed.</p>
<p>If we add advertising or analytics, those partners may use cookies to measure visits and show ads, and this page will be updated to name them and explain your choices.</p>
</article>
"""


OFFLINE = """
<article class="prose">
<h1>You're offline</h1>
<p>This page isn't saved on your device. Spots you've saved, or opened recently, still work without a connection:</p>
<div class="saved-list" id="saved-list"></div>
<p class="note">Saved pages hold a month of tide predictions. Live weather, warnings and water levels need a connection.</p>
</article>
"""

# Service worker: pages come from the network when possible (so they stay fresh) and fall back to the copy
# on the device; the files a page needs are cached on first use. "Save offline" keeps a page in its own cache.
SW = """const VER = "__VER__", BASE = "__BASE__";
const STATIC = "tc-static-" + VER, PAGES = "tc-pages", SAVED = "tc-saved", MAX_PAGES = 40;
self.addEventListener("install", (e) => {
  e.waitUntil(caches.open(STATIC).then((c) => c.addAll([BASE, BASE + "offline/", BASE + "static/icon-192.png"])).then(() => self.skipWaiting()));
});
self.addEventListener("activate", (e) => {
  e.waitUntil(caches.keys().then((ks) => Promise.all(ks.filter((k) => k.startsWith("tc-static-") && k !== STATIC).map((k) => caches.delete(k))))
    .then(() => self.clients.claim()));
});
const trim = async () => {
  const c = await caches.open(PAGES), keys = await c.keys();
  for (const k of keys.slice(0, Math.max(0, keys.length - MAX_PAGES))) await c.delete(k);
};
self.addEventListener("fetch", (e) => {
  const req = e.request, url = new URL(req.url);
  if (req.method !== "GET" || url.origin !== location.origin || !url.pathname.startsWith(BASE)) return;
  if (req.mode === "navigate") {
    e.respondWith(fetch(req).then((res) => {
      if (res.ok) {
        const copy = res.clone(), copy2 = res.clone();
        caches.open(PAGES).then((c) => c.put(url.pathname, copy)).then(trim);
        // Saved pages get the fresh copy too, so a saved spot always has the latest month of tides.
        caches.open(SAVED).then(async (c) => { if (await c.match(url.pathname)) c.put(url.pathname, copy2); });
      }
      return res;
    }).catch(async () => (await caches.match(url.pathname, { ignoreSearch: true })) || caches.match(BASE + "offline/")));
    return;
  }
  // Scripts, styles, icons and the search index: cached copy first, refreshed in the background.
  e.respondWith(caches.match(req).then((hit) => {
    const net = fetch(req).then((res) => {
      if (res.ok) { const copy = res.clone(); caches.open(STATIC).then((c) => c.put(req, copy)); }
      return res;
    });
    return hit || net;
  }));
});
"""


def search_index(stations):
    return {"base": BASE, "s": [[s["pretty"], s["state"], s["path"], round(s["lat"], 3), round(s["lng"], 3)]
                                for s in stations]}


def assign_paths(stations):
    """Adds "pretty" (display name) and "path" (URL path) to each station. Also used by alerts/send.py."""
    seen = set()
    for s in stations:
        s["pretty"] = tidy(s["name"])
        state = STATES.get(s["state"], s["state"])
        slug = slugify(s["pretty"]) or s["id"]
        path = f"tides/{slugify(state)}/{slug}/"
        if path in seen:
            path = f"tides/{slugify(state)}/{slug}-{s['id']}/"
        seen.add(path)
        s["path"] = path


def main():
    meta = json.loads((DATA / "stations.json").read_text())
    stations = meta["stations"]
    if OUT.exists():
        shutil.rmtree(OUT)
    OUT.mkdir()
    shutil.copytree(STATIC, OUT / "static")

    built_at = dt.datetime.fromisoformat(meta["fetched"])
    assign_paths(stations)
    by_id = {s["id"]: s for s in stations}

    # Nearby stations: bucket by 1-degree cells so this stays fast for ~3,000 stations.
    cells = {}
    for s in stations:
        cells.setdefault((int(s["lat"]), int(s["lng"])), []).append(s)

    def load(path, default):
        try:
            return json.loads(path.read_text())
        except (FileNotFoundError, ValueError):
            return default

    cur = load(DATA / "currents.json", {"stations": {}, "links": {}})
    sensors = load(DATA / "sensors.json", {})
    buoys = load(DATA / "buoys.json", {})
    zones = load(ROOT / "collector" / "marine_zones.json", {})
    radios = load(DATA / "nwr.json", {})
    counties = load(ROOT / "collector" / "county_zones.json", {})

    def cur_for(sid):
        link = cur["links"].get(sid)
        if not link:
            return None
        events = load(DATA / "currents" / f"{link[0]}.json", None)
        return (cur["stations"][link[0]], link[1], events) if events else None

    groups = {}
    popular = {}
    built = 0
    for s in stations:
        try:
            tz, events, days = load_station(s)
        except FileNotFoundError:
            continue
        if len(days) < 8:
            continue
        cand = [o for dy in (-1, 0, 1) for dx in (-1, 0, 1)
                for o in cells.get((int(s["lat"]) + dy, int(s["lng"]) + dx), []) if o is not s]
        near = sorted(((miles(s, o), o) for o in cand), key=lambda p: p[0])
        near = [(d, o) for d, o in near if d <= 40][:6]
        today = built_at.astimezone(tz).date()
        ctx = {"tz": tz, "events": events, "days": days, "near": near, "today": today,
               "ref": by_id.get(s["ref"]), "cur": cur_for(s["id"]), "sensors": sensors,
               "buoy": buoys.get(s["id"]), "zone": zones.get(s["id"]) or None,
               "nwr": radios.get(s["id"]), "county": counties.get(s["id"]) or None}
        write(s["path"] + "index.html", station_page(s, ctx))
        if s["id"] in POPULAR:
            popular[s["id"]] = (s, tz, events, today)
        groups.setdefault(s["state"], []).append(s)
        built += 1

    for code, g in groups.items():
        path, html_ = state_page(code, g)
        write(path + "index.html", html_)
    live = [s for g in groups.values() for s in g]
    write("manifest.webmanifest", json.dumps({
        "name": SITE_NAME, "short_name": "Tides", "start_url": BASE, "scope": BASE, "display": "standalone",
        "background_color": "#f4f8fa", "theme_color": "#0b5c7a",
        "description": "Tide charts, currents, fishing times and marine weather for US beaches and harbors.",
        "icons": [{"src": f"{BASE}static/icon-{n}.png", "sizes": f"{n}x{n}", "type": "image/png", "purpose": "any maskable"}
                  for n in (192, 512)]}, indent=1))
    write("sw.js", SW.replace("__BASE__", BASE).replace("__VER__", CSS_VER + "-" + built_at.strftime("%Y%m%d")))
    write("offline/index.html", page("Offline", "You're offline.", "offline/", OFFLINE, scripts=("units.js",)))
    write("index.html", home(groups, len(live), [popular[i] for i in POPULAR if i in popular]))
    write("states/index.html", page("Tide Charts by State", "Pick a state to see every NOAA tide station there.",
                                    "states/", f"<h1>Tide charts by state</h1><ul class='states'>{states_index(groups)}</ul>",
                                    crumbs=[("Home", ""), ("States", "states/")]))
    write("how-to-read-a-tide-chart/index.html", page(
        "How to Read a Tide Chart: Highs, Lows, MLLW and Minus Tides",
        "What the curve and numbers on a tide chart mean, why the two daily highs differ, and spring vs. neap tides.",
        "how-to-read-a-tide-chart/", GUIDE, crumbs=[("Home", ""), ("How to read a tide chart", "how-to-read-a-tide-chart/")]))
    write("about/index.html", page("About Tide Chart USA", "Where our tide predictions come from.", "about/", ABOUT))
    if ALERTS_API:
        write("alerts/index.html", page("Tide emails", "Weekly tide times and weather warnings by email.", "alerts/",
                                        ALERTS_PAGE.format(base=BASE, api=ALERTS_API)))
    write("privacy/index.html", page("Privacy", "Privacy at Tide Chart USA.", "privacy/", PRIVACY))
    write("404.html", page("Page not found", "Page not found.", "404.html",
                           f"<h1>Page not found</h1><p><a href='{BASE}'>Search for a tide station</a>.</p>"))
    write("static/search.json", json.dumps(search_index(live), separators=(",", ":")))
    if LAUNCHED:
        urls = [""] + ["states/", "how-to-read-a-tide-chart/", "about/"] + \
               [f"tides/{slugify(STATES.get(c, c))}/" for c in groups] + [s["path"] for s in live]
        write("sitemap.xml", '<?xml version="1.0" encoding="UTF-8"?>\n<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">'
              + "".join(f"<url><loc>{SITE_URL}/{u}</loc></url>" for u in urls) + "</urlset>")
        write("robots.txt", f"User-agent: *\nAllow: /\nSitemap: {SITE_URL}/sitemap.xml\n")
    else:
        write("robots.txt", "User-agent: *\nAllow: /\n")
    write(".nojekyll", "")
    host = urlparse(SITE_URL).hostname or ""
    if not host.endswith("github.io"):
        write("CNAME", host + "\n")
    print(f"built {built} station pages, {len(groups)} states" + ("" if LAUNCHED else " (noindex)"))


if __name__ == "__main__":
    main()
