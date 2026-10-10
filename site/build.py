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

CSS_VER = "3"


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
<p>Tide predictions from <a href="https://tidesandcurrents.noaa.gov/">NOAA CO-OPS</a>, refreshed every night. Predictions are not observations: wind, pressure and river flow can move the real water level. <strong>Not for navigation.</strong></p>
<p><a href="{BASE}about/">About</a> · <a href="{BASE}privacy/">Privacy</a> · <a href="{BASE}how-to-read-a-tide-chart/">How to read a tide chart</a> · Not affiliated with NOAA.</p>
</div></footer>
{js}
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
        dl_html = ("<h2>Best daylight low tides in the next two weeks</h2><p>The lowest water that falls between "
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

    data = {"ev": [[int(t), v, k] for t, v, k in events],
            "days": {d.isoformat(): [*map(int, bounds(d)), *sun_epochs(d), day_label(d)] for d in month}}
    title = f"{name}, {st['state']} Tide Chart & Tide Times"
    desc = (f"Today's high and low tide times for {name}, {state}, with a tide chart, a 7-day tide table, "
            f"sunrise and sunset, and the month ahead. From NOAA station {st['id']}.")
    gmap = f"https://www.google.com/maps?q={st['lat']},{st['lng']}"
    body = f"""
<article class="station">
<h1>{esc(name)} tide chart</h1>
<p class="sub">{esc(state)} · NOAA station {esc(st['id'])} · times in local time ({esc(dt.datetime.combine(today, dt.time(12), tz).strftime('%Z'))})</p>

<section class="today card" id="today">
<div class="today-head"><h2 id="today-title">Tides today, {day_label(today)}</h2><p class="now" id="now" hidden></p></div>
<div id="chart">{chart}</div>
<ul class="tlist" id="tlist">{today_rows}</ul>
<p class="sunline">Sunrise {clock(rise) if rise else '—'} · Sunset {clock(sset) if sset else '—'} · {moon_cell(today)}</p>
</section>

<h2>Tide times this week</h2>
<div class="scroll"><table class="tides week"><thead><tr><th>Day</th><th>High and low tides</th><th>Sunrise / sunset</th><th>Moon</th></tr></thead>
<tbody>{week_rows}</tbody></table></div>

<h2>About the tides at {esc(name)}</h2>
{writeup(st, name, f, tz)}

{dl_html}

<h2>Tide table: {m_title}</h2>
<div class="scroll"><table class="tides month"><thead><tr><th>Day</th><th>High and low tides</th><th>Sunrise / sunset</th></tr></thead>
<tbody>{month_rows}</tbody></table></div>
<p class="note">Heights are in feet above mean lower low water (MLLW), the zero line on most US nautical charts. A minus height means the water drops below that line.</p>

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
    return page(title, desc, st["path"], body, crumbs=crumbs, scripts=("tide.js",))


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


def home(groups, total):
    body = f"""
<section class="hero">
<h1>Tide charts and tide times for the whole US coast</h1>
<p class="lede">High and low tides for {total:,} NOAA stations, with a chart for today, the week ahead and a full month table. Updated every night.</p>
<div class="search"><input type="search" placeholder="Search a beach, harbor or town" aria-label="Search tide stations" data-search autocomplete="off"><div class="results" data-results hidden></div></div>
</section>
<h2>Browse by state</h2>
<ul class="states">{states_index(groups)}</ul>
<section class="explain">
<h2>What you get for each place</h2>
<ul>
<li><strong>Today's tide chart</strong>, with the next high or low and whether the water is rising or falling right now.</li>
<li><strong>A week of tide times</strong> next to sunrise, sunset and the moon phase.</li>
<li><strong>A month tide table</strong> you can print or screenshot.</li>
<li><strong>The best daylight low tides</strong> for tide pooling and beachcombing.</li>
</ul>
<p>New to tide charts? Read <a href="{BASE}how-to-read-a-tide-chart/">how to read a tide chart</a>.</p>
</section>
"""
    return page("Tide Charts & Tide Times for Every US Beach and Harbor",
                f"Free tide charts, high and low tide times and monthly tide tables for {total:,} NOAA stations across the US.",
                "", body, scripts=("site.js",))


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
<p>This site has no accounts and no forms. We don't collect personal information directly.</p>
<p>If we add advertising or analytics, those partners may use cookies to measure visits and show ads, and this page will be updated to name them and explain your choices.</p>
</article>
"""


def search_index(stations):
    return {"base": BASE, "s": [[s["pretty"], s["state"], s["path"]] for s in stations]}


def main():
    meta = json.loads((DATA / "stations.json").read_text())
    stations = meta["stations"]
    if OUT.exists():
        shutil.rmtree(OUT)
    OUT.mkdir()
    shutil.copytree(STATIC, OUT / "static")

    built_at = dt.datetime.fromisoformat(meta["fetched"])
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
    by_id = {s["id"]: s for s in stations}

    # Nearby stations: bucket by 1-degree cells so this stays fast for ~3,000 stations.
    cells = {}
    for s in stations:
        cells.setdefault((int(s["lat"]), int(s["lng"])), []).append(s)

    groups = {}
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
               "ref": by_id.get(s["ref"])}
        write(s["path"] + "index.html", station_page(s, ctx))
        groups.setdefault(s["state"], []).append(s)
        built += 1

    for code, g in groups.items():
        path, html_ = state_page(code, g)
        write(path + "index.html", html_)
    live = [s for g in groups.values() for s in g]
    write("index.html", home(groups, len(live)))
    write("states/index.html", page("Tide Charts by State", "Pick a state to see every NOAA tide station there.",
                                    "states/", f"<h1>Tide charts by state</h1><ul class='states'>{states_index(groups)}</ul>",
                                    crumbs=[("Home", ""), ("States", "states/")]))
    write("how-to-read-a-tide-chart/index.html", page(
        "How to Read a Tide Chart: Highs, Lows, MLLW and Minus Tides",
        "What the curve and numbers on a tide chart mean, why the two daily highs differ, and spring vs. neap tides.",
        "how-to-read-a-tide-chart/", GUIDE, crumbs=[("Home", ""), ("How to read a tide chart", "how-to-read-a-tide-chart/")]))
    write("about/index.html", page("About Tide Chart USA", "Where our tide predictions come from.", "about/", ABOUT))
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
    print(f"built {built} station pages, {len(groups)} states" + ("" if LAUNCHED else " (noindex)"))


if __name__ == "__main__":
    main()
