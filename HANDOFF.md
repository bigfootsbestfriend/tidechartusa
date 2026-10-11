# Tide Chart USA: handoff

Static tide-chart site for every US NOAA tide prediction station (~3,000 pages), rebuilt every night.

- Repo: github.com/bigfootsbestfriend/tidechartusa (public)
- Preview: https://bigfootsbestfriend.github.io/tidechartusa/ (noindex until launch)
- Planned domain: tidechartusa.com (not bought yet; Mike buys through Cloudflare Registrar)

## How it works
1. `collector/fetch.py` downloads NOAA's station list and 33 days of high/low predictions per station
   (starting yesterday, so every US time zone has "today"). About 17 minutes. Data isn't committed.
   If more than 5% of stations fail, it exits non-zero and the previous deploy stays live.
2. `site/build.py` (stdlib only) writes `_site/`: station pages, state pages, home with search,
   the "How to read a tide chart" guide, about and privacy pages.
3. `.github/workflows/nightly.yml` runs both at 07:17 UTC and deploys to GitHub Pages.

Station pages: today's chart (SVG, redrawn in the browser by `static/tide.js` with a "now" marker,
rising/falling, and the next tide), a 7-day table with sunrise/sunset and moon phase, a write-up computed
from that station's predictions (tide type, typical range, spring tides, lowest/highest tide, minus tides),
best daylight low tides, a month tide table, station details, nearby stations.
Sun and moon are calculated locally (`site/astro.py`).

## Boater and angler extras (added 2026-10-10)
- `collector/extras.py` runs after fetch.py (optional step): nearest NOAA **current** station within 10 mi
  (8 days of slack / max flood / max ebb), lists of stations with **live water temperature / water level**
  sensors, nearest **NDBC buoy** within 40 mi, and each station's **NWS marine zone**
  (`collector/marine_zones.json`, committed; only new stations are looked up, max 900 per run).
- Station pages gain: "Conditions" card (marine forecast + active warnings, water temperature, measured
  vs predicted water level, buoy link; all loaded live in the browser by `static/live.js`), "Tidal currents",
  "Best fishing times" (solunar periods from `astro.moon_times` + a day rating), and buttons to print the
  month table or download an .ics calendar of the tides (built in the browser, no extra files).
- NDBC doesn't allow browser fetches, so buoys are a link only.

## Before launch (Mike)
- Review a few station pages and the guide. The write-ups are computed from the data and phrased by Claude;
  Raptive wants meaningful human review, so read and adjust the wording in `writeup()` / `GUIDE`.
- Buy the domain, then: add a CNAME file (`site/static/` is copied, so add `_site/CNAME` in build), point DNS
  in Cloudflare, and build with `SITE_URL=https://tidechartusa.com`.
- Set `LAUNCHED = True` in `site/build.py` (drops noindex, writes sitemap.xml).
- Analytics: create a GA4 property (Raptive requires GA) and add the tag in `page()`.

## Money (not set up; needs Mike's applications)
- Raptive after 25k pageviews/month (long-form on most pages below 100k: the write-ups and guide help).
- FishingBooker affiliate (20–50% of their fee, 90-day cookie; manual approval) for "fishing charters near X".
- Direct local ads / business listings later, like US Harbors ($8 CPM, $45/month listings).
- Boat insurance/towing partners: not researched yet.

## Known limits
- Heights are MLLW feet. A few NOAA stations have no MLLW predictions and are skipped (see fetch log).
- Times on the page are station local time; the browser script uses day boundaries embedded at build time.
- Not for navigation (stated in the footer and guide).
