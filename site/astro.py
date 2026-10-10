"""Sunrise/sunset and moon phase, computed locally (no API).

Sun: the standard sunrise equation with -0.833 degrees for refraction and the sun's radius;
good to about a minute at US latitudes. Moon: age since a known new moon, good to a few hours,
which is plenty for a phase name and illumination.
"""

import datetime as dt
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


def moon(when):
    """(phase name, illuminated percent) at a timezone-aware datetime."""
    age = ((when - NEW_MOON).total_seconds() / 86400) % SYNODIC
    name = next(label for limit, label in PHASES if age < limit)
    lit = round(50 * (1 - math.cos(2 * math.pi * age / SYNODIC)))
    return name, lit
