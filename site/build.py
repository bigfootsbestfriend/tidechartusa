"""Build the static site from data/ into _site/.

    python3 site/build.py
    SITE_URL=https://shorebite.com python3 site/build.py   # the live site

Stdlib only. Every station gets a page with today's chart, a week of tide times, a month
tide table, sun and moon, and a short write-up computed from its own predictions.
"""

import datetime as dt
import html
import json
import math
import os
import urllib.parse
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
import kingtides  # noqa: E402
import lowtides  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"
OUT = ROOT / "_site"
STATIC = Path(__file__).resolve().parent / "static"

# Flip to True when Mike approves launch: drops noindex and publishes the sitemap. (Launched 2026-10-10.)
# IndexNow key (public by design: search engines fetch /<key>.txt to confirm submissions come from us).
INDEXNOW_KEY = "ab023efee00f9ab2707e5dbe5e3881c7"
BING_AUTH = "166ED942B039ECB32E7BF3985158FC36"
LAUNCHED = True
SITE_URL = os.environ.get("SITE_URL", "https://bigfootsbestfriend.github.io/tidechartusa").rstrip("/")
BASE = urlparse(SITE_URL).path.rstrip("/") + "/"
SITE_NAME = "Shorebite"
# Google Analytics 4 measurement ID (G-...). Empty = no analytics tag.
GA_ID = os.environ.get("GA_ID", "")
CF_BEACON = os.environ.get("CF_BEACON", "")  # Cloudflare Web Analytics token (cookieless)
CLICKY_ID = os.environ.get("CLICKY_ID", "")  # Clicky site id
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

CSS_VER = "42"


def ga_tag():
    out = ""
    if GA_ID:
        out += (f'\n<script async src="https://www.googletagmanager.com/gtag/js?id={GA_ID}"></script>'
                f"<script>window.dataLayer=window.dataLayer||[];function gtag(){{dataLayer.push(arguments);}}"
                f"gtag('js',new Date());gtag('config','{GA_ID}');</script>")
    if CF_BEACON:
        out += ('\n<script defer src="https://static.cloudflareinsights.com/beacon.min.js" '
                f"data-cf-beacon='{{\"token\": \"{CF_BEACON}\"}}'></script>")
    if CLICKY_ID:
        out += f'\n<script async data-id="{CLICKY_ID}" src="//static.getclicky.com/js"></script>'
    return out


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
<script>(function(){{try{{var m=location.search.match(/[?&]sbmove=([^&#]*)/);if(!m)return;var o=JSON.parse(decodeURIComponent(m[1]));for(var k in o){{if(!/^tc-(saved|units|subbed|bar)$/.test(k))continue;if(k==="tc-saved"){{var cur=JSON.parse(localStorage.getItem(k)||"[]");JSON.parse(o[k]).forEach(function(s){{if(!cur.some(function(c){{return c.path===s.path}}))cur.push(s)}});localStorage.setItem(k,JSON.stringify(cur.slice(0,30)))}}else if(!localStorage.getItem(k))localStorage.setItem(k,o[k])}}var q=location.search.replace(/[?&]sbmove=[^&#]*/,"").replace(/^&/,"?");history.replaceState(null,"",location.pathname+q+location.hash)}}catch(e){{}}}})()</script>
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
<meta property="og:site_name" content="{SITE_NAME}">
<meta property="og:image" content="{SITE_URL}/static/og.png">
<meta property="og:image:width" content="1200"><meta property="og:image:height" content="630">
<meta name="twitter:card" content="summary_large_image">{ga_tag()}
{ld}{extra_head}
</head>
<body>
<header class="top"><div class="wrap">
<a class="brand" href="{BASE}" aria-label="Shorebite home"><svg class="mark" viewBox="0 0 64 64" aria-hidden="true"><defs><clipPath id="sb-logo-r"><rect width="64" height="64" rx="15"/></clipPath><mask id="sb-logo-bite"><rect width="64" height="64" fill="#fff"/><circle cx="52" cy="13" r="5.2" fill="#000"/><circle cx="54.5" cy="20.5" r="4.6" fill="#000"/><circle cx="48" cy="7.5" r="4.4" fill="#000"/></mask></defs><g clip-path="url(#sb-logo-r)"><rect width="64" height="64" fill="#0b5c7a"/><circle cx="41" cy="20" r="12" fill="#f5b942" mask="url(#sb-logo-bite)"/><path d="M4 38c7 0 7-6 14-6s7 6 14 6 7-6 14-6 7 6 14 6v26H4z" fill="#5cc4e0"/><path d="M4 48c7 0 7-5 14-5s7 5 14 5 7-5 14-5 7 5 14 5v16H4z" fill="#fff"/></g></svg><span class="word">Shore<b>bite</b></span></a>
<nav><a href="{BASE}favorites/" class="nav-saved" data-nav-saved hidden><svg class="ico" viewBox="0 0 24 24" aria-hidden="true"><path d="m12 3 2.7 5.6 6.1.9-4.4 4.3 1 6.1L12 17l-5.4 2.9 1-6.1-4.4-4.3 6.1-.9z"/></svg>Favorites<span data-saved-count></span></a><a href="{BASE}fishing/">Fishing</a><a href="{BASE}king-tides/">King tides</a><a href="{BASE}states/">States</a><a href="{BASE}how-to-read-a-tide-chart/">How to read</a></nav>
</div></header>
<main class="wrap">
{body}
</main>
<footer class="foot"><div class="wrap">
<p>Tide and current predictions and live readings from <a href="https://tidesandcurrents.noaa.gov/">NOAA CO-OPS</a>, buoys from <a href="https://www.ndbc.noaa.gov/">NOAA NDBC</a>, marine forecasts from the <a href="https://www.weather.gov/marine/">National Weather Service</a>, town names from <a href="https://www.geonames.org/">GeoNames</a> (CC BY 4.0). Predictions refresh every night. Predictions are not observations: wind, pressure and river flow can move the real water level. <strong>Not for navigation.</strong></p>
{f'<p class="foot-cta">{ico("mail")} <a href="{BASE}#signup-band">Get free weekly tide emails for your beach</a></p>' if ALERTS_API else ""}
<p><a href="{BASE}about/">About</a> · <a href="{BASE}widget/">Free tide widget</a> · <a href="{BASE}king-tides/">King tides</a> · <a href="{BASE}tide-pools/">Tide pools</a> · <a href="{BASE}gear/">Gear</a> · <a href="{BASE}privacy/">Privacy</a> · <a href="{BASE}how-to-read-a-tide-chart/">How to read a tide chart</a> · Not affiliated with NOAA. As an Amazon Associate we earn from qualifying purchases.</p>
</div></footer>
{js}
<script src="{BASE}static/app.js?v={CSS_VER}" defer></script>
<script src="{BASE}static/track.js?v={CSS_VER}" defer></script>
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


# ---------- hourly bite forecast (same model as the app) ----------
# Score per hour, from what anglers most often track: solunar periods (up to 32), moving water vs this station's
# usual (up to 26), dawn/dusk light (up to 16) and moon phase (up to 12). In the browser, static/bite.js adds the
# live wind, gusts and pressure trend from the National Weather Service. Calibrated so a typical day lands near 55
# and roughly the best 15% of days score above 75.
BITE_BANDS = [(75, "Excellent"), (55, "Good"), (35, "Fair"), (0, "Slow")]


def bite_label(s):
    return next(label for cut, label in BITE_BANDS if s >= cut)


def bite_band(s):
    return 4 if s >= 75 else 3 if s >= 55 else 2 if s >= 35 else 1


def _bump(t, mid, width):
    return math.exp(-(((t - mid) / width) ** 2))


def _rate_at(events, t):
    """How fast the water is rising or falling at time t (ft per hour), from the cosine curve."""
    for (ta, ha, _), (tb, hb, _) in zip(events, events[1:]):
        if ta <= t <= tb:
            return abs(hb - ha) * math.pi / 2 * math.sin(math.pi * (t - ta) / (tb - ta)) / ((tb - ta) / 3600)
    return None


def bite_days(st, days, tz, events, f, sun_by_day):
    """{date: (score, [hour scores], [(from, to, peak) best windows])} for each day in days."""
    rates = sorted(abs(b[1] - a[1]) * math.pi / 2 / ((b[0] - a[0]) / 3600) for a, b in zip(events, events[1:]) if b[0] > a[0])
    max_rate = rates[int(len(rates) * 0.8)] if rates else 1
    typical = f.get("mean_range") or 1
    out = {}
    for d in days:
        start = dt.datetime.combine(d, dt.time(0), tz).timestamp()
        end = dt.datetime.combine(d + dt.timedelta(days=1), dt.time(0), tz).timestamp()
        mt = astro.moon_times(st["lat"], st["lng"], d, tz)
        periods = [(m.timestamp(), 1.0, 70 * 60) for m in mt["over"] + mt["under"]] + \
                  [(m.timestamp(), 0.55, 45 * 60) for m in mt["rise"] + mt["set"]]
        noon = dt.datetime.combine(d, dt.time(12), tz)
        phase = ((noon - astro.NEW_MOON).total_seconds() / 86400 % astro.SYNODIC) / astro.SYNODIC
        pf = max(0.0, 1 - min(phase, abs(phase - 0.5), 1 - phase) / 0.15)
        rise, sset = sun_by_day.get(d, (None, None))
        hours, t = [], start + 1800
        while t < end:
            sol = max([w * _bump(t, mid, width) for mid, w, width in periods] or [0])
            r = _rate_at(events, t)
            mv = min(1.0, r / max_rate) if r is not None else 0
            light = max([_bump(t, x.timestamp(), 75 * 60) for x in (rise, sset) if x] or [0])
            hours.append((t, 8 + sol * 32 + mv * 26 + light * 16 + pf * 12))
            t += 3600
        if not hours:
            continue
        pts = [h for _, h in curve_points(events, start, end, 1200)]
        rr = (max(pts) - min(pts)) / typical if pts else 1
        day_adj = (pf - 0.3) * 20 + max(-0.5, min(0.7, rr - 1.1)) * 12
        scale = lambda raw: max(3, min(98, 55 + (raw - 58) * 1.8 + day_adj))
        top3 = sum(sorted((s for _, s in hours), reverse=True)[:3]) / min(3, len(hours))
        scores = [round(scale(s)) for _, s in hours]
        cut = max(max(scores) - 12, 40)
        windows, run = [], None
        for (t, _), s in zip(hours, scores):
            if s >= cut:
                run = [t - 1800, t + 1800, s] if not run else [run[0], t + 1800, max(run[2], s)]
            elif run:
                windows.append(run)
                run = None
        if run:
            windows.append(run)
        windows.sort(key=lambda w: -w[2])
        out[d] = (round(max(5, scale(top3))), scores, windows[:3])
    return out


SPECIES_GUIDE = json.loads((Path(__file__).resolve().parent / "species_guide.json").read_text())


def region_of(st):
    return next((k for k, v in SPECIES_GUIDE["regions"].items() if st["state"] in v), "ma")


def biting_now(st, month):
    """Regional seasonal guide: species in season this month first, then ones starting next month."""
    nxt = 1 if month == 12 else month + 1
    out = [(n, tip, month in ms) for n, ms, tip in SPECIES_GUIDE["species"].get(region_of(st), [])
           if month in ms or nxt in ms]
    return sorted(out, key=lambda x: not x[2])


def span(a, b):
    return f"{clock(a)}–{clock(b)}"


def fishing_section(st, name, week, tz, f, sun_by_day, bite):
    """Day-by-day fishing table: bite score, best windows, and the solunar periods behind them."""
    rows = []
    for d in week:
        score, majors, minors = fish_day(st, d, tz, f, sun_by_day)
        b = bite.get(d)
        maj = ", ".join(span(m - dt.timedelta(hours=1), m + dt.timedelta(hours=1)) for m in majors) or "—"
        mnr = ", ".join(span(m - dt.timedelta(minutes=30), m + dt.timedelta(minutes=30)) for m in minors) or "—"
        best = ", ".join(span(dt.datetime.fromtimestamp(a, tz), dt.datetime.fromtimestamp(z, tz)) for a, z, _ in b[2][:2]) if b else "—"
        rate = (f'<span class="rate b{bite_band(b[0])}">{b[0]} · {bite_label(b[0])}</span>' if b
                else f'<span class="rate r{score}">{FISH_LABELS[score]}</span>')
        rows.append(f'<tr data-day="{d.isoformat()}"><th scope="row">{day_label(d, True)}</th>'
                    f'<td>{rate}</td><td>{best}</td><td>{maj}</td><td>{mnr}</td></tr>')
    return f"""
<h2 id="fishing">Best fishing times at {esc(name)}</h2>
<p>The <b>bite score</b> (0 to 100) adds up what anglers watch most: moving water (a tide running harder than usual here
scores higher), <b>solunar periods</b> (major periods of about two hours centred on the moon overhead or underfoot, minor
periods of about an hour on moonrise and moonset), dawn and dusk light, and how close it is to the new or full moon.
<b>Best times</b> are the stretches of the day scoring near that day's top.</p>
<div class="scroll"><table class="tides week fishing"><thead><tr><th>Day</th><th>Bite score</th><th>Best times</th><th>Major periods</th><th>Minor periods</th></tr></thead>
<tbody>{"".join(rows)}</tbody></table></div>
<p class="note">A planning aid, not a guarantee. Wind, water clarity, bait and pressure changes matter too; the forecast above adds live wind and pressure when you open the page. <a href="{BASE}gear/#fishing">Surf and pier fishing gear</a>.</p>"""


SPECIES_FILE = ROOT / "collector" / "species.json"
FISH_HERE = json.loads(SPECIES_FILE.read_text()) if SPECIES_FILE.exists() else {"sp": {}, "st": {}}
HAB = {"s": "Salt water", "b": "Brackish water", "f": "Fresh water", "?": ""}


def fish_here_section(st, name):
    """Fish recorded around the station (collector/species.py: open-licence GBIF records), salt and brackish first."""
    got = FISH_HERE["st"].get(st["id"])
    if not got:
        return ""
    r, rows = got
    sp = [(FISH_HERE["sp"][str(k)], c) for k, c in rows if str(k) in FISH_HERE["sp"]]
    water = [(x, c) for x, c in sp if x[2] != "f"]
    fresh = [(x, c) for x, c in sp if x[2] == "f"]
    if not water and not fresh:
        return ""
    top = max(c for _, c in sp)

    def li(x, c):
        common, sci, hab = x
        label = esc(common) if common else f"<i>{esc(sci)}</i>"
        return (f'<li><span><b>{label}</b>{f" <i>{esc(sci)}</i>" if common else ""}'
                f'<small>{HAB[hab] + " · " if HAB[hab] else ""}{c} record{"s" if c != 1 else ""}</small></span>'
                f'<em style="width:{max(4, round(100 * c / top))}%"></em></li>')
    first = ", ".join(x[0] or x[1] for x, _ in water[:3])
    out = [f'<h2 id="fish-here">{ico("fish")}Fish in the waters around {esc(name)}</h2>',
           f'<p>{len(water)} kinds of fish, sharks and rays have been recorded within {r} km (about {round(r * 0.621)} miles) of this spot'
           + (f", most often {esc(first)}" if first else "") + '. The bar shows how many records each has.</p>' if water else ""]
    if water:
        out.append(f'<ul class="fishlist">{"".join(li(x, c) for x, c in water)}</ul>')
    if fresh:
        out.append(f'<details class="fishfresh"><summary>Fresh water nearby · {len(fresh)} species</summary>'
                   f'<p class="note">Rivers, creeks and ponds within {r} km, not the tidal water itself.</p>'
                   f'<ul class="fishlist">{"".join(li(x, c) for x, c in fresh)}</ul></details>')
    out.append('<p class="note">Records from <a href="https://www.gbif.org/">GBIF</a> datasets released under CC0 or CC BY 4.0 '
               '(museum collections, surveys and community sightings). It shows what has been found here, not a complete list. '
               'Check your state rules before keeping fish.</p>')
    return f'<section class="fishhere">{"".join(out)}</section>'


def bite_card(st, name, bite, today, week, tz):
    """'Fishing forecast' card: today's score, best windows and an hour-by-hour strip. static/bite.js makes the
    days clickable, marks the current hour, folds in live wind, gusts, rain and pressure, and adds the radar loop."""
    if today not in bite:
        return ""
    score, hrs, wins = bite[today]
    month = dt.datetime.combine(today, dt.time(12), tz)
    chips = "".join(
        f'<button type="button" data-bd="{d.isoformat()}" aria-pressed="{str(d == today).lower()}">'
        f'<span>{"Today" if d == today else d.strftime("%a")}</span><b class="b{bite_band(bite[d][0])}">{bite[d][0]}</b></button>'
        for d in week if d in bite)
    bars = "".join(f'<i class="b{bite_band(s)}" style="height:{max(6, s)}%" title="{clock(dt.datetime.fromtimestamp(dt.datetime.combine(today, dt.time(0), tz).timestamp() + 3600 * n, tz))}: {s}"></i>'
                   for n, s in enumerate(hrs))
    best = " and ".join(span(dt.datetime.fromtimestamp(a, tz), dt.datetime.fromtimestamp(z, tz)) for a, z, _ in wins[:2])
    sp = biting_now(st, month.month)
    region = SPECIES_GUIDE["names"].get(region_of(st), "")
    sp_html = "".join(f'<li class="{"now" if now else "soon"}"><b>{esc(n)}</b> <small>{"In season" if now else "Starting soon"}</small><span>{esc(tip)}</span></li>'
                      for n, tip, now in sp)
    ph, lit = astro.moon(month)
    return f"""
<section class="card bite" id="bite">
<div class="bite-head"><h2>{ico("fish")}Fishing forecast</h2><span class="sub" id="bite-sub">Hour by hour at {esc(name)}</span></div>
<div class="bite-days" id="bite-days" role="group" aria-label="Day">{chips}</div>
<div class="bite-main">
<div class="bite-ring b{bite_band(score)}" id="bite-ring"><b id="bite-score">{score}</b><span id="bite-label">{bite_label(score)}</span></div>
<div class="bite-best"><p class="lbl">Best times</p><p class="win" id="bite-win">{best or "—"}</p>
<p class="why" id="bite-why">{esc(ph if ph.lower().endswith("moon") else ph + " moon")} ({lit}% lit)</p></div>
</div>
<div class="bite-bars" id="bite-bars" aria-hidden="true">{bars}</div>
<div class="bite-axis" aria-hidden="true"><span>12a</span><span>6a</span><span>12p</span><span>6p</span><span>12a</span></div>
<p class="bite-hour" id="bite-hour" aria-live="polite"></p>
<ul class="bite-factors" id="bite-factors"></ul>
<details class="bite-radar" id="bite-radar" hidden><summary>{ico("forecast")}Rain radar</summary><div class="radar-box"></div></details>
{f'<h3>Biting around here in {month.strftime("%B")}</h3><ul class="biting">{sp_html}</ul><p class="note">General seasonal guide for {esc(region)}. Seasons, sizes and limits vary, so check your state rules before keeping fish.</p>' if sp else ""}
</section>"""


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


REPORT_CHIPS = [("clear", "Clear water"), ("murky", "Murky"), ("calm", "Calm"), ("choppy", "Choppy"), ("rough", "Rough"),
                ("windy", "Windy"), ("crowded", "Crowded"), ("quiet", "Quiet"), ("fish-biting", "Fish biting"),
                ("slow-fishing", "Slow fishing"), ("great-tidepools", "Great tide pools"), ("higher-than-predicted", "Water higher than predicted"),
                ("lower-than-predicted", "Water lower than predicted"), ("seaweed", "Lots of seaweed"), ("jellyfish", "Jellyfish")]


def reports_card(st, name):
    if not ALERTS_API:
        return ""
    chips = "".join(f'<button type="button" class="chip" data-chip="{k}" aria-pressed="false">{esc(t)}</button>' for k, t in REPORT_CHIPS)
    return f"""
<section class="card reports" id="reports" data-api="{ALERTS_API}" data-station="{esc(st["id"])}" data-labels='{esc(json.dumps(dict(REPORT_CHIPS)))}'>
<h2>{ico("chat")}How was it out there?</h2>
<p class="sub">Been to {esc(name)} recently? Tap what you saw to help the next person. No account needed.</p>
<div class="chips">{chips}</div>
<textarea id="rp-note" maxlength="280" rows="2" placeholder="Anything else? (optional, no links)"></textarea>
<p class="rp-row"><button type="button" class="rp-send" data-rp-send>Share my report</button> <span id="rp-msg" class="note"></span></p>
<h3>Recent reports</h3>
<ul class="rp-list" id="rp-list"><li class="note">No reports in the last 30 days yet. Be the first.</li></ul>
<p class="note">Reports are from visitors and may be wrong. Inappropriate ones are removed.</p>
</section>"""


def signup_card(st, name, ctx):
    if not ALERTS_API:
        return ""
    warn = ("Warnings for this water: small craft advisories, gales, coastal flooding"
            if ctx.get("zone") else "Weather warnings here: coastal flooding, high surf, storms")
    return f"""
<section class="card signup" id="emails">
<h2>{ico("mail")}Free tide emails for {esc(name)}</h2>
<p class="sub">Pick what's useful. No spam, no sharing your address, unsubscribe in one click.</p>
<form method="post" action="{ALERTS_API}/subscribe" data-signup-form>
<input type="hidden" name="station" value="{esc(st["id"])}"><input type="hidden" name="name" value="{esc(name)}">
<input type="text" name="website" tabindex="-1" autocomplete="off" class="hp" aria-hidden="true">
<label class="opt"><input type="checkbox" name="weekly" value="1" checked> <span><b>This week's tides</b>, every Thursday morning in time to plan the weekend</span></label>
<label class="opt"><input type="checkbox" name="warn" value="1" checked> <span><b>{warn.split(":")[0]}</b>:{warn.split(":", 1)[1]}</span></label>
<label class="opt"><input type="checkbox" name="lows" value="1" checked> <span><b>Minus-tide heads-up</b> when the weekend has great low tides for tide pools and clamming</span></label>
<div class="row"><input type="email" name="email" required placeholder="you@example.com" aria-label="Email address" autocomplete="email"><button type="submit">Send me tides</button></div>
<p class="note">We'll email you once to confirm. <a href="{BASE}privacy/">Privacy</a></p>
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
    check: "<b>Almost done.</b> Check your inbox for an email from hello@shorebite.com and click the button to confirm. (Look in spam or promotions if it's not there in a minute.)",
    invalid: "That email address didn't look right. Please go back and try again.",
    nothing: "Pick at least one kind of email, then try again.",
    error: "Something went wrong on our end. Please try again in a few minutes.",
  }};
  const post = (path, t) => fetch(api + path, {{ method: "POST", headers: {{ "content-type": "application/json" }}, body: JSON.stringify({{ t }}) }})
    .then((r) => r.json()).catch(() => ({{ state: "error" }}));
  if (q.get("confirm")) {{
    say("Confirming…");
    post("/confirm", q.get("confirm")).then((r) => say(r.state === "confirmed" ? "<b>You're subscribed.</b> Your first email arrives with the next update. Every email has an unsubscribe link. Have another favorite spot? <a href=\"" + {base!r} + "\">Add it too</a>."
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
    # Water temperature sensors go offline now and then: also list the nearest other ones (within 20 miles)
    # so the browser can fall back to them, saying where the reading is from.
    wt_alt = [f'{o["id"]}:{d:.0f}:{o["pretty"].replace(",", "").replace(":", " ")}' for d, o in ctx.get("near_wt", [])]
    attrs = (f'data-st="{esc(st["id"])}" data-wt="{int(wt or bool(wt_alt))}" data-wl="{int(wl)}" '
             f'data-wt-alt="{esc(",".join(wt_alt))}" '
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
    if wt or wt_alt:
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
                             f"{day_label(dt.datetime.fromtimestamp(t, tz).date())}</li>" for v, t in dl) + "</ol>"
                   + ('<p class="cta-line"><button type="button" class="linkish" data-signup="lows">Get an email before weekends with minus tides</button></p>'
                      if ALERTS_API else ""))

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
        sc, majors, minors = fish_day(st, d, tz, f, sun_by_day)
        fish[d.isoformat()] = [sc, [int(m.timestamp()) for m in majors], [int(m.timestamp()) for m in minors]]
    data["fish"] = fish
    bite = bite_days(st, week, tz, events, f, sun_by_day)
    data["bite"] = {d.isoformat(): [sc, hrs, [[int(a), int(z), p] for a, z, p in w]] for d, (sc, hrs, w) in bite.items()}
    st["_bite"] = bite
    if ctx.get("cur"):
        meta, cdist, cev = ctx["cur"]
        data["cur"] = {"name": tidy(meta["name"]), "mi": cdist, "ev": [
            [int(dt.datetime.strptime(t, "%Y-%m-%d %H:%M").replace(tzinfo=tz).timestamp()), v, k] for t, v, k in cev]}
    town = st.get("town")  # (name, state code, miles, page path) or None
    if town and town[0].lower() not in name.lower():
        title = f"{town[0]}, {st['state']} Tide Chart & Tide Times ({name})"
        desc = (f"Today's high and low tide times for {name} near {town[0]}, {state}, with a tide chart, a 7-day tide table, "
                f"currents, an hourly fishing forecast and the marine forecast. From NOAA station {st['id']}.")
    else:
        title = f"{name}, {st['state']} Tide Chart & Tide Times"
        desc = (f"Today's high and low tide times for {name}, {state}, with a tide chart, a 7-day tide table, "
                f"currents, an hourly fishing forecast and the marine forecast. From NOAA station {st['id']}.")
    near_town = (f' · <a href="{BASE}{town[3]}">near {esc(town[0])}</a> ({town[2]:.0f} mi)' if town and town[2] >= 1
                 else f' · <a href="{BASE}{town[3]}">{esc(town[0])}</a>' if town else "")
    gmap = f"https://www.google.com/maps?q={st['lat']},{st['lng']}"
    year_links = "".join(f' <a class="yr" href="{BASE}{st["path"]}{y}/">Full {y} tide table</a>' for y in ctx.get("years", ()))
    week_html = f"""<h2 id="week">Tide times this week</h2>
<div class="scroll"><table class="tides week"><thead><tr><th>Day</th><th>High and low tides</th><th>Sunrise / sunset</th><th>Moon</th></tr></thead>
<tbody>{week_rows}</tbody></table></div>"""
    kt_line = kt_station_line(st, ctx["kt"], ctx["today"]) if ctx.get("kt") else ""
    if dl_html and ctx.get("tp"):
        dl_html += tp_station_line(st, ctx["tp"], ctx["today"])
    month_html = f"""<h2 id="month">Tide table: {m_title}</h2>
{kt_line}
<p class="tools"><button type="button" data-print>Print this tide table</button> <button type="button" data-ics>Add tides to my calendar (.ics)</button>{year_links}</p>
<div class="scroll"><table class="tides month"><thead><tr><th>Day</th><th>High and low tides</th><th>Sunrise / sunset</th></tr></thead>
<tbody>{month_rows}</tbody></table></div>
<p class="note">Heights are in feet above mean lower low water (MLLW), the zero line on most US nautical charts. A minus height means the water drops below that line.</p>"""
    cur_html = currents_section(name, ctx.get("cur"), week, tz)
    fish_html = fishing_section(st, name, week, tz, f, sun_by_day, bite)
    jumps = [("Today", "chart", "today")] + ([("Email me", "mail", "emails")] if ALERTS_API else []) + [("Fishing", "fish", "bite"), ("Plan a trip", "plan", "plan"), ("Weather", "forecast", "live"), ("Week", "week", "week")]
    jumps += [("Currents", "current", "currents")] if cur_html else []
    jumps += [("Low tides", "low", "lows")] if dl_html else []
    jumps += [("Month", "cal", "month")]
    jumps += [("Nearby", "pin", "around")] if ctx.get("places") else []
    jumps += [("Fish here", "fish", "fish-here")] if FISH_HERE["st"].get(st["id"]) else []
    jumps += [("Radio", "radio", "radio")]
    jumps += [("Reports", "chat", "reports")] if ALERTS_API else []
    body = f"""
<article class="station">
<h1>{esc(name)} tide chart</h1>
<p class="sub">{esc(state)}{near_town} · NOAA station {esc(st['id'])} · times in local time ({esc(dt.datetime.combine(today, dt.time(12), tz).strftime('%Z'))})</p>
{jump_nav(jumps)}
<section class="alerts-banner" id="alerts" aria-live="polite" hidden><template class="i-warn">{ico("warn")}</template><template class="i-check">{ico("check")}</template></section>
<div class="pagetools"><div class="acts-row" id="acts-row" hidden>
<button type="button" class="tool save" data-save aria-pressed="false">{ico("star")}<span><b>Favorite</b><small>One tap away under Favorites, and works with no signal.</small></span></button>
<button type="button" class="tool install" data-install hidden>{ico("phone")}<span><b>Add to home screen</b><small>Opens like an app, one tap away.</small></span></button>
<button type="button" class="tool" data-pocket aria-expanded="false">{ico("print")}<span><b>Pocket card</b><small>A printed card for fishing, boating or the beach.</small></span></button>
<button type="button" class="tool" data-share>{ico("share")}<span><b>Share</b><small>Send today's tides to a friend.</small></span></button>
</div>
<div class="pocket-opts" id="pocket-opts" hidden>
<h3>{ico("print")}Make a pocket card</h3>
<p class="po-label">What's it for?</p>
<div class="po-acts">
<button type="button" data-pk="general" aria-pressed="true">{ico("chart")}Everyday</button>
<button type="button" data-pk="fishing" aria-pressed="false">{ico("fish")}Fishing</button>
<button type="button" data-pk="boating" aria-pressed="false">{ico("kayak")}Boating &amp; paddling</button>
<button type="button" data-pk="beach" aria-pressed="false">{ico("pool")}Beach &amp; tide pools</button>
</div>
<p class="po-label">How many days?</p>
<div class="po-days"><button type="button" data-days="3" aria-pressed="false">3</button><button type="button" data-days="7" aria-pressed="true">7</button><button type="button" data-days="14" aria-pressed="false">14</button></div>
<label class="opt"><input type="checkbox" data-opt="radio" checked> Radio channels and weather radio</label>
<label class="opt"><input type="checkbox" data-opt="notes" checked> Space for notes</label>
<p class="po-go"><button type="button" class="rp-send" data-pk-print>Print my card</button> <span class="note">Fits on one page. Fold it in half for your pocket.</span></p>
</div>
<div class="units" id="units" hidden><span>Units</span><button type="button" data-u="ft">ft</button><button type="button" data-u="m">m</button><span class="sep"></span><button type="button" data-u="12">12h</button><button type="button" data-u="24">24h</button></div></div>

<section class="today card" id="today">
<div class="today-head"><h2>{ico("chart")}<span id="today-title">Tides today, {day_label(today)}</span></h2><p class="now" id="now" hidden></p></div>
<div class="daypick" id="daypick" hidden></div>
<div id="chart">{chart}</div>
<ul class="tlist" id="tlist">{today_rows}</ul>
<div class="dayextra" id="dayextra"></div>
<p class="acc" id="acc" hidden>Were today's predicted times right where you were? <button type="button" data-acc="1">👍 Spot on</button> <button type="button" data-acc="0">👎 Off</button> <span id="acc-msg"></span></p>
<p class="sunline" id="sunline">Sunrise {clock(rise) if rise else '—'} · Sunset {clock(sset) if sset else '—'} · {moon_cell(today)}</p>
</section>

<section class="card plan" id="plan" hidden>
<h2>{ico("plan")}Plan a trip</h2>
<p class="sub">Pick what you want to do and we'll find the best days and times coming up.</p>
<div class="acts" role="radiogroup" aria-label="Activity">
<button type="button" data-act="pool" aria-pressed="true">{ico("pool")}Tide pooling</button>
<button type="button" data-act="fish" aria-pressed="false">{ico("fish")}Fishing</button>
<button type="button" data-act="kayak" aria-pressed="false">{ico("kayak")}Kayak / paddle</button>
<button type="button" data-act="walk" aria-pressed="false">{ico("walk")}Beach walk</button>
</div>
<ol class="plan-list" id="plan-list"></ol>
<p class="note" id="plan-note"></p>
</section>

{bite_card(st, name, bite, today, week, tz)}

{signup_card(st, name, ctx)}

{live_section(st, name, ctx)}

{reports_card(st, name)}

<div class="tabs" data-tabs>
{tab("This week", "week", week_html)}
{tab("Currents", "current", cur_html)}
{tab("Fishing", "fish", fish_html)}
{tab("Low tides", "low", dl_html)}
{tab("Month", "cal", month_html, "month-tab")}
</div>


{places_section(name, ctx.get("places"))}

{fish_here_section(st, name)}

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
<details class="embed" id="embed"><summary>{ico("code")}Put these tides on your website</summary>
<p>Free for marinas, bait shops, clubs, rentals and anyone else. Paste this where you want the tide card to appear:</p>
<textarea readonly rows="4" onclick="this.select()">{esc(embed_code(st))}</textarea>
<p><button type="button" class="copy" onclick="navigator.clipboard.writeText(this.parentNode.previousElementSibling.value);this.textContent='Copied'">Copy the code</button> <a href="{BASE}widget/">How it works</a></p>
<iframe src="{BASE}embed/{st['id']}/" title="Preview" width="340" height="270" style="border:0;max-width:100%" loading="lazy"></iframe>
</details>
</article>
<script type="application/json" id="tide-data">{json.dumps(data, separators=(",", ":"))}</script>
"""
    crumbs = [("Home", ""), (state, f"tides/{slugify(state)}/"), (name, st["path"])]
    place_ld = {"@context": "https://schema.org", "@type": "Place", "name": f"{name} tide station",
                "geo": {"@type": "GeoCoordinates", "latitude": round(st["lat"], 5), "longitude": round(st["lng"], 5)},
                "address": {"@type": "PostalAddress", "addressRegion": state, "addressCountry": "US",
                            **({"addressLocality": town[0]} if town else {})},
                "url": SITE_URL + "/" + st["path"]}
    return page(title, desc, st["path"], body, crumbs=crumbs, scripts=("units.js", "tide.js", "bite.js", "live.js", "planner.js", "signup.js", "community.js", "pocket.js"),
                extra_head='<script type="application/ld+json">' + json.dumps(place_ld) + "</script>")


# ---------- other pages ----------

YEAR_DIR = DATA / "year"


def year_page(st, year, raw, tz):
    """A printable tide table for a whole calendar year, one month per printed page, with the year's extremes."""
    name = st["pretty"]
    state = STATES.get(st["state"], st["state"])
    by_day = {}
    for t, v, k in raw:
        w = dt.datetime.strptime(f"{year}-{t}", "%Y-%m-%d %H:%M").replace(tzinfo=tz)
        by_day.setdefault(w.date(), []).append((w, v, k))
    highs = sorted(((v, w) for evs in by_day.values() for w, v, k in evs if k == "H"), reverse=True)
    lows = sorted((v, w) for evs in by_day.values() for w, v, k in evs if k == "L")
    if not highs or not lows:
        return None
    minus_day = 0
    # Mark the single day of each new and full moon (least and most illuminated), not the whole phase.
    lit = {}
    d = dt.date(year, 1, 1) - dt.timedelta(days=1)
    while d <= dt.date(year, 12, 31) + dt.timedelta(days=1):
        lit[d] = astro.moon(dt.datetime.combine(d, dt.time(12), tz))[1]
        d += dt.timedelta(days=1)
    marks = {}
    for d, v in lit.items():
        a, b = lit.get(d - dt.timedelta(days=1)), lit.get(d + dt.timedelta(days=1))
        if a is not None and b is not None:
            if v <= a and v < b and v < 15:
                marks[d] = "●"
            elif v >= a and v > b and v > 85:
                marks[d] = "○"
    months = []
    for m in range(1, 13):
        first = dt.date(year, m, 1)
        last = (dt.date(year + (m == 12), m % 12 + 1, 1) - dt.timedelta(days=1))
        rows = []
        d = first
        while d <= last:
            rise, sset = astro.sun(st["lat"], st["lng"], d, tz)
            evs = by_day.get(d, [])
            cells = " ".join(
                f'<span class="ev {k}{" minus" if v < 0 else ""}"><b>{k}</b> {clock(w)} <i>{ft(v)}</i></span>' for w, v, k in evs)
            if rise and any(k == "L" and v < 0 and rise <= w <= sset for w, v, k in evs):
                minus_day += 1
            mk = marks.get(d, "")
            moon = f'<span class="mo" title="{"New moon" if mk == "●" else "Full moon"}"> {mk}</span>' if mk else ""
            rows.append(f'<tr><th scope="row">{d.strftime("%a %-d")}{moon}</th><td class="evs">{cells}</td>'
                        f'<td>{clock(rise) if rise else "—"} / {clock(sset) if sset else "—"}</td></tr>')
            d += dt.timedelta(days=1)
        mname = first.strftime("%B")
        months.append(f'<section class="ym" id="{mname.lower()}"><h2>{mname} {year}</h2><div class="scroll"><table class="tides month">'
                      f'<thead><tr><th>Day</th><th>High and low tides</th><th>Sunrise / sunset</th></tr></thead>'
                      f'<tbody>{"".join(rows)}</tbody></table></div></section>')
    kings = []
    for v, w in highs:  # the five highest tides, at most one per day
        if all(w.date() != k.date() for _, k in kings):
            kings.append((v, w))
        if len(kings) == 5:
            break
    town = st.get("town")
    near = f" near {town[0]}" if town and town[0].lower() not in name.lower() else ""
    jan, jul = dt.datetime(year, 1, 15, tzinfo=tz), dt.datetime(year, 7, 15, tzinfo=tz)
    dst = ", adjusted for daylight saving time" if jan.utcoffset() != jul.utcoffset() else ""
    summary = (f"<ul class='facts'><li><b>Highest tide:</b> {ft(highs[0][0])} on {highs[0][1].strftime('%B %-d')} at {clock(highs[0][1])}</li>"
               f"<li><b>Lowest tide:</b> {ft(lows[0][0])} on {lows[0][1].strftime('%B %-d')} at {clock(lows[0][1])}</li>"
               f"<li><b>King tides</b> (the year's highest): {', '.join(w.strftime('%b %-d') for _, w in sorted(kings, key=lambda x: x[1]))}</li>"
               + (f"<li><b>Days with a minus tide in daylight:</b> {minus_day}, good for tide pools and clamming</li></ul>" if minus_day
                  else f"<li><b>Minus tides in daylight:</b> none this year; the lowest daytime water is in the table below</li></ul>"))
    jump = " · ".join(f'<a href="#{dt.date(year, m, 1).strftime("%B").lower()}">{dt.date(year, m, 1).strftime("%b")}</a>' for m in range(1, 13))
    body = f"""
<article class="year-page">
<h1>{esc(name)} tide table {year}</h1>
<p class="sub">{esc(state)}{esc(near)} · NOAA station {esc(st['id'])} · times in local time{dst} · heights in feet above MLLW</p>
<p class="tools"><button type="button" onclick="print()">Print the {year} tide table</button> <a href="{BASE}{st['path']}">Today's chart and forecast for {esc(name)}</a></p>
<h2>{year} at a glance</h2>
{summary}
<p class="ymjump">{jump}</p>
<p class="note">H = high tide, L = low tide. Bold lows are minus tides (below the chart datum). ● new moon, ○ full moon: tides run biggest a day or two after each.</p>
{"".join(months)}
<p class="note">Predictions from NOAA CO-OPS. Weather can move the real water level. Not for navigation.</p>
</article>"""
    path = f"{st['path']}{year}/"
    title = f"{name}, {st['state']} Tide Table {year}" + (f" ({town[0]})" if near else "")
    desc = (f"{year} tide table for {name}{near}, {state}: every high and low tide of the year with sunrise and sunset, "
            f"king tides and minus tides. Printable, from NOAA station {st['id']}.")
    crumbs = [("Home", ""), (state, f"tides/{slugify(state)}/"), (name, st["path"]), (f"{year} tide table", path)]
    return path, page(title, desc, path, body, crumbs=crumbs, scripts=("units.js",))


# Official king tide photo projects, by state (checked 2026-10-11). MyCoast covers several states from one app.
KT_PROGRAMS = {
    "CA": [("California King Tides Project", "https://www.coastal.ca.gov/kingtides/",
            "run by the California Coastal Commission; share photos of the highest tides near you")],
    "OR": [("Oregon King Tides Project", "https://www.oregonkingtides.net/",
            "photos from the Oregon coast help map where water reaches today")],
    "WA": [("Washington Sea Grant king tides calendar", "https://waseagrant.uw.edu/our-programs/coastal-hazards-climate-resilience/king-tides/king-tides-calendar/",
            "the official Washington dates and a guide to sharing photos")],
    "HI": [("Hawaiʻi & Pacific Islands King Tides Project", "https://www.pacioos.hawaii.edu/projects/king-tides/",
            "University of Hawaiʻi Sea Grant; photos go on a public map")],
}
for _c in ("MA", "MD", "NJ", "RI", "SC", "WA", "FL", "TX"):
    KT_PROGRAMS.setdefault(_c, []).append(("MyCoast", "https://mycoast.org/",
                                           "a free app for reporting king tides and coastal flooding, used by state agencies and researchers"))

KT_SAFETY_TIPS = [
    ("waves", "Stay off the edges", "Jetties, sea walls and rock shelves get hit by bigger waves than usual near the peak."),
    ("log", "Watch the drift logs", "On the Pacific coast, sneaker waves can roll a log onto you in a few inches of surf."),
    ("car", "Don't drive through water", "Salt water ruins cars, and flooded curbs and storm drains are hidden."),
    ("wind", "Check the forecast", "Onshore wind, low pressure or heavy rain can add a foot or more to the predicted tide."),
]
KT_PHOTO_TIPS = [
    ("clock", "Arrive early", "Get there half an hour before your spot's peak and stay until it passes."),
    ("ruler", "Show the scale", "Frame something people know: a stair, sign, piling, sea wall or road."),
    ("compare", "Shoot a before", "Take the same shot at an ordinary high tide. The pair says more than words."),
    ("upload", "Share it", "Note the place, date and time and send it to your state's project. Planners use them to map rising seas."),
]


BITE_TIPS = [
    ("current", "Moving water", "A tide running harder than usual for the spot stirs up bait and scores higher."),
    ("moon", "Solunar periods", "About two hours around the moon overhead or underfoot, and an hour around moonrise and moonset."),
    ("sunrise", "Low light", "The hour around sunrise and sunset, when fish feed closer in."),
    ("phase", "Moon phase", "Days near the new and full moon bring bigger tides and stronger currents."),
    ("wind", "Wind", "On each spot's page, strong wind from the National Weather Service forecast lowers the score."),
    ("gauge", "Pressure", "Slowly falling pressure before a front raises the score; a sharp rise lowers it."),
]
KT_WHY = [
    ("phase", "Sun and moon line up", "Around every new and full moon their pull adds together: spring tides."),
    ("moon", "The moon is closest", "Once a month the moon reaches perigee. Near a new or full moon, tides run highest."),
    ("sun", "Earth is near the sun", "In early January Earth is closest to the sun, which adds a little more."),
]
KT_SEASONS = [
    ("waves", "Pacific coast", "The biggest tides come in winter, November to January."),
    ("sun", "Florida and the Southeast", "Early fall, when the ocean is warmest and sea level is at its seasonal high."),
    ("beach", "Hawaiʻi", "Two seasons: early summer and midwinter."),
]
GUIDE_TIPS = [
    ("chart", "The curve", "The wavy line is the predicted water height. Peaks are high tides, dips are low tides, and the steepest part is when water moves fastest."),
    ("ruler", "The numbers", "Heights are feet above mean lower low water (MLLW), the zero on nautical charts. A minus tide drops below it and uncovers extra beach."),
    ("compare", "Why the two highs differ", "Pacific, Alaska and Hawaiʻi tides are mixed: one high is much higher. Most of the Atlantic has two similar highs; parts of the Gulf get one."),
    ("phase", "Spring and neap tides", "Near the new and full moon, highs are higher and lows lower (spring tides). Near quarter moons the range shrinks (neap tides)."),
    ("wind", "Predictions vs. reality", "Onshore wind, low pressure or river flow can raise the water; offshore wind can drop it. Not for navigation."),
    ("pin", "Reference and nearby stations", "Reference stations are measured for years. Thousands of others are worked out from the nearest one and can be off by a few minutes."),
]


def tipcards(tips, tone):
    """A grid of colourful icon cards: short title plus one line, instead of a wall of bullets."""
    return f'<div class="tips t-{tone}">' + "".join(
        f'<div class="tcard"><span class="tc-i">{ico(i)}</span><div><b>{t}</b><p>{d}</p></div></div>'
        for i, t, d in tips) + "</div>"


def list_tools(total, refs):
    """Search, chips and sort for a state's station list (wired up in site.js). The HTML stays A to Z and fully shown."""
    chips = (f'<div class="kt-chips" role="group" aria-label="Station type"><span>{ico("pin")} Show</span>'
             f'<button type="button" data-k="" class="on">All {total}</button><button type="button" data-k="ref">Reference stations {refs}</button></div>') if 0 < refs < total else "<span></span>"
    return f"""<div class="kt-tools" data-list-tools data-target="ul.stations">
<label class="filter"><span>{ico("search")} Find a spot</span><input type="search" placeholder="Type a town, bay or inlet" data-lq></label>
<div class="kt-row">{chips}
<label class="kt-sort"><span>Sort</span><select data-lsort><option value="n">A to Z</option><option value="near">Nearest to me</option>
<option value="b">Best fishing today</option></select></label></div>
<p class="kt-count" data-lcount aria-live="polite">Showing all {total} spots</p></div>"""


KT_SORTS = (("d", "Soonest first"), ("a", "Biggest above normal"), ("h", "Highest tide"), ("n", "A to Z"))


def kt_tools(months, total, chip_label="Next king tide", sorts=KT_SORTS):
    """Search, month chips and sort for a long spot table (king tides, tide pools; wired up in site.js)."""
    chips = "".join(f'<button type="button" data-m="{m}">{dt.date.fromisoformat(m + "-01"):%b}</button>' for m in sorted(months)[:8])
    month_html = (f'<div class="kt-chips" role="group" aria-label="Month"><span>{ico("cal")} {chip_label}</span>'
                  f'<button type="button" data-m="" class="on">All</button>{chips}</div>') if len(months) > 1 else "<span></span>"
    return f"""<div class="kt-tools" data-kt-tools>
<label class="filter"><span>{ico("pin")} Find a spot</span><input type="search" placeholder="Type a town, bay or inlet" data-kt-q></label>
<div class="kt-row">{month_html}
<label class="kt-sort"><span>Sort</span><select data-kt-sort>{"".join(f'<option value="{v}">{t}</option>' for v, t in sorts)}</select></label></div>
<p class="kt-count" data-kt-count aria-live="polite">Showing all {total} spots</p></div>"""


def kt_path(code):
    return f"king-tides/{slugify(STATES.get(code, code))}/"


def kt_next(kt, today):
    """The spot's next king tide window that hasn't finished."""
    return next((w for w in kt["windows"] if w[1] >= today), None)


def kt_station_line(st, kt, today):
    """One line for the station page: the spot's next king tides, linked to the state page."""
    w = kt_next(kt, today)
    if not w:
        return ""
    a, b, pk, v = w
    state = STATES.get(st["state"], st["state"])
    return (f'<p class="tip kt-line"><b>Next king tides here:</b> {kingtides.span(a, b)}, peaking at {ft(v)} on '
            f'{pk:%a %b} {pk.day} at {clock(pk)} ({ft(v - kt["typical"])} above a typical high tide). '
            f'<a href="{BASE}{kt_path(st["state"])}">King tides in {esc(state)}</a></p>')


def kt_state_page(code, rows, today, built_at):
    """King tide dates for one state: statewide windows, then every spot's next king tides."""
    state = STATES.get(code, code)
    season = kingtides.season_label(today)
    wins = kingtides.state_windows([kt for _, kt in rows])
    path = kt_path(code)
    total = len(rows)
    upcoming = [w for w in wins if w[1] >= today]
    win_rows = "".join(
        f'<tr><td><b>{kingtides.span(a, b)}</b></td><td>{pk:%a %b} {pk.day}</td><td>{n} of {t} spots</td></tr>'
        for a, b, pk, n, t in upcoming)
    first = upcoming[0] if upcoming else None
    if first:
        lede_next = (f"The next statewide king tides are <b>{kingtides.span(first[0], first[1])}</b>, "
                     f"when {first[3]} of {total} spots have their highest tides of the year.")
    else:
        lede_next = "King tide dates here vary from spot to spot; find yours in the table below."
    spot_rows, months = [], set()
    for st, kt in sorted(rows, key=lambda r: r[0]["pretty"].lower()):
        nxt = [w for w in kt["windows"] if w[1] >= today][:3]
        if not nxt:
            continue
        a, b, pk, v = nxt[0]
        later = ", ".join(kingtides.span(x[0], x[1]) for x in nxt[1:])
        ms = [f"{a:%Y-%m}"]  # month of the next king tide window
        months.update(ms)
        spot_rows.append((a, st["pretty"].lower(),
            f'<tr data-n="{esc(st["pretty"].lower())}" data-d="{a.isoformat()}" data-h="{v:.2f}" '
            f'data-a="{v - kt["typical"]:.2f}" data-m="{" ".join(ms)}"><th scope="row"><a href="{BASE}{st["path"]}">{esc(st["pretty"])}</a></th>'
            f'<td><b>{kingtides.span(a, b)}</b>{f"<br><small>then {later}</small>" if later else ""}</td>'
            f'<td>{ft(v)} <small>{pk:%a %b} {pk.day}, {clock(pk)}<br>{ft(v - kt["typical"])} above a typical high</small></td></tr>'))
    biggest = sorted(rows, key=lambda r: -(r[1]["top"][1] - r[1]["typical"]))[:5]
    big_list = "".join(
        f'<li><a href="{BASE}{st["path"]}">{esc(st["pretty"])}</a>: {ft(kt["top"][1])} on {kt["top"][0]:%b} {kt["top"][0].day} '
        f'at {clock(kt["top"][0])}, {ft(kt["top"][1] - kt["typical"])} above a typical high</li>' for st, kt in biggest)
    progs = KT_PROGRAMS.get(code, [])
    prog_html = ("<p>Share your photos with " + " or ".join(
        f'<a href="{u}" rel="noopener">{esc(n)}</a> ({esc(d)})' for n, u, d in progs) + ".</p>") if progs else ""
    body = f"""
<article class="kt">
<h1>King tides in {esc(state)}, {season}</h1>
<p class="lede">King tides are the highest tides of the year. {lede_next} Dates, times and heights below come from NOAA
predictions for {total} spots in {esc(state)}, worked out for the next 12 months.</p>
<p class="tools"><a class="btn" href="{BASE}{path}king-tides.ics" download>{ico("cal")} Add {esc(state)} king tides to my calendar</a>
<a href="{BASE}king-tides/">King tides in every state</a></p>
<h2>{esc(state)} king tide dates</h2>
<div class="scroll"><table class="tides kt-wins"><thead><tr><th>Dates</th><th>Peak day</th><th>Spots at their highest that day</th></tr></thead>
<tbody>{win_rows}</tbody></table></div>
<p class="note">Big states can have more than one season: one stretch of coast may peak in fall while another peaks in winter. The table for your spot below is the one to trust.</p>
<h2>Biggest king tides in {esc(state)}</h2>
<p>The spots where the year's highest tide stands furthest above an ordinary high tide:</p>
<ol>{big_list}</ol>
<h2 id="spots">King tide times for your spot</h2>
{kt_tools(months, len(spot_rows))}
<div class="scroll kt-box" data-kt-box><table class="tides kt-spots"><thead><tr><th>Spot</th><th>Next king tides</th><th>Highest tide</th></tr></thead>
<tbody>{"".join(r for _, _, r in sorted(spot_rows))}</tbody></table></div>
<button type="button" class="kt-more" data-kt-more hidden>Show all {len(spot_rows)} spots</button>
<h2>{ico("camera")} Photograph the king tides</h2>
{tipcards(KT_PHOTO_TIPS, "photo")}
{prog_html}
<h2>{ico("warn")} Stay safe</h2>
{tipcards(KT_SAFETY_TIPS, "safe")}
<p class="tip">{ico("waves")} <a href="{BASE}gear/#beach">What to bring for king tides</a>: boots, a rain shell and a tripod.</p>
<h2>How these dates are worked out</h2>
<p>For every spot we take NOAA's high and low tide predictions for the next 12 months and find each day's highest tide.
The days in that spot's top 5% (about 18 days a year) are its king tide days, and days next to each other make one
window. A statewide window is a run of days when at least a quarter of the state's spots are in theirs. Heights are in
feet above mean lower low water (MLLW), the zero on tide charts. Predictions don't include weather. Not for navigation.</p>
</article>"""
    title = f"{state} King Tides {season}: Dates, Times & Heights"
    desc = (f"When are the king tides in {state}? " + (f"Next: {kingtides.span(first[0], first[1])}. " if first else "")
            + f"Dates, peak times and heights for {total} spots, plus a calendar and photo tips.")
    crumbs = [("Home", ""), ("King tides", "king-tides/"), (state, path)]
    return path, page(title, desc, path, body, crumbs=crumbs, scripts=("units.js", "site.js")), \
        kingtides.ics(state, wins, f"{SITE_URL}/{path}", built_at)


def kt_hub(by_state, today):
    """King tides in every state: what they are, when each coast gets them, and links to the state pages."""
    season = kingtides.season_label(today)
    blocks = []
    for label, codes in REGIONS:
        rows = []
        for c in codes.split():
            spots = by_state.get(c)
            if not spots:
                continue
            wins = [w for w in kingtides.state_windows([kt for _, kt in spots]) if w[1] >= today]
            later = ", ".join(kingtides.span(w[0], w[1]) for w in wins[1:3])
            nxt = kingtides.span(wins[0][0], wins[0][1]) if wins else "varies by spot"
            rows.append(f'<tr><th scope="row"><a href="{BASE}{kt_path(c)}">{esc(STATES.get(c, c))}</a></th>'
                        f'<td><b>{nxt}</b></td><td>{later or "—"}</td><td>{len(spots)}</td></tr>')
        if rows:
            blocks.append(f'<h3>{esc(label)}</h3><div class="scroll"><table class="tides kt-hub"><thead><tr><th>State</th>'
                          f'<th>Next king tides</th><th>Then</th><th>Spots</th></tr></thead>'
                          f'<tbody>{"".join(rows)}</tbody></table></div>')
    progs = []
    for c, lst in sorted(KT_PROGRAMS.items(), key=lambda x: STATES.get(x[0], x[0])):
        progs.append(f"<li><b>{esc(STATES.get(c, c))}:</b> " + "; ".join(
            f'<a href="{u}" rel="noopener">{esc(n)}</a>' for n, u, _ in lst) + "</li>")
    body = f"""
<article class="kt">
<h1>King tides {season}: dates for every US coast</h1>
<p class="lede">King tides are the highest tides of the year. They flood low streets, cover beaches and push water over sea
walls, and they show today what everyday high tides will look like as sea level rises. Pick your state for exact
dates, peak times and heights at every NOAA tide station.</p>
<div class="search"><input type="search" placeholder="Find your beach, pier or harbor" aria-label="Search spots" data-search autocomplete="off"><div class="results" data-results hidden></div></div>
<h2>When are the king tides?</h2>
{"".join(blocks)}
<h2>{ico("moon")} What makes a king tide</h2>
<p>"King tide" isn't a scientific term: it's the name for the few highest tides of the year, when three things stack up.</p>
{tipcards(KT_WHY, "why")}
<h2>{ico("cal")} When they come to your coast</h2>
{tipcards(KT_SEASONS, "coast")}
<p class="note">We work from each spot's own predictions, so the dates on every state page already match your stretch of coast.</p>
<h2>{ico("camera")} Photograph the king tides</h2>
{tipcards(KT_PHOTO_TIPS, "photo")}
<p>State and university projects collect these photos:</p>
<ul>{"".join(progs)}</ul>
<h2>{ico("warn")} Stay safe</h2>
{tipcards(KT_SAFETY_TIPS, "safe")}
<p class="tip">{ico("waves")} <a href="{BASE}gear/#beach">What to bring for king tides</a>: boots, a rain shell and a tripod.</p>
<p class="note">Dates come from NOAA tide predictions for the next 12 months: a spot's king tide days are its top 5% of
daily high tides. Predictions don't include wind, storms or rain. Not for navigation.</p>
</article>"""
    return page(f"King Tides {season}: Dates for Every US State",
                f"When are the king tides? Dates for the {season} king tides in every coastal state, with peak times and heights for each NOAA tide station.",
                "king-tides/", body, crumbs=[("Home", ""), ("King tides", "king-tides/")], scripts=("units.js", "site.js"))

# Famous tide pool spots: name, state, lat, lng. Each is matched to its nearest NOAA station with a year of predictions.
TP_SPOTS = [
    ("La Jolla tide pools", "CA", 32.8435, -117.2810), ("Cabrillo National Monument", "CA", 32.6680, -117.2450),
    ("Crystal Cove State Park", "CA", 33.5710, -117.8400), ("Laguna Beach tide pools", "CA", 33.5420, -117.7850),
    ("Point Fermin, San Pedro", "CA", 33.7050, -118.2900), ("Leo Carrillo State Park", "CA", 34.0450, -118.9350),
    ("Montaña de Oro", "CA", 35.2700, -120.8900), ("Shell Beach, Pismo", "CA", 35.1550, -120.6700),
    ("Point Lobos", "CA", 36.5200, -121.9500), ("Asilomar, Pacific Grove", "CA", 36.6200, -121.9400),
    ("Natural Bridges, Santa Cruz", "CA", 36.9500, -122.0600), ("Pigeon Point", "CA", 37.1820, -122.3940),
    ("Fitzgerald Marine Reserve", "CA", 37.5230, -122.5170), ("Duxbury Reef, Bolinas", "CA", 37.8900, -122.7000),
    ("Salt Point State Park", "CA", 38.5650, -123.3300), ("Trinidad State Beach", "CA", 41.0600, -124.1450),
    ("Harris Beach, Brookings", "OR", 42.0650, -124.3100), ("Cape Arago & Sunset Bay", "OR", 43.3050, -124.3900),
    ("Strawberry Hill", "OR", 44.2500, -124.1120), ("Cape Perpetua", "OR", 44.2800, -124.1100),
    ("Seal Rock", "OR", 44.4970, -124.0830), ("Yaquina Head", "OR", 44.6770, -124.0780),
    ("Otter Rock (Devil's Punchbowl)", "OR", 44.7530, -124.0650), ("Haystack Rock, Cannon Beach", "OR", 45.8840, -123.9680),
    ("Kalaloch (Beach 4)", "WA", 47.5700, -124.3700), ("Second Beach, La Push", "WA", 47.8900, -124.6200),
    ("Rialto Beach (Hole-in-the-Wall)", "WA", 47.9300, -124.6500), ("Shi Shi Beach & Point of the Arches", "WA", 48.2700, -124.6900),
    ("Salt Creek Recreation Area", "WA", 48.1650, -123.7000), ("Rosario Beach, Deception Pass", "WA", 48.4170, -122.6650),
    ("Alki Beach, Seattle", "WA", 47.5800, -122.4100), ("Lincoln Park, Seattle", "WA", 47.5300, -122.3950),
    ("Bishop's Beach, Homer", "AK", 59.6400, -151.5500), ("Shark's Cove, Oʻahu", "HI", 21.6500, -158.0620),
    ("Makapuʻu tide pools, Oʻahu", "HI", 21.3100, -157.6600), ("Ship Harbor, Acadia", "ME", 44.2300, -68.3230),
    ("Wonderland, Acadia", "ME", 44.2350, -68.3150), ("Pemaquid Point", "ME", 43.8370, -69.5080),
    ("Two Lights, Cape Elizabeth", "ME", 43.5650, -70.2000), ("Odiorne Point, Rye", "NH", 43.0400, -70.7150),
    ("Halibut Point, Rockport", "MA", 42.6900, -70.6300), ("Nahant", "MA", 42.4200, -70.9100),
    ("Beavertail, Jamestown", "RI", 41.4500, -71.4000), ("Brenton Point, Newport", "RI", 41.4500, -71.3600),
    ("Coral Cove Park, Jupiter", "FL", 26.9800, -80.0700),
]
TP_TIPS = [
    ("clock", "Go before the low", "Arrive about an hour before low tide and head back as soon as the water turns."),
    ("waves", "Watch the waves", "Sneaker waves run far up rocky shores, especially on the Pacific. Never turn your back on the ocean."),
    ("walk", "Step on bare rock", "Seaweed and barnacles are slippery and alive. Wear shoes with grip and step on bare rock or sand."),
    ("pool", "Look, don't take", "Touch gently with a wet finger, put rocks back as you found them, and leave animals and shells. Many tide pools are protected."),
]


def tp_path(code):
    return f"tide-pools/{slugify(STATES.get(code, code))}/"


def tp_upcoming(tp, today, n=3):
    return [r for r in lowtides.runs(tp["good"]) if r[1].date() >= today][:n]


def tp_when(w):
    """'morning' / 'midday' / 'afternoon' for a low tide time."""
    return "morning" if w.hour < 11 else "midday" if w.hour < 14 else "afternoon"


def tp_months(rows, today):
    """[(YYYY-MM, average tide pool days per spot)] for the next 12 months."""
    keys = [f"{(today.replace(day=1) + dt.timedelta(days=32 * i)):%Y-%m}" for i in range(12)]
    keys = list(dict.fromkeys(keys))[:12]
    return [(k, sum(tp["months"].get(k, 0) for _, tp in rows) / len(rows)) for k in keys]


def tp_best_months(months):
    """'June to August': the three months in a row with the most tide pool days (months: next 12, in order)."""
    i = max(range(len(months) - 2), key=lambda j: sum(v for _, v in months[j:j + 3]))
    name = lambda k: dt.date.fromisoformat(k + "-01").strftime("%B")
    return f"{name(months[i][0])} to {name(months[i + 2][0])}"


def tp_station_line(st, tp, today):
    nxt = tp_upcoming(tp, today, 3)
    if not nxt:
        return ""
    a, b, (lw, lv) = nxt[0]
    state = STATES.get(st["state"], st["state"])
    later = ", ".join(kingtides.span(x[0].date(), x[1].date()) for x in nxt[1:])
    return (f'<p class="tip">{ico("pool")} <b>Best tide pool days here:</b> {kingtides.span(a.date(), b.date())}, lowest {ft(lv)} '
            f'on {lw:%a %b} {lw.day} at {clock(lw)}{f"; then {later}" if later else ""}. '
            f'<a href="{BASE}{tp_path(st["state"])}">Tide pooling in {esc(state)}</a></p>')


def tp_spot_rows(spots, today, show_state=False):
    """Table rows for famous spots: [(sortkey, html)]."""
    out = []
    for name, code, st, tp, d in spots:
        nxt = tp_upcoming(tp, today, 3)
        if not nxt:
            continue
        a, b, (lw, lv) = nxt[0]
        later = ", ".join(kingtides.span(x[0].date(), x[1].date()) for x in nxt[1:])
        out.append((name, f'<tr><th scope="row">{esc(name)}{f" <small>{code}</small>" if show_state else ""}<br><small>Tides: '
                          f'<a href="{BASE}{st["path"]}">{esc(st["pretty"])}</a>{f", {d:.0f} mi" if d >= 1 else ""}</small></th>'
                          f'<td><b>{kingtides.span(a.date(), b.date())}</b>{f"<br><small>then {later}</small>" if later else ""}</td>'
                          f'<td>{ft(lv)} <small>{lw:%a %b} {lw.day}, {clock(lw)}</small></td></tr>'))
    return [h for _, h in out]


def tp_month_bars(months):
    top = max(v for _, v in months) or 1
    return '<div class="tp-bars">' + "".join(
        f'<div class="tp-bar"><span>{dt.date.fromisoformat(k + "-01"):%b}</span><i style="width:{v / top * 100:.0f}%"></i>'
        f'<b>{v:.1f}</b></div>' for k, v in months) + "</div>"


def tp_state_page(code, rows, spots, today):
    """Tide pooling in one state: when the best daylight lows come, the famous spots, then every spot's next ones."""
    state = STATES.get(code, code)
    path = tp_path(code)
    months = tp_months(rows, today)
    best = tp_best_months(months)
    wins = [w for w in kingtides.state_windows([{"days": {w.date() for w, _ in tp["good"]}} for _, tp in rows]) if w[1] >= today]
    win_rows = "".join(f'<tr><td><b>{kingtides.span(a, b)}</b></td><td>{pk:%a %b} {pk.day}</td><td>{n} of {t} spots</td></tr>'
                       for a, b, pk, n, t in wins[:8])
    first = wins[0] if wins else None
    lede_next = (f"The next stretch of tide pool lows across the state is <b>{kingtides.span(first[0], first[1])}</b>."
                 if first else "")
    spot_rows, mset = [], set()
    for st, tp in sorted(rows, key=lambda r: r[0]["pretty"].lower()):
        nxt = tp_upcoming(tp, today, 3)
        if not nxt:
            continue
        a, b, (lw, lv) = nxt[0]
        later = ", ".join(kingtides.span(x[0].date(), x[1].date()) for x in nxt[1:])
        soon = sum(1 for w, _ in tp["good"] if today <= w.date() < today + dt.timedelta(days=90))
        mset.add(f"{a:%Y-%m}")
        spot_rows.append((a.date(), st["pretty"].lower(),
            f'<tr data-n="{esc(st["pretty"].lower())}" data-d="{a.date().isoformat()}" data-h="{-lv:.2f}" data-a="{soon}" '
            f'data-m="{a:%Y-%m}"><th scope="row"><a href="{BASE}{st["path"]}">{esc(st["pretty"])}</a></th>'
            f'<td><b>{kingtides.span(a.date(), b.date())}</b> <small>{tp_when(lw)}{"s" if b.date() > a.date() else ""}</small>{f"<br><small>then {later}</small>" if later else ""}</td>'
            f'<td>{ft(lv)} <small>{lw:%a %b} {lw.day}, {clock(lw)}<br>{soon} good day{"s" if soon != 1 else ""} in the next 3 months</small></td></tr>'))
    famous = tp_spot_rows([s for s in spots if s[1] == code], today)
    famous_html = (f'<h2>{ico("star")} Favorite tide pools in {esc(state)}</h2><div class="scroll"><table class="tides kt-wins">'
                   f'<thead><tr><th>Tide pools</th><th>Next good low tides</th><th>Lowest</th></tr></thead><tbody>{"".join(famous)}</tbody></table></div>'
                   ) if famous else ""
    body = f"""
<article class="kt">
<h1>Tide pooling in {esc(state)}: best low tides</h1>
<p class="lede">The best tide pool days are low tides that are among a spot's lowest of the year and fall in daylight. In
{esc(state)} they come mostly in <b>{best}</b>. {lede_next} Dates, times and heights below come from NOAA predictions for
{len(rows)} spots, worked out for the next 12 months.</p>
<p class="tools"><a href="{BASE}tide-pools/">Tide pools in every state</a> · <a href="{BASE}{kt_path(code)}">{esc(state)} king tides</a></p>
<h2>{ico("cal")} Tide pool season in {esc(state)}</h2>
<p>Average number of good tide pool days per spot, month by month:</p>
{tp_month_bars(months)}
{f'<h2>Best tide pool days statewide</h2><div class="scroll"><table class="tides kt-wins"><thead><tr><th>Dates</th><th>Best day</th><th>Spots with a good low that day</th></tr></thead><tbody>{win_rows}</tbody></table></div>' if win_rows else ""}
{famous_html}
<h2 id="spots">Tide pool lows for your spot</h2>
{kt_tools(mset, len(spot_rows), "Next good low", (("d", "Soonest first"), ("h", "Lowest tide"), ("a", "Most days in 3 months"), ("n", "A to Z")))}
<div class="scroll kt-box" data-kt-box><table class="tides kt-spots"><thead><tr><th>Spot</th><th>Next tide pool lows</th><th>Lowest</th></tr></thead>
<tbody>{"".join(r for _, _, r in sorted(spot_rows))}</tbody></table></div>
<button type="button" class="kt-more" data-kt-more hidden>Show all {len(spot_rows)} spots</button>
<h2>{ico("warn")} Tide pool tips</h2>
{tipcards(TP_TIPS, "safe")}
<p class="tip">{ico("walk")} <a href="{BASE}gear/#tidepools">What to bring for tide pooling</a>: grippy water shoes, a field guide, a headlamp.</p>
<h2>How these dates are worked out</h2>
<p>For every spot we take NOAA's low tide predictions for the next 12 months. A low counts as a tide pool low when it's in
that spot's lowest 10% and comes between an hour after sunrise and sunset, so there's light for the hour before it. Heights are feet above mean lower low water (MLLW), the zero on
tide charts; below zero is a minus tide. Wind and swell can keep the water higher than predicted. Not for navigation.</p>
</article>"""
    title = f"Tide Pooling in {state}: Best Low Tides {kingtides.season_label(today)}"
    desc = (f"When are the best tide pool days in {state}? Mostly {best}. " +
            (f"Next: {kingtides.span(first[0], first[1])}. " if first else "") +
            f"Daylight low tide dates, times and heights for {len(rows)} spots.")
    return path, page(title, desc, path, body, crumbs=[("Home", ""), ("Tide pools", "tide-pools/"), (state, path)],
                      scripts=("units.js", "site.js"))


def tp_hub(by_state, spots, today):
    blocks = []
    for label, codes in REGIONS:
        rows = []
        for c in codes.split():
            r = by_state.get(c)
            if not r:
                continue
            rows.append(f'<tr><th scope="row"><a href="{BASE}{tp_path(c)}">{esc(STATES.get(c, c))}</a></th>'
                        f'<td>{tp_best_months(tp_months(r, today))}</td><td>{len(r)}</td></tr>')
        if rows:
            blocks.append(f'<h3>{esc(label)}</h3><div class="scroll"><table class="tides kt-hub"><thead><tr><th>State</th>'
                          f'<th>Best months</th><th>Spots</th></tr></thead><tbody>{"".join(rows)}</tbody></table></div>')
    famous = tp_spot_rows(spots, today, show_state=True)
    body = f"""
<article class="kt">
<h1>Tide pools: the best low tides near you</h1>
<p class="lede">Tide pooling is best on the lowest daylight tides of the year, when sea stars, anemones, crabs and
nudibranchs are left in pools on uncovered rock. Here's when those tides come at well-known tide pools, and in every
coastal state, from NOAA predictions for the next 12 months.</p>
<div class="search"><input type="search" placeholder="Find your beach, pier or harbor" aria-label="Search spots" data-search autocomplete="off"><div class="results" data-results hidden></div></div>
<h2>{ico("star")} Famous tide pools: next good low tides</h2>
<div class="scroll"><table class="tides kt-wins"><thead><tr><th>Tide pools</th><th>Next good low tides</th><th>Lowest</th></tr></thead>
<tbody>{"".join(famous)}</tbody></table></div>
<h2>{ico("cal")} When is tide pool season?</h2>
<p>It depends on the coast: the lowest daylight tides come in different months, and at different times of day, around the country.</p>
{"".join(blocks)}
<h2>{ico("warn")} Tide pool tips</h2>
{tipcards(TP_TIPS, "safe")}
<p class="tip">{ico("walk")} <a href="{BASE}gear/#tidepools">What to bring for tide pooling</a>: grippy water shoes, a field guide, a headlamp.</p>
<p class="note">A low counts as a tide pool low when it's in that spot's lowest 10% for the next 12 months and comes between
an hour after sunrise and sunset. Each spot's own page lists every low tide. Not for navigation.</p>
</article>"""
    return page(f"Tide Pools Near Me: Best Low Tides {kingtides.season_label(today)}",
                "The best low tides for tide pooling at famous tide pools and in every coastal state: dates, times and heights from NOAA predictions.",
                "tide-pools/", body, crumbs=[("Home", ""), ("Tide pools", "tide-pools/")], scripts=("units.js", "site.js"))


# Razor clam beaches. Facts from WDFW and ODFW pages, checked Oct 2026.
CLAM_BEACHES = [  # name, state, open-coast NOAA station id (not the nearer bay and slough stations), boundaries
    ("Long Beach", "WA", "9440574", "From the Columbia River north to the mouth of Willapa Bay."),
    ("Twin Harbors", "WA", "9441102", "From Willapa Bay north to the south jetty at the mouth of Grays Harbor."),
    ("Copalis", "WA", "9441156", "From the north jetty at Grays Harbor to the Copalis River."),
    ("Mocrocks", "WA", "9441627", "From the Copalis River to the Quinault Indian Reservation."),
    ("Kalaloch", "WA", "9442396", "From the South Beach campground north to Olympic National Park Beach Trail 3. Closed for the 2026–27 season "
                                         "because of low clam numbers (WDFW)."),
    ("Clatsop beaches", "OR", "9440574", "From the Columbia River south past Gearhart and Seaside to Tillamook Head: about 95% of Oregon's razor clamming."),
]
CLAM_RULES = {
    "WA": ('<a href="https://wdfw.wa.gov/fishing/shellfish/razorclams/seasons_set.html" rel="noopener">WDFW razor clam seasons</a>',
           "Washington digs only on days WDFW opens, after state marine toxin tests come back clean, usually a week or less before each "
           "series. Openings get postponed when domoic acid is high. You need a Washington razor clam license."),
    "OR": ('<a href="https://myodfw.com/recreation-report" rel="noopener">ODFW Recreation Report</a> and the '
           '<a href="https://www.oregon.gov/oda/programs/foodsafety/shellfish/pages/shellfishclosures.aspx" rel="noopener">ODA shellfish safety page</a> '
           '(hotline 800-448-2474)',
           "Oregon needs a shellfish license. The limit is the first 15 clams dug, whatever their size or condition. North of "
           "Tillamook Head, razor clamming is closed July 15 to September 30 every year to protect young clams; biotoxin closures "
           "can come at any time."),
}
CLAM_TIPS = [
    ("clock", "Start before the low", "Most clams are dug in the hour or two before low tide, as the water drops."),
    ("waves", "Look for shows", "A dimple or hole in wet sand near the surf line marks a clam. Dig fast and on the ocean side."),
    ("low", "Lower is better", "The lower the tide, the more beach is uncovered. Minus tides are best; swell can spoil a good tide."),
    ("warn", "Never eat from a closed beach", "Domoic acid and PSP toxins can't be cooked out. Only dig when the state says the beach is open."),
]
CLAM_CUT = 0.5  # lows at or below this many feet (MLLW) count as clam tides


def clam_tides(raws, tz, code, today, days=150):
    """Low tides good for razor clams over the next `days`: [(datetime, height)].

    Washington's good tides are in the afternoon and evening from October to mid-March and in the morning after (WDFW).
    Oregon has no time rule, but north of Tillamook Head is closed July 15 to September 30."""
    end = today + dt.timedelta(days=days)
    out = []
    for year, raw in raws.items():
        for t, v, k in raw:
            if k != "L" or v > CLAM_CUT:
                continue
            try:
                w = dt.datetime.strptime(f"{year}-{t}", "%Y-%m-%d %H:%M").replace(tzinfo=tz)
            except ValueError:
                continue
            d = w.date()
            if not today <= d < end:
                continue
            if code == "WA":
                pm_season = d.month >= 10 or d.month <= 2 or (d.month == 3 and d.day <= 15)
                if (w.hour >= 12) != pm_season or 6 <= d.month <= 9:
                    continue
            out.append((w, v))
    return sorted(out)


def clam_page(beaches, today):
    """Razor clam tides for Washington and Oregon beaches."""
    sections = []
    for code, label in (("WA", "Washington"), ("OR", "Oregon")):
        rows = [b for b in beaches if b[1] == code]
        if not rows:
            continue
        where, rule = CLAM_RULES[code]
        parts = [f'<h2 id="{code.lower()}">{ico("waves")} {label}</h2><p class="tip">{ico("warn")} <b>Check before you go:</b> {where}. {rule}</p>']
        for name, _, note, st, tz, tides in rows:
            closed = lambda w: code == "OR" and name.startswith("Clatsop") and (dt.date(w.year, 7, 15) <= w.date() <= dt.date(w.year, 9, 30))
            tides = [x for x in tides if not closed(x[0])]
            trs = "".join(
                f'<tr><th scope="row">{w:%a %b} {w.day}</th><td><b>{clock(w)}</b></td><td>{ft(v)}</td>'
                f'<td>{clock(w - dt.timedelta(hours=2))}–{clock(w)}</td></tr>' for w, v in tides[:16])
            parts.append(
                f'<h3>{esc(name)}</h3><p>{esc(note)} Times from the open-coast <a href="{BASE}{st["path"]}">{esc(st["pretty"])}</a> station.</p>'
                + (f'<div class="scroll"><table class="tides kt-wins"><thead><tr><th>Day</th><th>Low tide</th><th>Height</th><th>Best digging</th></tr></thead>'
                   f'<tbody>{trs}</tbody></table></div>' if trs else "<p>No clam tides in the next few months.</p>"))
        sections.append("".join(parts))
    body = f"""
<article class="kt">
<h1>Razor clam tides: Washington and Oregon</h1>
<p class="lede">Razor clams are dug on the lowest tides, in the hour or two before low water. Here are the coming clam tides
(low tides at or below {ft(CLAM_CUT)}) for each razor clam beach, from NOAA predictions. In Washington they're the afternoon and
evening lows from October to mid-March and the morning lows after that, the tides WDFW picks its digs from.</p>
<p class="tip">{ico("warn")} <b>These are tides, not openings.</b> A beach is only open when the state says so, and openings are
cancelled when marine toxins are high. Always check the official links for your state below before you go.</p>
<p class="tools"><a href="#wa">Washington beaches</a> · <a href="#or">Oregon beaches</a> · <a href="{BASE}tides/washington/">Washington tides</a> · <a href="{BASE}tides/oregon/">Oregon tides</a></p>
{"".join(sections)}
<h2>{ico("pool")} Razor clam tips</h2>
{tipcards(CLAM_TIPS, "safe")}
<p class="note">Times are local. Heights are feet above mean lower low water (MLLW); below zero is a minus tide. Predictions don't
include swell or wind, which can keep the water higher. Season details come from WDFW and ODFW and can change; their pages are the
final word. Not for navigation.</p>
</article>"""
    return page(f"Razor Clam Tides {kingtides.season_label(today)}: Washington & Oregon Digging Times",
                "Razor clam digging tides for Long Beach, Twin Harbors, Copalis, Mocrocks and Oregon's Clatsop beaches: low tide times, "
                "heights and the best hours to dig, with links to WDFW and ODFW openings.",
                "razor-clams/", body, crumbs=[("Home", ""), ("Razor clams", "razor-clams/")], scripts=("units.js", "site.js"))


EMBED_JS = """(() => {
  const d = JSON.parse(document.getElementById("d").textContent), ev = d.ev, now = Date.now() / 1000;
  const fmt = (t) => new Date(t * 1000).toLocaleTimeString([], { hour: "numeric", minute: "2-digit", timeZone: d.tz });
  const day = (t) => new Date(t * 1000).toLocaleDateString([], { weekday: "short", timeZone: d.tz });
  const h = (t) => { for (let i = 0; i + 1 < ev.length; i++) { const [a, x] = ev[i], [b, y] = ev[i + 1];
    if (a <= t && t <= b) return x + (y - x) * (1 - Math.cos(Math.PI * (t - a) / (b - a))) / 2; } return null; };
  const v = h(now), nx = ev.find((e) => e[0] > now);
  if (v !== null && nx) document.getElementById("now").innerHTML = `Now <b>${v.toFixed(1)} ft</b>, ${nx[2] === "H" ? "rising" : "falling"}`;
  const t0 = now - 6 * 3600, t1 = now + 18 * 3600, W = 300, H = 70, pts = [];
  for (let t = t0; t <= t1; t += 900) { const y = h(t); if (y !== null) pts.push([t, y]); }
  if (pts.length > 2) {
    const lo = Math.min(...pts.map((p) => p[1])), hi = Math.max(...pts.map((p) => p[1])), sp = hi - lo || 1;
    const X = (t) => (t - t0) / (t1 - t0) * W, Y = (y) => H - 6 - (y - lo) / sp * (H - 14);
    const line = pts.map(([t, y]) => `${X(t).toFixed(1)},${Y(y).toFixed(1)}`).join(" L");
    document.getElementById("c").innerHTML = `<path class="f" d="M0,${H} L${line} L${W},${H} Z"/><path class="l" d="M${line}"/>` +
      `<line class="n" x1="${X(now)}" x2="${X(now)}" y1="0" y2="${H}"/><circle class="p" cx="${X(now)}" cy="${Y(v ?? lo)}" r="4"/>`;
  }
  document.getElementById("list").innerHTML = ev.filter((e) => e[0] > now).slice(0, 4).map(([t, y, k]) =>
    `<li class="${k}"><b>${k === "H" ? "High" : "Low"}</b> ${day(t)} ${fmt(t)} <i>${y.toFixed(1)} ft</i></li>`).join("");
})();"""


def embed_page(st, events, tz):
    """Tiny tide card other sites can put in an iframe. Not indexed; the embed code carries a normal link to us."""
    now = dt.datetime.now(dt.timezone.utc).timestamp()
    ev = [[int(t), v, k] for t, v, k in events if now - 86400 <= t <= now + 9 * 86400]
    if isinstance(tz, ZoneInfo):
        tzname = tz.key
    else:  # fixed offset: IANA's Etc/GMT zones have the sign flipped
        hours = int(tz.utcoffset(None).total_seconds() // 3600)
        tzname = f"Etc/GMT{-hours:+d}" if hours else "UTC"
    data = json.dumps({"ev": ev, "tz": tzname}, separators=(",", ":"))
    name = esc(st["pretty"])
    return f"""<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<meta name="robots" content="noindex"><title>{name} tides</title><style>
:root {{ --bg:#fff; --ink:#11232c; --mut:#536a75; --sea:#0b5c7a; --sea2:#1689ad; --foam:#d9f1f8; --low:#b5651d; --line:#d6e3e9; }}
@media (prefers-color-scheme: dark) {{ :root:not(.light) {{ --bg:#122028; --ink:#e5f0f4; --mut:#9db3bd; --sea:#6cc7e3; --sea2:#3aa8cc; --foam:#12313d; --low:#f0a35e; --line:#24363f; }} }}
:root.dark {{ --bg:#122028; --ink:#e5f0f4; --mut:#9db3bd; --sea:#6cc7e3; --sea2:#3aa8cc; --foam:#12313d; --low:#f0a35e; --line:#24363f; }}
body {{ margin:0; font:14px/1.4 system-ui,-apple-system,Segoe UI,sans-serif; background:var(--bg); color:var(--ink); }}
.w {{ padding:12px 14px; border:1px solid var(--line); border-radius:12px; }}
h1 {{ font-size:15px; margin:0; }} #now {{ color:var(--mut); margin:2px 0 6px; }} #now b {{ color:var(--ink); }}
svg {{ width:100%; height:70px; display:block; }} .f {{ fill:var(--foam); }} .l {{ fill:none; stroke:var(--sea2); stroke-width:2; }}
.n {{ stroke:#d6336c; stroke-dasharray:3 3; }} .p {{ fill:#d6336c; }}
ul {{ list-style:none; padding:0; margin:8px 0 6px; font-size:13px; }} li {{ display:flex; gap:8px; }} li b {{ width:36px; }} li i {{ margin-left:auto; }}
li b {{ color:var(--sea); }} li.L b {{ color:var(--low); }} li i {{ color:var(--mut); font-style:normal; }}
a {{ color:var(--sea); font-size:12px; text-decoration:none; }} a:hover {{ text-decoration:underline; }}
</style><script>if(/[?&]theme=dark/.test(location.search))document.documentElement.className="dark";if(/[?&]theme=light/.test(location.search))document.documentElement.className="light";</script></head>
<body><div class="w"><h1>{name} tides</h1><p id="now">Tide predictions from NOAA</p>
<svg id="c" viewBox="0 0 300 70" preserveAspectRatio="none" aria-hidden="true"></svg><ul id="list"></ul>
<a href="{SITE_URL}/{st["path"]}" target="_blank" rel="noopener">Full tide chart and fishing forecast · Shorebite</a></div>
<script type="application/json" id="d">{data}</script><script>{EMBED_JS}</script></body></html>"""


def embed_code(st):
    name = esc(st["pretty"])
    return (f'<iframe src="{SITE_URL}/embed/{st["id"]}/" title="{name} tides" width="340" height="270" '
            f'style="border:0;max-width:100%" loading="lazy"></iframe>\n'
            f'<p style="font-size:12px;margin:4px 0"><a href="{SITE_URL}/{st["path"]}">{name} tide chart</a> by Shorebite</p>')


PLACE_KINDS = [("beach", "beach", "Beaches"), ("ramp", "ramp", "Boat ramps"), ("marina", "anchor", "Marinas"),
               ("pier", "pier", "Fishing piers and docks")]


def places_section(name, places, heading=None):
    """Beaches, boat ramps, marinas and piers within a few miles (OpenStreetMap)."""
    if not places:
        return ""
    cols = []
    for kind, icon, label in PLACE_KINDS:
        items = [p for p in places if p[0] == kind]
        if not items:
            continue
        lis = "".join(f'<li><a href="https://www.google.com/maps/search/?api=1&amp;query={la},{lo}" rel="nofollow noopener" target="_blank">'
                      f'{esc(n) if n else ("Boat ramp" if kind == "ramp" else "Fishing spot" if kind == "pier" else label[:-1])}</a> <span>{d:.1f} mi</span></li>'
                      for kind_, n, la, lo, d in items)
        cols.append(f'<div class="pl-col"><h3>{ico(icon)}{label}</h3><ul>{lis}</ul></div>')
    if not cols:
        return ""
    return (f'<section class="card around" id="around"><h2>{ico("pin")}{heading or f"Around {esc(name)}"}</h2>'
            f'<div class="pl-cols">{"".join(cols)}</div><p class="note">Distances from the tide station. Places from '
            f'<a href="https://www.openstreetmap.org/copyright">© OpenStreetMap contributors</a>; links open in Google Maps.</p></section>')


TOWN_COAST_MILES = 5  # towns further than this from any tide station are inland: no page unless listed
TOWN_WATER_MILES = 2  # a town this close to a station is on the water: always its own page
TOWN_WATER = re.compile(r"Beach|Island|Isle|Harbou?r|Haven|Port\b|Bay\b|Shores?\b|Point\b|Cove\b|Inlet|Key\b|Cape\b|Ocean|Sea\b|Pier", re.I)
# GeoNames "places" that aren't towns anyone looks up tides for.
TOWN_JUNK = re.compile(r"Healthcare|Hospital|Medical|Campus|Airport|\bMall\b|Correctional|Prison|Naval Academy|Downs Station|Kodiak Station")


def town_path(name, st):
    return f"tides-near/{slugify(name)}-{st.lower()}/"


def town_page(town, near, nearby_towns, aka=(), region=False):
    """'Tides near <town>': today's tides at the closest NOAA stations, which is what people searching a town want.

    aka: other names people search for it (OCMD, St. Pete). region: an island, bay or stretch of coast, so cards
    show each station's town rather than a distance from the middle of it."""
    tname, tst = town[0], town[1]
    also = f" ({aka[0]})" if aka else ""
    state = STATES.get(tst, tst)
    cards, station_highs = [], []
    for d, (s, tz, events, today) in near:
        a = dt.datetime.combine(today, dt.time(0), tz).timestamp()
        evs = [(dt.datetime.fromtimestamp(t, tz), v, k) for t, v, k in events if a <= t < a + 86400]
        station_highs.append([(t, v) for t, v, k in events if k == "H" and a - 21600 <= t < a + 108000])
        times = "".join(f'<li class="{k}"><b title="{"High" if k == "H" else "Low"}">{"▲" if k == "H" else "▼"}</b> {clock(w)} <i>{ft(v)}</i></li>'
                        for w, v, k in evs)
        cards.append(f'<a class="spot" href="{BASE}{s["path"]}"><span class="spot-name">{esc(s["pretty"])}'
                     f'<small>{(esc(s["town"][0]) if s.get("town") else "") if region else f"{d:.1f} miles from {esc(tname)}"}</small></span>{spark(events, a, a + 86400)}<ul>{times}</ul></a>')
    first_d, (first, ftz, _, ftoday) = near[0]
    facts = [] if region else [f"The closest NOAA tide station to {esc(tname)} is <a href=\"{BASE}{first['path']}\">{esc(first['pretty'])}</a>, "
                               f"{first_d:.1f} miles away."]
    # Compare the same high tide everywhere: the closest station's first high today, and each other station's
    # high nearest to it (within 5 hours, so it's the same tide arriving, not the next one).
    a0 = dt.datetime.combine(ftoday, dt.time(0), ftz).timestamp()
    ref = next(((t, v) for t, v in station_highs[0] if t >= a0), None)
    same = []
    if ref:
        for hs in station_highs:
            m = min(hs, key=lambda tv: abs(tv[0] - ref[0]), default=None)
            if m and abs(m[0] - ref[0]) <= 5 * 3600:
                same.append(m)
    if len(same) >= 2:
        spread = round((max(t for t, _ in same) - min(t for t, _ in same)) / 60)
        lo, hi = min(v for _, v in same), max(v for _, v in same)
        if spread >= 20 or hi - lo >= 1:
            facts.append(f"The same high tide reaches these stations up to {spread // 60} h {spread % 60} min apart"
                         if spread >= 60 else f"The same high tide reaches these stations up to {spread} minutes apart")
            facts[-1] += f", and peaks anywhere from {ft(lo)} to {ft(hi)}, so use the station closest to where you'll be."
        else:
            facts.append(f"These stations are within {max(spread, 1)} minutes and {ft(hi - lo)} of each other, so any of them works for {esc(tname)}.")
    links = "".join(f'<li><a href="{BASE}{p}">{esc(n)}</a> <span>{d:.0f} mi</span></li>' for d, n, p in nearby_towns)
    cta = (f'<p class="cta-box">{ico("mail")} <span>Get <a href="{BASE}{first["path"]}#emails">{esc(first["pretty"])} tides by email</a> '
           f'every Thursday, with a heads-up before the best low tides and when warnings are issued.</span></p>') if ALERTS_API else ""
    body = f"""
<h1>Tides {"around" if region else "near"} {esc(tname)}{esc(also)}, {esc(state)}</h1>
<p class="lede">High and low tides today, {day_label(ftoday)}, at {f"{len(near)} NOAA tide stations around {esc(tname)}" if region else f"the {len(near)} NOAA tide station{'s' if len(near) != 1 else ''} closest to {esc(tname)}"}{f" (also called {esc(' or '.join(aka))})" if aka else ""}.
Tap a station for its full chart, the week ahead, currents, an hourly fishing forecast and the marine forecast.</p>
<div class="spots">{"".join(cards)}</div>
<p>{" ".join(facts)}</p>
{cta}
{"" if region else places_section(tname, first.get("_places"), f"Beaches, ramps and marinas near {esc(tname)}")}
{f'<h2>Nearby towns</h2><ul class="near">{links}</ul>' if links else ""}
<p><a href="{BASE}tides/{slugify(state)}/">All {esc(state)} tide stations</a></p>
"""
    path = town_path(tname, tst)
    crumbs = [("Home", ""), (state, f"tides/{slugify(state)}/"), (f"Tides {'around' if region else 'near'} {tname}", path)]
    return path, page(f"{tname}{also}, {tst} Tide Chart & Tide Times Today",
                      f"High and low tide times today for {tname}{also}, {state}, from the closest NOAA tide stations, with charts, "
                      f"currents, an hourly fishing forecast and the marine forecast.", path, body, crumbs=crumbs, scripts=("units.js",))


def state_page(code, stations, towns=(), kings=False, pools=False):
    state = STATES.get(code, code)
    refs = sum(1 for s in stations if s["type"] == "R")
    lis = []
    for s in sorted(stations, key=lambda s: s["pretty"].lower()):
        tz = zone_for(s)
        b = (s.get("_bite") or {}).get(dt.datetime.now(tz).date())
        badge = f' <b class="sb b{bite_band(b[0])}" title="Fishing today: {bite_label(b[0])}">{b[0]}</b>' if b else ""
        lis.append(f'<li data-n="{esc(s["pretty"].lower())}" data-k="{"ref" if s["type"] == "R" else ""}" '
                   f'data-b="{b[0] if b else -1}" data-ll="{s["lat"]:.4f},{s["lng"]:.4f}"><a href="{BASE}{s["path"]}">{esc(s["pretty"])}</a>'
                   f'{" <span class=tag>reference</span>" if s["type"] == "R" else ""}{badge}</li>')
    items = "".join(lis)
    town_list = ("<h2>Tides by town</h2><ul class='towns'>" + "".join(
        f'<li><a href="{BASE}{p}">{esc(n)}</a></li>' for n, p in sorted(towns)) + "</ul>") if towns else ""
    body = f"""
<h1>{esc(state)} tide charts</h1>
<p class="lede">Tide times and charts for {len(stations)} NOAA tide stations in {esc(state)}. {refs} are reference
stations with their own long-term measurements; the rest are calculated from the nearest reference station.</p>
{list_tools(len(stations), refs)}
{f'<p class="tip">{ico("mail")} Open any spot to see its tides, and to get them free by email every Thursday.</p>' if ALERTS_API else ""}
{f'<p class="tip">{ico("cal")} <a href="{BASE}{kt_path(code)}">King tide dates for {esc(state)}</a>: when the year\'s highest tides arrive at every spot.</p>' if kings else ""}
{f'<p class="tip">{ico("waves")} <a href="{BASE}razor-clams/#{code.lower()}">Razor clam tides</a> for {esc(state)}\'s clam beaches.</p>' if code in ("WA", "OR") else ""}
{f'<p class="tip">{ico("pool")} <a href="{BASE}{tp_path(code)}">Best tide pool days in {esc(state)}</a>: the lowest daylight tides at every spot.</p>' if pools else ""}
<ul class="stations">{items}</ul>
{town_list}"""
    path = f"tides/{slugify(state)}/"
    return path, page(f"{state} Tide Charts & Tide Times ({len(stations)} stations)",
                      f"High and low tide times, tide charts and tide tables for {len(stations)} places in {state}, from NOAA.",
                      path, body, crumbs=[("Home", ""), (state, path)], scripts=("site.js",))


def fishing_page(groups):
    rows = []
    for label, codes in REGIONS:
        blocks = []
        for c in codes.split():
            cand = []
            for st in groups.get(c, []):
                tz = zone_for(st)
                today = dt.datetime.now(tz).date()
                b = (st.get("_bite") or {}).get(today)
                if b:
                    cand.append((b[0], st, tz, today))
            if not cand:
                continue
            cand.sort(key=lambda x: -x[0])
            name = STATES.get(c, c)
            blocks.append(f'<div class="fish-state"><h3><a href="{BASE}tides/{slugify(name)}/">{esc(name)}</a></h3><ol>' + "".join(
                f'<li><a href="{BASE}{st["path"]}#bite">{esc(st["pretty"])}</a> {bite_line(st, tz, today)}</li>'
                for _, st, tz, today in cand[:5]) + "</ol></div>")
        if blocks:
            rows.append(f'<h2>{esc(label)}</h2><div class="fish-states">{"".join(blocks)}</div>')
    body = f"""
<h1>Fishing forecast: best times to fish today</h1>
<p class="lede">Every tide station on Shorebite has an hour-by-hour fishing forecast. Here are today's top-rated spots in each
state. Open any of them for the best times, live wind and pressure, rain radar and the fish recorded in those waters.</p>
<div class="search"><input type="search" placeholder="Find your beach, pier or harbor" aria-label="Search fishing spots" data-search data-suffix="#bite" autocomplete="off"><div class="results" data-results hidden></div></div>
<h2>{ico("fish")} How the bite score works</h2>
<p>A 0 to 100 score for every hour, built from what anglers watch most:</p>
{tipcards(BITE_TIPS, "fish")}
<p class="note">A planning aid, not a guarantee. Always check your state's fishing rules, seasons and limits.</p>
{"".join(rows)}"""
    return page("Fishing Forecast Today: Best Times to Fish at Every US Beach and Harbor",
                "Hour-by-hour fishing forecasts and today's best-rated fishing spots in every coastal state, from tides, solunar periods, moon and live weather.",
                "fishing/", body, crumbs=[("Home", ""), ("Fishing", "fishing/")], scripts=("units.js", "site.js"))


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
    "code": '<path d="m8 8-5 4 5 4M16 8l5 4-5 4M13.5 5l-3 14"/>',
    "beach": '<path d="M3 20h18"/><path d="M12 20 8.5 8"/><path d="M4 9.5a8 8 0 0 1 15-3.5z"/>',
    "ramp": '<path d="M3 19 21 9v10z"/><path d="M8 13l3-1.5"/>',
    "anchor": '<circle cx="12" cy="5" r="2"/><path d="M12 7v14M5 13a7 7 0 0 0 14 0M8 11h8"/>',
    "pier": '<path d="M3 9h18M6 9v11M12 9v11M18 9v11"/><path d="M3 20c1.5 0 1.5-1 3-1s1.5 1 3 1 1.5-1 3-1 1.5 1 3 1 1.5-1 3-1 1.5 1 3 1"/>',
    "pin": '<path d="M12 21s-7-6.5-7-11.5a7 7 0 0 1 14 0C19 14.5 12 21 12 21z"/><circle cx="12" cy="9.5" r="2.5"/>',
    "chat": '<path d="M4 5h16v11H9l-5 4z"/><path d="M8 9h8M8 12h5"/>',
    "share": '<circle cx="18" cy="5" r="2.5"/><circle cx="6" cy="12" r="2.5"/><circle cx="18" cy="19" r="2.5"/><path d="m8.2 10.8 7.6-4.4M8.2 13.2l7.6 4.4"/>',
    "mail": '<rect x="3" y="5" width="18" height="14" rx="2"/><path d="m3 7 9 6 9-6"/>',
    "camera": '<path d="M4 8h3l2-3h6l2 3h3v11H4z"/><circle cx="12" cy="13" r="3.5"/>',
    "clock": '<circle cx="12" cy="12" r="9"/><path d="M12 7v5l3 2"/>',
    "ruler": '<rect x="2.5" y="8" width="19" height="8" rx="1.5"/><path d="M6 8v3M9.5 8v4M13 8v3M16.5 8v4"/>',
    "compare": '<rect x="3" y="5" width="8" height="14" rx="1.5"/><rect x="13" y="5" width="8" height="14" rx="1.5"/><path d="M3 15l2.5-2 2.5 2 3-2M13 12l2.5-2 2.5 2 3-2"/>',
    "upload": '<path d="M12 16V4M7 9l5-5 5 5"/><path d="M4 16v4h16v-4"/>',
    "waves": '<path d="M2 9c2.5 0 2.5-2 5-2s2.5 2 5 2 2.5-2 5-2 2.5 2 5 2M2 15c2.5 0 2.5-2 5-2s2.5 2 5 2 2.5-2 5-2 2.5 2 5 2M2 21c2.5 0 2.5-2 5-2s2.5 2 5 2 2.5-2 5-2 2.5 2 5 2"/>',
    "log": '<ellipse cx="5" cy="12" rx="2.5" ry="4"/><path d="M5 8h14a2.5 4 0 0 1 0 8H5"/><path d="M2 21c2.5 0 2.5-1.5 5-1.5s2.5 1.5 5 1.5 2.5-1.5 5-1.5 2.5 1.5 5 1.5"/>',
    "car": '<path d="M5 13l1.5-5h11L19 13"/><rect x="3" y="13" width="18" height="5" rx="1.5"/><circle cx="7.5" cy="18" r="1.5"/><circle cx="16.5" cy="18" r="1.5"/>',
    "wind": '<path d="M3 8h11a3 3 0 1 0-3-3M3 12h16a3 3 0 1 1-3 3M3 16h7"/>',
    "moon": '<path d="M20 14.5A8 8 0 0 1 9.5 4a8 8 0 1 0 10.5 10.5z"/>',
    "phase": '<circle cx="12" cy="12" r="9"/><path d="M12 3a9 9 0 0 1 0 18z" fill="currentColor"/>',
    "sunrise": '<path d="M4 18h16M7 18a5 5 0 0 1 10 0M12 4v5M9 7l3-3 3 3M3.5 13l1.6.9M20.5 13l-1.6.9"/>',
    "sun": '<circle cx="12" cy="12" r="4"/><path d="M12 2v2M12 20v2M4.9 4.9l1.4 1.4M17.7 17.7l1.4 1.4M2 12h2M20 12h2M4.9 19.1l1.4-1.4M17.7 6.3l1.4-1.4"/>',
    "gauge": '<path d="M4 18a8 8 0 1 1 16 0"/><path d="M12 18l4-5"/><circle cx="12" cy="18" r="1"/>',
    "search": '<circle cx="11" cy="11" r="6.5"/><path d="m16 16 4.5 4.5"/>',
}


def ico(name, cls="ico"):
    return f'<svg class="{cls}" viewBox="0 0 24 24" aria-hidden="true">{ICON[name]}</svg>'
FEATURES = [("chart", "Today's tide chart", "A live curve with a now marker, the next high or low, and whether the water is rising or falling."),
            ("current", "Tidal currents", "Slack water and peak flood and ebb in knots, from the nearest NOAA current station."),
            ("fish", "Hour-by-hour fishing forecast", "A bite score for every hour, the best times to fish, live wind and pressure, and a rain radar."),
            ("pin", "Fish in these waters", "The fish, sharks and rays recorded around each spot, and what's in season this month."),
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


def home_signup():
    if not ALERTS_API:
        return ""
    return f"""<section class="signup-band" id="signup-band">
<div class="sb-text"><h2>{ico("mail")}Your beach's tides, in your inbox</h2>
<p>Every Thursday: the week's high and low tides for your spot, a heads-up when the weekend has great low tides, and
warnings when the weather service flags your water. Free, and one click to stop.</p></div>
<div class="sb-form"><div class="search"><input type="search" placeholder="Find your beach or harbor" aria-label="Find your spot to sign up" data-search data-suffix="#emails" autocomplete="off"><div class="results" data-results hidden></div></div>
<p class="note">Pick your spot, then add your email on its page.</p></div>
</section>"""


def bite_line(st, tz, today):
    b = (st.get("_bite") or {}).get(today)
    if not b:
        return ""
    best = span(dt.datetime.fromtimestamp(b[2][0][0], tz), dt.datetime.fromtimestamp(b[2][0][1], tz)) if b[2] else ""
    return (f'<span class="spot-bite"><b class="b{bite_band(b[0])}">{b[0]}</b> {bite_label(b[0])} fishing'
            f'{f" · best {best}" if best else ""}</span>')


def best_fishing(groups, per_region=2):
    """Top-scoring spots for today in each region (named towns first, so the list is recognisable)."""
    out = []
    for label, codes in REGIONS:
        cand = []
        for c in codes.split():
            for st in groups.get(c, []):
                tz = zone_for(st)
                today = dt.datetime.now(tz).date()
                b = (st.get("_bite") or {}).get(today)
                # Skip spots named only by a distance along a river ("8 miles above mouth"): not recognisable on a home page.
                if b and not re.search(r"^\d|\bmiles?\b|\babove\b|\bbelow\b", st["pretty"], re.I):
                    cand.append((bool(st.get("town")) + (st["type"] == "R"), b[0], st, tz, today))
        cand.sort(key=lambda x: (x[0], x[1]), reverse=True)
        best_by_state = {}
        for town, sc, st, tz, today in cand:  # one spot per state first, so a region shows different states
            best_by_state.setdefault(st["state"], (sc, st, tz, today))
        picks = sorted(best_by_state.values(), key=lambda x: -x[0])[:per_region]
        if len(picks) < per_region:
            used = {p[1]["id"] for p in picks}
            picks += [(sc, st, tz, today) for _, sc, st, tz, today in cand if st["id"] not in used][:per_region - len(picks)]
        if picks:
            out.append((label, picks))
    return out


def bite_card_small(st, tz, today):
    return (f'<a class="spot fish-spot" href="{BASE}{st["path"]}#bite"><span class="spot-name">{esc(st["pretty"])}'
            f'<small>{esc(STATES.get(st["state"], st["state"]))}</small></span>{bite_line(st, tz, today)}</a>')


def kt_band(kings):
    """Home page: the next king tides in the busiest coastal states, linking into the king tide pages."""
    if not kings:
        return ""
    today = dt.datetime.now(dt.timezone.utc).date()
    chips = []
    for c in ("CA", "OR", "WA", "FL", "SC", "NJ", "NY", "MA", "VA", "TX", "HI", "AK"):
        spots = kings.get(c)
        if not spots:
            continue
        wins = [w for w in kingtides.state_windows([kt for _, kt in spots]) if w[1] >= today]
        if wins:
            chips.append(f'<a class="kt-chip" href="{BASE}{kt_path(c)}"><b>{esc(STATES[c])}</b> {kingtides.span(wins[0][0], wins[0][1])}</a>')
    return f"""<section class="fish-band kt-band">
<div class="fish-band-head"><h2 class="sec">{ico("cal")}King tides {kingtides.season_label(today)}</h2>
<a href="{BASE}king-tides/">Every state, every spot →</a></div>
<p>The highest tides of the year. Here's when the next ones arrive; open a state for peak times and heights at your spot.</p>
<div class="kt-chips">{"".join(chips)}</div>
</section>"""

def home(groups, total, popular, kings=None):
    cards = []
    for st, tz, events, today in popular:
        a = dt.datetime.combine(today, dt.time(0), tz).timestamp()
        evs = [(dt.datetime.fromtimestamp(t, tz), v, k) for t, v, k in events if a <= t < a + 86400]
        times = "".join(f'<li class="{k}"><b title="{"High" if k == "H" else "Low"}">{"▲" if k == "H" else "▼"}</b> {clock(w)} <i>{ft(v)}</i></li>'
                        for w, v, k in evs)
        cards.append(f'<a class="spot" href="{BASE}{st["path"]}"><span class="spot-name">{esc(st["pretty"])}'
                     f'<small>{esc(STATES.get(st["state"], st["state"]))}</small></span>{spark(events, a, a + 86400)}'
                     f'<ul>{times}</ul>{bite_line(st, tz, today)}</a>')
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
<h1>Tides and fishing forecasts for every beach, bay and harbor in the US</h1>
<p>{total:,} spots with today's tide chart, an hour-by-hour fishing forecast with the best times to fish, the fish in those waters, currents and the marine forecast. Updated every night.</p>
<div class="search big"><input type="search" placeholder="Search a beach, harbor or town" aria-label="Search tide stations" data-search autocomplete="off"><div class="results" data-results hidden></div></div>
<div class="locates"><button type="button" class="locate" data-locate><svg viewBox="0 0 24 24" aria-hidden="true"><circle cx="12" cy="12" r="3"/><path d="M12 2v3M12 19v3M2 12h3M19 12h3"/><circle cx="12" cy="12" r="8"/></svg>Find tides near me</button>
<button type="button" class="locate" data-locate data-suffix="#bite"><svg viewBox="0 0 24 24" aria-hidden="true">{ICON["fish"]}</svg>Fishing near me</button></div>
<p class="locate-msg" data-locate-msg hidden></p>
</div>
</section>

<section class="saved" id="saved" hidden><h2 class="sec">{ico("star")}Your favorites <span>· work offline</span></h2><div class="saved-list" id="saved-list"></div></section>

<h2 class="sec">Popular spots{f' <span>· {day_label(day)}</span>' if day else ''}</h2>
<div class="spots">{"".join(cards)}</div>

{kt_band(kings)}

<section class="fish-band">
<div class="fish-band-head"><h2 class="sec">{ico("fish")}Best fishing today</h2>
<a href="{BASE}fishing/">All states and how the bite score works →</a></div>
<p>Every spot gets an hour-by-hour bite score from the tide flow, solunar periods, dawn and dusk, the moon, and live wind and pressure.
These are today's top-rated spots in each part of the country.</p>
<div class="spots">{"".join(bite_card_small(st, tz, today) for _, st, tz, today in [x for _, picks in best_fishing(groups, 3) for x in picks][:12])}</div>
</section>

{home_signup()}

<h2 class="sec">On every station page</h2>
<div class="feats">{feats}</div>

<h2 class="sec">Browse by state</h2>
<div class="regions">{"".join(regions)}</div>

<a class="guide-cta" href="{BASE}how-to-read-a-tide-chart/"><b>New to tide charts?</b> Learn what MLLW, minus tides and spring tides mean in two minutes →</a>
"""
    return page("Shorebite: Tide Charts, Tide Times & Fishing Forecasts for Every US Beach",
                f"Free tide charts, high and low tide times, currents, fishing times and marine forecasts for {total:,} NOAA stations across the US.",
                "", body, scripts=("units.js", "site.js"))


GUIDE = """
<article class="prose">
<h1>How to read a tide chart</h1>
<p class="lede">A tide chart shows how high the water will be at a spot through the day. Here is what each part means and how to use it.</p>

__GUIDE_CARDS__
__GUIDE_CTA__
</article>
"""

ABOUT = """
<article class="prose">
<h1>About Shorebite</h1>
<p>Shorebite turns NOAA's tide predictions into fast, readable pages for every US tide station: a chart for today,
an hour-by-hour fishing forecast, the week ahead, a month table, currents, the marine forecast, sunrise and sunset,
and the best daylight low tides. The Shorebite app brings the same tides and fishing forecast to your phone, offline.</p>
<p>Shorebite used to be called Tide Chart USA. Same pages, same free tools, new name.</p>
<p>The predictions come from the <a href="https://tidesandcurrents.noaa.gov/">NOAA Center for Operational Oceanographic Products and Services (CO-OPS)</a>.
We download them every night, so each page always shows the next month. Sunrise, sunset and moon phase are calculated from each station's position.</p>
<p>We are not affiliated with NOAA. Predictions are not observations, and this site is not for navigation.</p>
</article>
"""

ANALYTICS_TEXT = ("<h2>Analytics</h2><p>We use Google Analytics to count visits and see which pages are useful. It sets cookies "
                  "and collects things like your approximate location, device and the pages you view, not your name or email. "
                  "You can opt out with <a href=\"https://tools.google.com/dlpage/gaoptout\">Google's opt-out add-on</a> or by blocking cookies. "
                  "We also use Cloudflare Web Analytics, which sets no cookies and only gives us aggregated counts "
                  "(<a href=\"https://www.cloudflare.com/privacypolicy/\">Cloudflare's privacy policy</a>). "
                  "We also use Clicky to see how visitors move through the site "
                  "(<a href=\"https://clicky.com/terms/privacy\">Clicky's privacy policy</a>). "
                  "If we add advertising, this page will be updated to name those partners and explain your choices.</p>") if GA_ID else \
                 ("<p>If we add advertising or analytics, those partners may use cookies to measure visits and show ads, "
                  "and this page will be updated to name them and explain your choices.</p>")

AMAZON_TAG = "shorebite-20"  # Amazon US Associates; the linked amazon.ca account (shorebiteca-20) is reached via OneLink


def amz(q):
    """An Amazon search link (no invented products), tagged, marked as a paid link."""
    return (f'<a href="https://www.amazon.com/s?k={urllib.parse.quote_plus(q)}&amp;tag={AMAZON_TAG}" '
            f'rel="sponsored nofollow noopener" target="_blank">{esc(q[:1].upper() + q[1:])}</a>')


GEAR = [  # section id, icon, heading, intro, [(icon, item search, why)]
    ("tidepools", "pool", "Tide pooling", "Low tide is the time to explore. Rocks are slick and the water comes back fast.", [
        ("walk", "water shoes with grippy soles", "Wet rock and barnacles are sharp and slippery. Closed toes, firm soles."),
        ("search", "tide pool field guide", "Name what you find: anemones, sea stars, nudibranchs, crabs."),
        ("sun", "waterproof headlamp", "The best minus tides are often at dawn or after dark."),
        ("camera", "waterproof phone pouch", "Photos without dunking your phone.")]),
    ("beach", "beach", "Beach walks and king tides", "Big tides flood paths and parking. Dress for spray and wet feet.", [
        ("waves", "waterproof rain boots", "King tides cover low streets and boardwalks."),
        ("wind", "packable rain jacket", "King tides come with winter storms and wind."),
        ("camera", "phone tripod", "Steady shots to document how high the water got."),
        ("clock", "tide clock", "A wall clock that shows hours to the next high or low.")]),
    ("fishing", "fish", "Surf and pier fishing", "Match the gear to the water you fish. Check local rules and licences first.", [
        ("fish", "surf fishing rod and reel combo", "A long rod to reach past the breakers."),
        ("pier", "pier fishing rod and reel combo", "Shorter and stout for pier rails."),
        ("fish", "saltwater fishing tackle box kit", "Hooks, sinkers and rigs that stand up to salt."),
        ("chart", "rod holder sand spike", "Keeps your rod up while you wait for the bite."),
        ("ruler", "fish measuring board", "Check legal sizes before you keep a fish.")]),
    ("paddling", "kayak", "Kayak and boat safety", "Plan around the current and slack water, and carry the basics.", [
        ("kayak", "kayak PFD life jacket", "Wear it. Tidal currents are stronger than they look."),
        ("phone", "waterproof dry bag", "Keeps your phone, keys and snacks dry."),
        ("radio", "handheld marine VHF radio", "Weather alerts and a way to call for help."),
        ("warn", "safety whistle", "Required on many boats, and cheap insurance.")]),
]


def gear_page():
    sections = "".join(
        f'<h2 id="{sid}">{ico(icon)} {esc(title)}</h2><p>{esc(intro)}</p><div class="tips t-learn">' + "".join(
            f'<div class="tcard"><span class="tc-i">{ico(i)}</span><div><b>{amz(q)}</b><p>{esc(why)}</p></div></div>'
            for i, q, why in items) + "</div>"
        for sid, icon, title, intro, items in GEAR)
    jump = " · ".join(f'<a href="#{sid}">{esc(t)}</a>' for sid, _, t, _, _ in GEAR)
    return page("Tide Pool, Beach and Fishing Gear", "What to bring for tide pooling, king tides, surf and pier fishing and kayaking.",
                "gear/", f"""<article class="prose">
<h1>Gear for the tides</h1>
<p class="lede">What's worth bringing for tide pools, beach walks, fishing and paddling, picked for safety and comfort near moving water.</p>
<p class="note">Links below go to Amazon searches so you can compare options (<a href="{BASE}privacy/#affiliate">affiliate links</a>).</p>
<p class="tools">{jump}</p>
{sections}
<p class="note">Always check the tide before you go, and never turn your back on the ocean.</p>
</article>""")


PRIVACY = """
<article class="prose">
<h1>Privacy</h1>
<p>This site has no accounts. The only personal information we collect is your email address, if you sign up for tide emails.</p>
<h2>Tide emails</h2>
<p>When you sign up we store your email address, the station you picked and which emails you want. We use them only to send those emails.
The list is kept in our Cloudflare database and the emails are sent through Resend. We never sell or share it.
Every email has a one-click unsubscribe link, which deletes your subscription. You can also email hello@shorebite.com to be removed.</p>
<h2>Conditions reports, votes and favorites</h2>
<p>Conditions reports are public and anonymous: we show the tags and note you choose, and the time. Accuracy votes and
favorites are stored only as totals per station. To stop spam and double votes we keep a scrambled code made from your
IP address that changes every day and can't be turned back into the address. Your list of favorites stays on your own device.</p>
{ANALYTICS_TEXT}
<h2 id="affiliate">Affiliate links</h2>
<p>Some links, such as on our <a href="/gear/">gear page</a>, go to Amazon. As an Amazon Associate we earn from qualifying purchases at no extra cost to you. Amazon may set its own cookies when you click.</p>
</article>
"""


WIDGET_PAGE = """
<article class="prose">
<h1>Free tide widget for your website</h1>
<p>Show today's tides for your beach, harbor or river on your own site: the current water level, a small 24-hour
tide curve and the next four highs and lows. It updates itself every day from NOAA predictions and works on any website
builder that accepts an embed or HTML block (WordPress, Squarespace, Wix, Shopify and others).</p>
<p>It's free for marinas, bait and tackle shops, fishing and boating clubs, vacation rentals, surf shops, harbor masters,
schools and local news. There's no sign-up and no ads in the widget.</p>
<h2>Get the code</h2>
<ol class="steps"><li>Find your spot below.</li><li>On its page, scroll to <b>Put these tides on your website</b> at the bottom and tap <b>Copy the code</b>.</li>
<li>Paste it into an HTML or embed block on your site.</li></ol>
<div class="search big"><input type="search" placeholder="Find your beach, harbor or town" aria-label="Find your spot" data-search data-suffix="#embed" autocomplete="off"><div class="results" data-results hidden></div></div>
<h2>Good to know</h2>
<ul><li>It's 340 pixels wide and shrinks to fit narrow columns. It follows your visitor's light or dark setting; add <code>?theme=light</code> or <code>?theme=dark</code> to the address in the code to fix one.</li>
<li>Please keep the small link under the widget: it tells your visitors where the tides come from.</li>
<li>Predictions, not live readings. Not for navigation.</li></ul>
<p>Questions? Email <a href="mailto:hello@shorebite.com">hello@shorebite.com</a>.</p>
</article>
"""

SAVED_PAGE = """
<article class="prose saved-page">
<h1>Your favorite spots</h1>
<p>Your favorites are kept on this device with a month of tide predictions, so they open even with no signal:
on the boat, on the beach or in airplane mode. They update themselves whenever you open them with a connection.</p>
<div class="saved-list" id="saved-list"></div>
<h2>How to add a favorite</h2>
<ol class="steps"><li>Open any beach or harbor page.</li><li>Tap <b>Favorite</b> near the top.</li><li>Come back here any time from <b>Favorites</b> at the top of every page.</li></ol>
<p class="note">Favorites live in this browser. If you clear your browsing data they'll be removed. Live weather and warnings need a connection.</p>
</article>
"""

OFFLINE = """
<article class="prose">
<h1>You're offline</h1>
<p>This page isn't saved on your device. Your favorites, and pages you opened recently, still work without a connection:</p>
<div class="saved-list" id="saved-list"></div>
<p class="note">Saved pages hold a month of tide predictions. Live weather, warnings and water levels need a connection.</p>
</article>
"""

# Service worker: pages come from the network when possible (so they stay fresh) and fall back to the copy
# on the device; the files a page needs are cached on first use. "Save offline" keeps a page in its own cache.
SW = """const VER = "__VER__", BASE = "__BASE__";
const STATIC = "tc-static-" + VER, PAGES = "tc-pages", SAVED = "tc-saved", MAX_PAGES = 40;
self.addEventListener("install", (e) => {
  e.waitUntil(caches.open(STATIC).then((c) => c.addAll([BASE, BASE + "offline/", BASE + "favorites/", BASE + "static/icon-192.png"])).then(() => self.skipWaiting()));
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


def search_index(stations, town_pages=()):
    """[label, state, path, lat, lng, extra words to match]. Towns come first so "Pacifica" finds its town page."""
    return {"base": BASE, "s": [[f"Tides near {n}", st, p, round(la, 3), round(lo, 3), "town"] + ([aka] if aka else [])
                                for n, st, p, la, lo, aka in town_pages] +
            [[s["pretty"], s["state"], s["path"], round(s["lat"], 3), round(s["lng"], 3), s["town"][0] if s.get("town") else ""]
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
    nearby = load(ROOT / "collector" / "places.json", {})
    towns = load(ROOT / "collector" / "towns.json", {"stations": {}, "towns": {}})
    # Beach towns, islands and spots people search for that GeoNames/towns.py miss, plus other names for places.
    extra = load(ROOT / "collector" / "extra_places.json", {"places": [], "aka": {}})
    for name, st, la, lo, *opt in extra["places"]:
        towns["towns"].setdefault(f"{st}|{name}", [name, st, la, lo, 0] + opt)
    town_aka = extra["aka"]
    towns["towns"] = {k: v for k, v in towns["towns"].items() if not TOWN_JUNK.search(v[0])}
    for st_ in stations:
        t = towns["stations"].get(st_["id"])
        if t and t[0] in towns["towns"]:
            tn = towns["towns"][t[0]]
            st_["town"] = (tn[0], tn[1], t[1], town_path(tn[0], tn[1]))

    def cur_for(sid):
        link = cur["links"].get(sid)
        if not link:
            return None
        events = load(DATA / "currents" / f"{link[0]}.json", None)
        return (cur["stations"][link[0]], link[1], events) if events else None

    years = sorted(int(p.name) for p in YEAR_DIR.glob("*") if p.name.isdigit()) if YEAR_DIR.exists() else []
    year_pages = []
    kt_by_state, tp_by_state, clam_cands = {}, {}, {}
    groups = {}
    popular = {}
    built_data = {}
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
        wt_set = set(sensors.get("wt", ()))
        near_wt = [(d, o) for d, o in sorted(((miles(s, o), o) for o in cand if o["id"] in wt_set), key=lambda p: p[0]) if d <= 20][:3]
        ctx = {"tz": tz, "events": events, "days": days, "near": near, "today": today, "near_wt": near_wt,
               "ref": by_id.get(s["ref"]), "cur": cur_for(s["id"]), "sensors": sensors,
               "buoy": buoys.get(s["id"]), "zone": zones.get(s["id"]) or None,
               "nwr": radios.get(s["id"]), "county": counties.get(s["id"]) or None,
               "places": nearby.get(s["id"]), "years": [y for y in years if (YEAR_DIR / str(y) / f"{s['id']}.json").exists()]}
        raws = {y: json.loads((YEAR_DIR / str(y) / f"{s['id']}.json").read_text()) for y in ctx["years"]}
        ctx["kt"] = kingtides.windows_for(raws, tz, today) if raws else None
        if ctx["kt"]:
            kt_by_state.setdefault(s["state"], []).append((s, ctx["kt"]))
        ctx["tp"] = lowtides.lows_for(raws, tz, s["lat"], s["lng"], today) if raws else None
        if raws and s["id"] in {b[2] for b in CLAM_BEACHES}:
            clam_cands[s["id"]] = (s, tz, raws, today)
        if ctx["tp"]:
            tp_by_state.setdefault(s["state"], []).append((s, ctx["tp"]))
        write(s["path"] + "index.html", station_page(s, ctx))
        for y in ctx["years"]:
            yp = year_page(s, y, raws[y], tz)
            if yp:
                write(yp[0] + "index.html", yp[1])
                year_pages.append(yp[0])
        if s["id"] in POPULAR:
            popular[s["id"]] = (s, tz, events, today)
        s["_places"] = ctx["places"]
        built_data[s["id"]] = (s, tz, events, today)
        write(f"embed/{s['id']}/index.html", embed_page(s, events, tz))
        groups.setdefault(s["state"], []).append(s)
        built += 1

    # Town pages. Every town with a built station within 15 miles is a candidate. Kept: a station's own town, a hand-picked
    # or searched place (extra_places.json), a town with a water word in its name, a town right on the water (station within
    # TOWN_WATER_MILES), and otherwise one page per set of closest stations among towns within TOWN_COAST_MILES. That
    # drops inland suburbs that would all repeat the same few stations (Google treats mass near-copies as low value).
    town_pages, by_state_towns, cand = [], {}, {}
    tlist = [(k, v) for k, v in towns["towns"].items()]
    for k, tn in tlist:
        pt = {"lat": tn[2], "lng": tn[3]}
        near = sorted(((miles(pt, o), o) for dy in (-1, 0, 1) for dx in (-1, 0, 1)
                       for o in cells.get((int(tn[2]) + dy, int(tn[3]) + dx), []) if o["id"] in built_data),
                      key=lambda x: x[0])
        opt = tn[5] if len(tn) > 5 else {}
        if opt.get("r", 15) > 15:  # islands and coasts reach past the neighbouring cells
            near = sorted(((miles(pt, o), o) for o in stations if o["id"] in built_data), key=lambda x: x[0])
        near = [(d, built_data[o["id"]]) for d, o in near if d <= opt.get("r", 15)][:12 if opt.get("region") else 8]
        if near:
            cand[k] = (tn, near, opt)
    protected = {t[0] for t in towns["stations"].values()} | {f"{p[1]}|{p[0]}" for p in extra["places"]} | set(extra.get("keep", []))
    keep, by_set, paths = set(), {}, {}
    for k, (tn, near, opt) in cand.items():
        if k in protected or TOWN_WATER.search(tn[0]) or near[0][0] <= TOWN_WATER_MILES:
            keep.add(k)
        elif near[0][0] <= TOWN_COAST_MILES:
            by_set.setdefault(tuple(x[1][0]["id"] for x in near[:3]), []).append(k)
    shown = {tuple(x[1][0]["id"] for x in cand[k][1][:3]) for k in keep}
    for ids, ks in by_set.items():
        if ids not in shown:  # one page per set of closest stations: the biggest town
            keep.add(max(ks, key=lambda k: cand[k][0][4]))
    for k in sorted(keep, key=lambda k: (k not in protected, k)):  # two names, one URL (Kihei / Kīhei): first wins
        paths.setdefault(town_path(cand[k][0][0], cand[k][0][1]), k)
    keep = set(paths.values())
    (DATA / "town_pages_dropped.txt").write_text("".join(sorted({town_path(cand[k][0][0], cand[k][0][1]) + "\n" for k in cand} - {p + "\n" for p in paths})))
    tlist = [(k, v) for k, v in tlist if k in keep]
    # Dropped pages may already be crawled or bookmarked: send each to the nearest kept town (noindex, canonical).
    kept_pts = [(cand[k][0][2], cand[k][0][3], town_path(cand[k][0][0], cand[k][0][1])) for k in keep]
    for k in set(cand) - keep:
        tn = cand[k][0]
        old = town_path(tn[0], tn[1])
        if old in paths:
            continue
        to = min(kept_pts, key=lambda p: (p[0] - tn[2]) ** 2 + ((p[1] - tn[3]) * math.cos(math.radians(tn[2]))) ** 2)[2]
        write(old + "index.html", f'<!doctype html><meta charset="utf-8"><title>Tides near {esc(tn[0])}</title>'
              f'<meta name="robots" content="noindex"><link rel="canonical" href="{SITE_URL}/{to}">'
              f'<meta http-equiv="refresh" content="0; url={BASE}{to}"><a href="{BASE}{to}">Tides near {esc(tn[0])}</a>')
    for k, tn in tlist:
        pt = {"lat": tn[2], "lng": tn[3]}
        _, near, opt = cand[k]
        others = sorted((miles(pt, {"lat": o[2], "lng": o[3]}), o[0], town_path(o[0], o[1])) for kk, o in tlist
                        if kk != k and abs(o[2] - tn[2]) < 0.5 and abs(o[3] - tn[3]) < 0.6)
        others = [x for x in others if 0.3 < x[0] <= 25][:8]
        aka = town_aka.get(k, [])
        path, html_ = town_page(tn, near, others, aka, opt.get("region", False))
        write(path + "index.html", html_)
        town_pages.append((tn[0], tn[1], path, tn[2], tn[3], " ".join(aka)))
        by_state_towns.setdefault(tn[1], []).append((tn[0], path))

    for code, g in groups.items():
        path, html_ = state_page(code, g, by_state_towns.get(code, ()), code in kt_by_state, code in tp_by_state)
        write(path + "index.html", html_)
    kt_pages = []
    if kt_by_state:
        kt_today = built_at.date()
        for code, rows in kt_by_state.items():
            path, html_, cal = kt_state_page(code, rows, kt_today, built_at)
            write(path + "index.html", html_)
            write(path + "king-tides.ics", cal)
            kt_pages.append(path)
        write("king-tides/index.html", kt_hub(kt_by_state, kt_today))
        kt_pages.insert(0, "king-tides/")
    if tp_by_state:
        tp_today = built_at.date()
        all_tp = [(st, tp) for rows in tp_by_state.values() for st, tp in rows]
        spots = []
        for name, code, la, lo in TP_SPOTS:
            d, (st, tp) = min(((miles({"lat": la, "lng": lo}, st), (st, tp)) for st, tp in all_tp), key=lambda x: x[0])
            if d <= 15:
                spots.append((name, code, st, tp, d))
        for code, rows in tp_by_state.items():
            path, html_ = tp_state_page(code, rows, spots, tp_today)
            write(path + "index.html", html_)
            kt_pages.append(path)
        write("tide-pools/index.html", tp_hub(tp_by_state, spots, tp_today))
        kt_pages.append("tide-pools/")
    beaches = []
    for name, code, sid, note in CLAM_BEACHES:
        if sid in clam_cands:
            s, tz, raws, today = clam_cands[sid]
            beaches.append((name, code, note, s, tz, clam_tides(raws, tz, code, today)))
    if beaches:
        write("razor-clams/index.html", clam_page(beaches, built_at.date()))
        kt_pages.append("razor-clams/")
    live = [s for g in groups.values() for s in g]
    write(f"{INDEXNOW_KEY}.txt", INDEXNOW_KEY)
    # Bing Webmaster Tools site ownership (the account's code, public by design).
    write("BingSiteAuth.xml", f'<?xml version="1.0"?>\n<users>\n\t<user>{BING_AUTH}</user>\n</users>\n')
    write("manifest.webmanifest", json.dumps({
        "name": SITE_NAME, "short_name": "Shorebite", "start_url": BASE, "scope": BASE, "display": "standalone",
        "background_color": "#f4f8fa", "theme_color": "#0b5c7a",
        "description": "Tide charts, currents, fishing times and marine weather for US beaches and harbors.",
        "icons": [{"src": f"{BASE}static/icon-{n}.png", "sizes": f"{n}x{n}", "type": "image/png", "purpose": "any maskable"}
                  for n in (192, 512)]}, indent=1))
    write("sw.js", SW.replace("__BASE__", BASE).replace("__VER__", CSS_VER + "-" + built_at.strftime("%Y%m%d")))
    write("widget/index.html", page("Free Tide Widget for Your Website", "Add today's tides for your beach or harbor to your own website: free, no sign-up.",
                                    "widget/", WIDGET_PAGE.replace("<a href=\"mailto", "<a href=\"mailto"), scripts=("site.js",)))
    write("favorites/index.html", page("Favorite spots", "Your favorite tide stations.", "favorites/", SAVED_PAGE, scripts=("units.js",),
                                   extra_head='<meta name="robots" content="noindex">'))
    write("offline/index.html", page("Offline", "You're offline.", "offline/", OFFLINE, scripts=("units.js",),
                                     extra_head='<meta name="robots" content="noindex">'))
    write("index.html", home(groups, len(live), [popular[i] for i in POPULAR if i in popular], kt_by_state))
    write("fishing/index.html", fishing_page(groups))
    write("states/index.html", page("Tide Charts by State", "Pick a state to see every NOAA tide station there.",
                                    "states/", f"<h1>Tide charts by state</h1><ul class='states'>{states_index(groups)}</ul>",
                                    crumbs=[("Home", ""), ("States", "states/")]))
    write("how-to-read-a-tide-chart/index.html", page(
        "How to Read a Tide Chart: Highs, Lows, MLLW and Minus Tides",
        "What the curve and numbers on a tide chart mean, why the two daily highs differ, and spring vs. neap tides.",
        "how-to-read-a-tide-chart/", GUIDE.replace("__GUIDE_CARDS__", tipcards(GUIDE_TIPS, "learn")).replace("__GUIDE_CTA__", (
            f'<p class="cta-box">{ico("mail")} <span>Want this for your own beach? <a href="{BASE}#signup-band">Get its tides free by email '
            f'every Thursday</a>, with a heads-up before the best low tides.</span></p>') if ALERTS_API else ""), crumbs=[("Home", ""), ("How to read a tide chart", "how-to-read-a-tide-chart/")]))
    write("about/index.html", page("About Shorebite", "Where our tide predictions come from.", "about/", ABOUT))
    if ALERTS_API:
        write("alerts/index.html", page("Tide emails", "Weekly tide times and weather warnings by email.", "alerts/",
                                        ALERTS_PAGE.format(base=BASE, api=ALERTS_API),
                                        extra_head='<meta name="robots" content="noindex">'))
    write("gear/index.html", gear_page())
    write("privacy/index.html", page("Privacy", "Privacy at Shorebite.", "privacy/", PRIVACY.replace("{ANALYTICS_TEXT}", ANALYTICS_TEXT)))
    write("404.html", page("Page not found", "Page not found.", "404.html",
                           f"<h1>Page not found</h1><p><a href='{BASE}'>Search for a tide station</a>.</p>"))
    write("static/search.json", json.dumps(search_index(live, town_pages), separators=(",", ":")))
    if LAUNCHED:
        urls = [""] + ["fishing/", "states/", "how-to-read-a-tide-chart/", "about/", "widget/", "gear/"] + \
               [f"tides/{slugify(STATES.get(c, c))}/" for c in groups] + [s["path"] for s in live] + [t[2] for t in town_pages] + year_pages + kt_pages
        write("sitemap.xml", '<?xml version="1.0" encoding="UTF-8"?>\n<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">'
              + "".join(f"<url><loc>{SITE_URL}/{u}</loc><lastmod>{built_at.date().isoformat()}</lastmod></url>" for u in urls)
              + "</urlset>")
        write("robots.txt", f"User-agent: *\nAllow: /\nSitemap: {SITE_URL}/sitemap.xml\n")
    else:
        write("robots.txt", "User-agent: *\nAllow: /\n")
    write(".nojekyll", "")
    host = urlparse(SITE_URL).hostname or ""
    if not host.endswith("github.io"):
        write("CNAME", host + "\n")
    print(f"built {len(town_pages)} town pages, {len(year_pages)} year tide tables, {len(kt_pages)} king tide + tide pool pages")
    print(f"built {built} station pages, {len(groups)} states" + ("" if LAUNCHED else " (noindex)"))


if __name__ == "__main__":
    main()
