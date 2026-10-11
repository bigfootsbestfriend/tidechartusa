"""Send Shorebite emails to confirmed subscribers (the list lives in the tide-alerts Worker's D1 database).

    python3 alerts/send.py weekly      # Thursdays: the week's tides, and the weekend minus-tide heads-up
    python3 alerts/send.py warnings    # every few hours: new NWS marine/coastal warnings for each station
    python3 alerts/send.py ids         # comma-separated subscribed station ids (for fetch.py --ids)
    python3 alerts/send.py weekly --dry-run --to you@example.com   # print or send yourself a sample

Needs RESEND_API_KEY, ADMIN_TOKEN, ALERTS_API (the Worker URL) and MAIL_ADDRESS (the postal address
US anti-spam law requires in the footer). Run after fetch.py so data/ is current.
"""

import argparse
import datetime as dt
import html
import json
import os
import re
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "site"))
os.environ.setdefault("SITE_URL", "https://shorebite.com")
import build  # noqa: E402
from astro import sun  # noqa: E402

SITE = os.environ["SITE_URL"].rstrip("/")
FROM = "Shorebite <hello@shorebite.com>"
UA = "Shorebite/1.0 (hello@shorebite.com)"
# NWS events worth an email for people on or by the water.
EVENTS = {
    "Small Craft Advisory", "Gale Warning", "Storm Warning", "Hurricane Force Wind Warning", "Special Marine Warning",
    "Hazardous Seas Warning", "Heavy Freezing Spray Warning", "Dense Fog Advisory", "Low Water Advisory",
    "Coastal Flood Warning", "Coastal Flood Advisory", "Lakeshore Flood Warning", "High Surf Warning",
    "Storm Surge Warning", "Hurricane Warning", "Tropical Storm Warning", "Tsunami Warning", "Tsunami Advisory",
}
esc = html.escape


def http(url, data=None, headers=None, method=None):
    h = {"User-Agent": UA, **(headers or {})}
    body = None
    if data is not None:
        body = json.dumps(data).encode()
        h["Content-Type"] = "application/json"
    req = urllib.request.Request(url, data=body, headers=h, method=method)
    for n in range(4):
        try:
            return json.loads(urllib.request.urlopen(req, timeout=40).read() or b"null")
        except urllib.error.HTTPError as ex:
            if ex.code < 500 and ex.code != 429 or n == 3:
                raise RuntimeError(f"{url}: {ex.code} {ex.read()[:300]!r}") from None
        except OSError:
            if n == 3:
                raise
        time.sleep(3 * (n + 1))


def stations():
    st = json.loads((build.DATA / "stations.json").read_text())["stations"]
    build.assign_paths(st)
    return {s["id"]: s for s in st}


# ---------- email pieces ----------

def shell(title, inner, unsub_url, unsub_all_url):
    addr = esc(os.environ.get("MAIL_ADDRESS", ""))
    return f"""<!doctype html><html><body style="margin:0;background:#f4f8fa">
<div style="font-family:system-ui,-apple-system,Segoe UI,sans-serif;font-size:16px;line-height:1.5;color:#11232c;max-width:560px;margin:0 auto;padding:20px 16px">
<p style="margin:0 0 16px;font-weight:700;color:#0b5c7a;font-size:18px">Shore<span style="color:#d9930d">bite</span></p>
<h1 style="font-size:22px;line-height:1.25;margin:0 0 16px">{esc(title)}</h1>
{inner}
<p style="color:#536a75;font-size:13px;margin-top:28px;border-top:1px solid #d6e3e9;padding-top:12px">
Predictions from NOAA. Not for navigation; always check local conditions.<br>
<a href="{unsub_url}" style="color:#536a75">Stop emails for this spot</a> · <a href="{unsub_all_url}" style="color:#536a75">Unsubscribe from everything</a><br>
Shorebite · {addr}</p>
</div></body></html>"""


def week_table(s, tz, events, days):
    rows = []
    for d in days:
        evs = [(dt.datetime.fromtimestamp(t, tz), v, k) for t, v, k in events
               if dt.datetime.fromtimestamp(t, tz).date() == d]
        cells = " &nbsp; ".join(
            f'<span style="color:{"#0b5c7a" if k == "H" else "#b5651d"}">{"H" if k == "H" else "L"}</span> '
            f'{build.clock(w)} <span style="color:#536a75">{build.ft(v)}</span>' for w, v, k in evs)
        rows.append(f'<tr><td style="padding:6px 10px 6px 0;white-space:nowrap;vertical-align:top;font-weight:600">'
                    f'{d.strftime("%a %b %-d")}</td><td style="padding:6px 0;font-size:15px">{cells}</td></tr>')
    return f'<table style="border-collapse:collapse;width:100%;border-top:1px solid #d6e3e9">{"".join(rows)}</table>'


def weekend_lows(s, tz, events, days):
    """Daylight low tides below 0.0 ft on Saturday or Sunday in the coming days."""
    out = []
    for d in days:
        if d.weekday() not in (5, 6):
            continue
        rise, sset = sun(s["lat"], s["lng"], d, tz)
        if not rise:
            continue
        for t, v, k in events:
            if k == "L" and v < 0 and rise.timestamp() <= t <= sset.timestamp():
                out.append((dt.datetime.fromtimestamp(t, tz), v))
    return sorted(out, key=lambda p: p[1])


def station_block(s, sub):
    tz, events, days = build.load_station(s)
    today = dt.datetime.now(tz).date()
    days = [d for d in days if d >= today][:7]
    url = f"{SITE}/{s['path']}"
    lows = weekend_lows(s, tz, events, days) if sub["lows"] else []
    parts = [f'<h2 style="font-size:18px;margin:22px 0 6px"><a href="{url}" style="color:#11232c">{esc(s["pretty"])}</a></h2>']
    if lows:
        best = "; ".join(f'{w.strftime("%A")} {build.clock(w)} ({build.ft(v)})' for w, v in lows[:3])
        parts.append(f'<p style="background:#d9f1f8;border-radius:10px;padding:10px 12px;margin:6px 0 10px">'
                     f'<b>Minus tides this weekend:</b> {esc(best)}. Good timing for tide pools and clamming.</p>')
    if sub["weekly"]:
        parts.append(week_table(s, tz, events, days))
    parts.append(f'<p style="margin:10px 0 0"><a href="{url}" style="color:#0b5c7a;font-weight:600">'
                 f'Today\'s chart, currents, fishing times and the marine forecast →</a></p>')
    return "".join(parts), bool(lows)


def unsub_links(api, sub):
    return (f"{SITE}/alerts/?unsub={sub['unsub']}", f"{SITE}/alerts/?unsub={sub['unsub_all']}",
            f"{api}/unsubscribe?t={sub['unsub_all']}")


def message(to, subject, title, inner, sub, api):
    one, everything, one_click = unsub_links(api, sub)
    return {"from": FROM, "to": [to], "subject": subject, "html": shell(title, inner, one, everything),
            "headers": {"List-Unsubscribe": f"<{one_click}>", "List-Unsubscribe-Post": "List-Unsubscribe=One-Click"}}


# ---------- modes ----------

def weekly(subs, by_id, api):
    out = []
    by_email = {}
    for sub in subs:
        if (sub["weekly"] or sub["lows"]) and sub["station"] in by_id:
            by_email.setdefault(sub["email"], []).append(sub)
    for email, mine in by_email.items():
        blocks, any_lows = [], False
        for sub in mine:
            try:
                block, has_lows = station_block(by_id[sub["station"]], sub)
            except FileNotFoundError:
                continue
            if sub["weekly"] or has_lows:  # lows-only subscribers just get the heads-up weeks
                blocks.append(block)
                any_lows |= has_lows
        if not blocks:
            continue
        name = by_id[mine[0]["station"]]["pretty"] if len(mine) == 1 else "your spots"
        subject = f"Tides this week: {name}" + (" (minus tides this weekend)" if any_lows else "")
        out.append(message(email, subject, f"Tides for the week ahead", "".join(blocks), mine[0], api))
    return out, []


def warnings(subs, sent, by_id, api):
    zones = json.loads((ROOT / "collector" / "marine_zones.json").read_text())
    done = {(r["email"], r["alert"]) for r in sent}
    cache = {}

    def active(s):
        found = {}
        z = zones.get(s["id"])
        urls = [f"https://api.weather.gov/alerts/active?point={s['lat']:.4f},{s['lng']:.4f}"]
        if z:
            urls.append(f"https://api.weather.gov/alerts/active?zone={z[0]}")
        for u in urls:
            if u not in cache:
                try:
                    cache[u] = http(u, headers={"Accept": "application/geo+json"}).get("features", [])
                except Exception as ex:
                    print(f"alerts fetch failed {u}: {ex}", file=sys.stderr)
                    cache[u] = []
            for f in cache[u]:
                p = f["properties"]
                if p.get("event") in EVENTS and p.get("status") == "Actual" and p.get("messageType") != "Cancel":
                    found[p["id"]] = p
        return found.values()

    out, record = [], []
    by_email = {}
    for sub in subs:
        if sub["warn"] and sub["station"] in by_id:
            by_email.setdefault(sub["email"], []).append(sub)
    for email, mine in by_email.items():
        items = []
        for sub in mine:
            s = by_id[sub["station"]]
            for p in active(s):
                refs = {r.get("identifier") for r in p.get("references") or []}
                # Updates and extensions of an alert we already sent come with a new id that references the old one.
                if (email, p["id"]) in done or any((email, r) in done for r in refs):
                    record.append([email, p["id"]])
                    continue
                if any(p["id"] == q["id"] for _, q in items):
                    continue
                items.append((s, p))
                record.append([email, p["id"]])
        if not items:
            continue
        blocks = []
        for s, p in items:
            ends = p.get("ends") or p.get("expires")
            until = ""
            if ends:
                tz = build.zone_for(s)
                until = " until " + dt.datetime.fromisoformat(ends).astimezone(tz).strftime("%a %-I:%M %p")
            desc = esc((p.get("description") or "").strip()).replace("\n\n", "<br><br>").replace("\n", " ")
            desc = re.sub(r"\* ([A-Z ]+)\.\.\.", lambda m: f"<b>{m.group(1).capitalize()}:</b> ", desc)
            blocks.append(f'<div style="border-left:4px solid #d6336c;padding:4px 0 4px 12px;margin:14px 0">'
                          f'<p style="margin:0;font-weight:700">{esc(p["event"])}{esc(until)}</p>'
                          f'<p style="margin:2px 0 8px;color:#536a75;font-size:14px">Near '
                          f'<a href="{SITE}/{s["path"]}" style="color:#0b5c7a">{esc(s["pretty"])}</a>. '
                          f'{esc(p.get("areaDesc") or "")}</p>'
                          f'<p style="margin:0;font-size:15px">{desc[:1500]}</p></div>')
        first = items[0][1]["event"]
        subject = first + (f" and {len(items) - 1} more" if len(items) > 1 else "") + f" near {items[0][0]['pretty']}"
        out.append(message(email, subject, "Weather warning for your spot", "".join(blocks), mine[0], api))
    return out, record


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("mode", choices=["weekly", "warnings", "ids"])
    ap.add_argument("--dry-run", action="store_true", help="print the emails instead of sending")
    ap.add_argument("--to", help="send only the first email, to this address (testing)")
    args = ap.parse_args()
    api = os.environ["ALERTS_API"].rstrip("/")
    if not os.environ.get("MAIL_ADDRESS") and not args.dry_run and args.mode != "ids":
        sys.exit("MAIL_ADDRESS is not set: US law requires a postal address in every email")
    auth = {"Authorization": f"Bearer {os.environ['ADMIN_TOKEN']}"}
    data = http(f"{api}/admin/subs", headers=auth)
    if args.mode == "ids":
        print(",".join(sorted({s["station"] for s in data["subs"]})))
        return
    by_id = stations()
    if args.mode == "weekly":
        emails, record = weekly(data["subs"], by_id, api)
    else:
        emails, record = warnings(data["subs"], data["sent"], by_id, api)
    print(f"{args.mode}: {len(data['subs'])} subscriptions, {len(emails)} emails to send")
    if args.to:
        emails, record = [dict(emails[0], to=[args.to])] if emails else [], []
    if args.dry_run:
        for e in emails[:3]:
            print(e["to"], e["subject"])
        return
    key = os.environ["RESEND_API_KEY"]
    for i in range(0, len(emails), 100):
        http("https://api.resend.com/emails/batch", emails[i:i + 100], {"Authorization": f"Bearer {key}"})
        time.sleep(1)
    if record:
        http(f"{api}/admin/sent", record, auth)
    print(f"sent {len(emails)}")


if __name__ == "__main__":
    main()
