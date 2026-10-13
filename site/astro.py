"""Sunrise/sunset and moon phase, computed locally (no API).

Sun: the standard sunrise equation with -0.833 degrees for refraction and the sun's radius;
good to about a minute at US latitudes. Moon: age since a known new moon, good to a few hours,
which is plenty for a phase name and illumination.
"""

import datetime as dt
import functools
import math

J2000 = dt.date(2000, 1, 1)
SYNODIC = 29.530588853
NEW_MOON = dt.datetime(2000, 1, 6, 18, 14, tzinfo=dt.timezone.utc)
PHASES = [(1.84, "New moon"), (5.53, "Waxing crescent"), (9.22, "First quarter"), (12.91, "Waxing gibbous"),
          (16.61, "Full moon"), (20.30, "Waning gibbous"), (23.99, "Last quarter"), (27.68, "Waning crescent"),
          (99, "New moon")]


def _jd_to_dt(jd):
    return dt.datetime(1970, 1, 1, tzinfo=dt.timezone.utc) + dt.timedelta(seconds=(jd - 2440587.5) * 86400)


def sun(lat, lng, day, tz):
    """(sunrise, sunset) as local datetimes; None for either when the sun doesn't rise or set."""
    rad = math.radians
    n = (day - J2000).days + 0.0008
    jstar = n - lng / 360
    m = (357.5291 + 0.98560028 * jstar) % 360
    c = 1.9148 * math.sin(rad(m)) + 0.02 * math.sin(rad(2 * m)) + 0.0003 * math.sin(rad(3 * m))
    lam = (m + c + 180 + 102.9372) % 360
    transit = 2451545.0 + jstar + 0.0053 * math.sin(rad(m)) - 0.0069 * math.sin(rad(2 * lam))
    decl = math.asin(math.sin(rad(lam)) * math.sin(rad(23.4397)))
    cosw = (math.sin(rad(-0.833)) - math.sin(rad(lat)) * math.sin(decl)) / (math.cos(rad(lat)) * math.cos(decl))
    if cosw > 1 or cosw < -1:
        return None, None
    w = math.degrees(math.acos(cosw))
    rise = _jd_to_dt(transit - w / 360).astimezone(tz)
    sset = _jd_to_dt(transit + w / 360).astimezone(tz)
    return rise, sset


_MOON_RADEC = {}


def _moon_radec(ts):
    """Moon (right ascension, sin dec, cos dec) at a unix time. Same for every station, so cached:
    the moon_times grid lands on 5-minute marks shared by all stations."""
    hit = _MOON_RADEC.get(ts)
    if hit:
        return hit
    rad = math.radians
    d = ts / 86400 + 2440587.5 - 2451545.0
    L = rad(218.316 + 13.176396 * d)
    M = rad(134.963 + 13.064993 * d)
    F = rad(93.272 + 13.229350 * d)
    lon = L + rad(6.289) * math.sin(M)
    b = rad(5.128) * math.sin(F)
    e = rad(23.4397)
    ra = math.atan2(math.sin(lon) * math.cos(e) - math.tan(b) * math.sin(e), math.cos(lon))
    dec = math.asin(math.sin(b) * math.cos(e) + math.cos(b) * math.sin(e) * math.sin(lon))
    hit = _MOON_RADEC[ts] = (ra, math.sin(dec), math.cos(dec), rad(280.16 + 360.9856235 * d))
    return hit


def _moon_pos(ts, lat, lng):
    """Moon altitude (degrees) and hour angle (radians) at a unix time. Low-precision series
    (as in suncalc), good to about a degree, which puts rise/set/transit within a few minutes."""
    ra, sdec, cdec, gst = _moon_radec(ts)
    H = gst + math.radians(lng) - ra
    phi = math.radians(lat)
    alt = math.asin(math.sin(phi) * sdec + math.cos(phi) * cdec * math.cos(H))
    return math.degrees(alt), H


@functools.lru_cache(maxsize=4096)
def moon_times(lat, lng, day, tz, step=300):
    """Moonrise, moonset, overhead (upper transit) and underfoot (lower transit) for a local day.
    Returns a dict of lists of local datetimes; a day can have none or one of each."""
    t0 = dt.datetime.combine(day, dt.time(0), tz).timestamp()
    out = {"rise": [], "set": [], "over": [], "under": []}
    prev = None
    t = t0
    while t <= t0 + 86400:
        alt, H = _moon_pos(t, lat, lng)
        cur = (alt - 0.13, math.sin(H), math.cos(H))
        if prev:
            a0, s0, c0 = prev
            frac = lambda x0, x1: x0 / (x0 - x1) if x0 != x1 else 0
            if a0 < 0 <= cur[0]:
                out["rise"].append(t - step + frac(a0, cur[0]) * step)
            elif a0 >= 0 > cur[0]:
                out["set"].append(t - step + frac(a0, cur[0]) * step)
            # Hour angle passes 0 (overhead) or pi (underfoot): sin(H) changes sign.
            if (s0 < 0 <= cur[1]) or (s0 > 0 >= cur[1]):
                key = "over" if c0 + cur[2] > 0 else "under"
                out[key].append(t - step + frac(s0, cur[1]) * step)
        prev = cur
        t += step
    return {k: [dt.datetime.fromtimestamp(x, tz) for x in v if t0 <= x < t0 + 86400] for k, v in out.items()}


def moon(when):
    """(phase name, illuminated percent) at a timezone-aware datetime."""
    age = ((when - NEW_MOON).total_seconds() / 86400) % SYNODIC
    name = next(label for limit, label in PHASES if age < limit)
    lit = round(50 * (1 - math.cos(2 * math.pi * age / SYNODIC)))
    return name, lit
