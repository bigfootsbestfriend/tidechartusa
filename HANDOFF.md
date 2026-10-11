# Shorebite (formerly Tide Chart USA): handoff

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

## Weather, marine radio and tide emails (2026-10-10)

- Station pages load the NWS land forecast in the browser (api.weather.gov/points) next to the marine forecast.
- Marine radio box: nearest in-service NOAA Weather Radio transmitters (`collector/extras.py` → data/nwr.json from
  weather.gov's CCL.js), the SAME county code for alert radios (collector/county_zones.json, cached like
  marine_zones.json), and the standard VHF channels.
- Tide emails: `alerts/` is a Cloudflare Worker (tide-alerts, custom domain alerts.tidechartusa.com) with a D1
  database of subscriptions. Double opt-in, HMAC-signed links via <site>/alerts/. `alerts/send.py` sends the
  weekly email (Thursdays, includes the weekend minus-tide heads-up) and new NWS warnings (every 3 hours) through
  Resend; `.github/workflows/alerts.yml` runs it. Deploy with `alerts/deploy.sh`.
- Turning it on: Worker secret RESEND_API_KEY; GitHub secrets RESEND_API_KEY and MAIL_ADDRESS (ADMIN_TOKEN is set);
  verify tidechartusa.com in Resend; then add `ALERTS_API: https://alerts.tidechartusa.com` to the build env in
  nightly.yml so the signup forms and /alerts/ page appear. Local secrets: ~/.config/kitchen-magpie/tidealerts.env.

## Interactive pages, offline app, pocket card (2026-10-10)

- Station pages: day picker on the chart, tap-to-read chart, tabs for the tables, sticky jump row, trip planner
  (`static/planner.js`: tide pooling, fishing, kayaking, beach walks over 14 days; uses `fish`/`cur` in the page JSON
  and the NWS wind forecast that live.js publishes as `window.tcWx`), feet/meters and 12/24h (`static/units.js`
  rewrites text on screen, remembered in localStorage).
- Offline app: `manifest.webmanifest` + `sw.js` written by build.py (network-first pages with a device copy,
  last 40 pages kept; "Save offline" pages kept in their own cache and refreshed on each visit). `static/app.js`
  handles saving, the saved list on the home and /offline/ pages, the install button and the offline notice.
- "Print pocket card" builds a one-page 7-day summary (tides, sun, fishing, slack water, radio) from the page.
- Bump CSS_VER whenever a static file changes: the service worker serves cached copies first.

## SEO and community features (2026-10-10, after launch)

- Towns: `collector/towns.py` (GeoNames cities500, CC BY) → `collector/towns.json` (committed). Station titles use the
  town people search ("Pacifica, CA Tide Chart … (Point San Pedro)"), and ~2,000 `tides-near/<town>-<st>/` pages
  list the closest stations with today's tides. Towns are in search.json and on state pages.
- Yearly tide tables: `collector/year.py` + `.github/workflows/yearly.yml` (monthly, this year and next, kept in the
  Actions cache `year-data-*`); nightly restores it and builds `tides/<state>/<station>/<year>/`.
- Widget: `embed/<station id>/` (noindex iframe card) + `widget/` page; embed code on every station page carries a
  normal credit link (that's the backlink).
- Nearby places: `collector/places.py` (OpenStreetMap via Overpass, ODbL credit on the section) → `collector/places.json`.
- Community (Worker endpoints in alerts/src/index.js, D1 tables reports/counts/seen): conditions reports (emailed to
  OWNER_EMAIL secret with a delete link; links/phones blocked; 3 per hour per visitor), "were today's times right?"
  votes, favorite counts (shown from 10 votes / 25 favorites). Visitors are only a daily-rotating salted IP hash.
- Place JSON-LD on station pages; sitemap has lastmod. IndexNow key file at /<INDEXNOW_KEY>.txt; Bing site verified by
  DNS CNAME and added via the Bing API.

## Nearby places and yearly tables (2026-10-11)

- **Places** (collector/places.json, committed): built from Geofabrik OpenStreetMap extracts, not Overpass (too busy).
  Download the coastal states' .osm.pbf files (list in ~/.cache/tidechartusa-osm/list.txt on Mike's desktop; 6.9 GB),
  `pip install osmium` in a venv, then `python3 collector/places.py --pbf <files>` (about 6 minutes). The JUNK regex
  drops port, military, private and code-name entries. 2,522 stations have nearby places.
- **Year tables:** yearly.yml downloads are time-boxed (45 min per year) and always save the cache, so a slow NOAA day
  never loses progress; the next run continues. First full cache saved 2026-10-11.
- Rule from Mike: when something is slow, look for another source or method right away instead of waiting.

## Renamed to Shorebite (2026-10-11)

- Live at **https://shorebite.com** (Mike bought it in Cloudflare). GitHub Pages custom domain = shorebite.com (set through the
  API; the build also writes CNAME). tidechartusa.com and www now go to the `tidechartusa-redirect` Worker (`redirect/`),
  which sends a 301 to the same path on shorebite.com. Keep tidechartusa.com registered for at least a year or two.
- Brand: logo = gold sun/moon with a bite out of it over the waves (`site/static/favicon.svg`; icons, og.png made from it with
  rsvg-convert). Wordmark "Shore" white + "bite" gold #f5b942 on #0b5c7a.
- Email: hello@shorebite.com forwards like hello@tidechartusa.com did (Cloudflare Email Routing). Resend domain shorebite.com
  verified (same Resend account/key as before); alerts come from "Shorebite <hello@shorebite.com>". The tide-alerts Worker
  answers on alerts.shorebite.com AND alerts.tidechartusa.com (old links in sent emails keep working).
- Search: Bing site https://shorebite.com/ added via the API (CNAME verify record in place). Google Search Console needs Mike:
  add the shorebite.com Domain property (send Claude the TXT code), then use Change of Address from tidechartusa.com.
- Canada: NOT added. CHS tide predictions are licensed "not for derivative products for commercial purposes"; only the station
  inventory is open data. Needs a commercial licence from CHS (chsinfo@dfo-mpo.gc.ca). NOAA covers only ~4 BC border spots.

## Fishing forecast and fish species (2026-10-11)

- "Fishing forecast" card on every station page (`bite_days()` + `bite_card()` in build.py, `static/bite.js`): hourly bite
  score, best times, live NWS wind/gusts/rain chance (gridpoint forecast) and pressure trend (nearest stations that report it),
  NWS radar loop (radar.weather.gov ridge GIF from the points API's radarStation), regional "biting this month"
  (`site/species_guide.json`, exported from the app's fishing.js). Same scoring model as the app.
- "Fish in the waters around X" (`fish_here_section()`), from `collector/species.py`: GBIF occurrence records under CC0 or
  CC BY 4.0 only (iNaturalist's API terms bar commercial use), fish + sharks/rays within 15 km (40 km if < 8 species),
  WoRMS habitat tags. Output `collector/species.json` is committed; rerun occasionally (GBIF rate-limits: ~1 hour with
  8 workers, resumable via data/species_raw/).

## King tides (2026-10-11)

- `/king-tides/` hub plus `/king-tides/<state>/` for every state with yearly data, each with a `king-tides.ics` calendar of the statewide windows.
- The math is in `site/kingtides.py`, using the yearly data (`data/year`, this year and next):
  - A spot's king tide days are the days whose highest tide is in its top 5% for the next 12 months. Nearby days join into one window.
  - A statewide window is a run of days when at least 25% of the state's spots are in theirs.
  - Because each spot uses its own predictions, the season is right everywhere: Pacific winter, Southeast fall, Hawaii summer and winter.
- Station pages show a "Next king tides here" line above the month table. State tide pages link to their king tide page, and the footer links the hub.
- Official photo projects are listed in `KT_PROGRAMS` in build.py: CA, OR, WA Sea Grant, Hawaii Sea Grant, plus MyCoast for MA/MD/NJ/RI/SC/WA/FL/TX. Re-check these links each fall.
- No outreach (Mike, 2026-10-11). The pages are meant to earn links on their own, mainly from news "king tides this week" stories and local sites.
