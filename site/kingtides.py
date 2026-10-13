"""King tides: each spot's highest predicted high tides over the next 12 months, grouped into windows.

"King tide" isn't a scientific term; it's the name the state photo projects use for the year's highest
tides. Here a spot's king tide days are the days whose highest tide is in its top 5% for the coming
12 months (about 18 days a year), and neighbouring days (at most one ordinary day between) form a window.
Working from each spot's own predictions means the season comes out right everywhere: winter on the
Pacific coast, fall in Florida and the Southeast, summer and winter in Hawaii.
"""

import datetime as dt

TOP = 0.95  # daily highest tide at or above this percentile of the next 12 months = a king tide day


def daily_highs(raws, tz):
    """{date: (datetime, height)} of each day's highest high tide, from {year: [["MM-DD HH:MM", v, "H"|"L"], ...]}."""
    out = {}
    for year, raw in raws.items():
        for t, v, k in raw:
            if k != "H":
                continue
            try:
                w = dt.datetime.fromisoformat(f"{year}-{t}").replace(tzinfo=tz)
            except ValueError:
                continue
            d = w.date()
            if d not in out or v > out[d][1]:
                out[d] = (w, v)
    return out


def windows_for(raws, tz, today):
    """This spot's king tide windows from today through the next 12 months, or None without enough data.

    Returns {"cut": height, "days": {date}, "windows": [(first, last, peak_dt, peak_v)], "top": (dt, v),
    "typical": median daily highest tide}."""
    highs = daily_highs(raws, tz)
    end = today + dt.timedelta(days=365)
    days = {d: x for d, x in highs.items() if today <= d < end}
    if len(days) < 300:  # need (nearly) a full year for the percentile to mean "the year's highest"
        return None
    vals = sorted(v for _, v in days.values())
    cut = vals[int(TOP * (len(vals) - 1))]
    kdays = sorted(d for d, (_, v) in days.items() if v >= cut)
    wins = []
    for d in kdays:
        if wins and (d - wins[-1][-1]).days <= 2:
            wins[-1].append(d)
        else:
            wins.append([d])
    out = []
    for w in wins:
        peak_d = max(w, key=lambda d: days[d][1])
        out.append((w[0], w[-1], days[peak_d][0], days[peak_d][1]))
    top = max(days.values(), key=lambda x: x[1])
    return {"cut": cut, "days": set(kdays), "windows": out, "top": top, "typical": vals[len(vals) // 2]}


def state_windows(spots, share=0.25):
    """Statewide windows: runs of dates when at least `share` of the state's spots have a king tide day.

    spots: list of windows_for() results. Returns [(first, last, peak_date, spots_on_peak, total)]."""
    total = len(spots)
    if not total:
        return []
    count = {}
    for s in spots:
        for d in s["days"]:
            count[d] = count.get(d, 0) + 1
    hot = sorted(d for d, n in count.items() if n >= share * total)
    runs = []
    for d in hot:
        if runs and (d - runs[-1][-1]).days <= 2:
            runs[-1].append(d)
        else:
            runs.append([d])
    out = []
    for r in runs:
        peak = max(r, key=lambda d: count[d])
        out.append((r[0], r[-1], peak, count[peak], total))
    return out


def span(a, b):
    """'Nov 23–27', 'Nov 30–Dec 2', 'Dec 31, 2026–Jan 2, 2027' ('Nov 25' for one day)."""
    if a == b:
        return f"{a:%b} {a.day}"
    if a.year != b.year:
        return f"{a:%b} {a.day}, {a.year}–{b:%b} {b.day}, {b.year}"
    if a.month == b.month:
        return f"{a:%b} {a.day}–{b.day}"
    return f"{a:%b} {a.day}–{b:%b} {b.day}"


def season_label(today):
    """'2026–27'."""
    return f"{today.year}–{(today.year + 1) % 100:02d}"


def ics(name, wins, url, stamp):
    """All-day calendar events for statewide windows."""
    lines = ["BEGIN:VCALENDAR", "VERSION:2.0", "PRODID:-//Shorebite//King tides//EN", "CALSCALE:GREGORIAN",
             f"X-WR-CALNAME:King tides: {name}"]
    for a, b, peak, n, total in wins:
        lines += ["BEGIN:VEVENT", f"UID:kingtide-{name.lower().replace(' ', '-')}-{a:%Y%m%d}@shorebite.com",
                  f"DTSTAMP:{stamp:%Y%m%dT%H%M%SZ}", f"DTSTART;VALUE=DATE:{a:%Y%m%d}",
                  f"DTEND;VALUE=DATE:{b + dt.timedelta(days=1):%Y%m%d}",
                  f"SUMMARY:King tides in {name}",
                  f"DESCRIPTION:Highest predicted tides of the year at {n} of {total} spots on {peak:%b} {peak.day}. "
                  f"Times for your spot: {url}",
                  f"URL:{url}", "TRANSP:TRANSPARENT", "END:VEVENT"]
    lines.append("END:VCALENDAR")
    return "".join(fold(x) for x in lines)


def fold(line):
    """iCalendar lines are at most 75 octets; longer ones continue on lines starting with a space."""
    b, out = line.encode(), []
    while len(b) > 75:
        cut = 75 if not out else 74
        while (b[cut] & 0xC0) == 0x80:  # don't split a UTF-8 character
            cut -= 1
        out.append(b[:cut].decode())
        b = b[cut:]
    out.append(b.decode())
    return "\r\n ".join(out) + "\r\n"
