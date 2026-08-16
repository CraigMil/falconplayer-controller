"""World clock display — local time, weather, and a skyline silhouette per city."""

from __future__ import annotations

import random
import time
from datetime import datetime
from zoneinfo import ZoneInfo

import httpx
from PIL import Image, ImageDraw

from ..canvas import Color, Frame

# ------------------------------------------------------------------ cities

CITIES: list[dict] = [
    {"name": "Pune",        "tz": "Asia/Kolkata",       "lat": 18.5204,  "lon": 73.8567},
    {"name": "New York",    "tz": "America/New_York",   "lat": 40.7128,  "lon": -74.0060},
    {"name": "Seville",     "tz": "Europe/Madrid",      "lat": 37.3891,  "lon": -5.9845},
    {"name": "Tokyo",       "tz": "Asia/Tokyo",         "lat": 35.6762,  "lon": 139.6503},
    {"name": "Bangkok",     "tz": "Asia/Bangkok",       "lat": 13.7563,  "lon": 100.5018},
    {"name": "London",      "tz": "Europe/London",      "lat": 51.5072,  "lon": -0.1276},
    {"name": "Paris",       "tz": "Europe/Paris",       "lat": 48.8566,  "lon": 2.3522},
    {"name": "Sydney",      "tz": "Australia/Sydney",   "lat": -33.8688, "lon": 151.2093},
    {"name": "Dubai",       "tz": "Asia/Dubai",         "lat": 25.2048,  "lon": 55.2708},
    {"name": "Cairo",       "tz": "Africa/Cairo",       "lat": 30.0444,  "lon": 31.2357},
    {"name": "Moscow",      "tz": "Europe/Moscow",      "lat": 55.7558,  "lon": 37.6173},
    {"name": "Beijing",     "tz": "Asia/Shanghai",      "lat": 39.9042,  "lon": 116.4074},
    {"name": "Rio de Janeiro", "tz": "America/Sao_Paulo", "lat": -22.9068, "lon": -43.1729},
    {"name": "Mexico City", "tz": "America/Mexico_City", "lat": 19.4326, "lon": -99.1332},
    {"name": "Toronto",     "tz": "America/Toronto",    "lat": 43.6532,  "lon": -79.3832},
    {"name": "Nairobi",     "tz": "Africa/Nairobi",     "lat": -1.2921,  "lon": 36.8219},
    {"name": "Reykjavik",   "tz": "Atlantic/Reykjavik", "lat": 64.1466,  "lon": -21.9426},
    {"name": "Singapore",   "tz": "Asia/Singapore",     "lat": 1.3521,   "lon": 103.8198},
    {"name": "Honolulu",    "tz": "Pacific/Honolulu",   "lat": 21.3069,  "lon": -157.8583},
    {"name": "Los Angeles", "tz": "America/Los_Angeles", "lat": 34.0522, "lon": -118.2437},
    {"name": "Berlin",      "tz": "Europe/Berlin",      "lat": 52.5200,  "lon": 13.4050},
    {"name": "Rome",        "tz": "Europe/Rome",        "lat": 41.9028,  "lon": 12.4964},
    {"name": "Athens",      "tz": "Europe/Athens",      "lat": 37.9838,  "lon": 23.7275},
    {"name": "Istanbul",    "tz": "Europe/Istanbul",    "lat": 41.0082,  "lon": 28.9784},
    {"name": "Amsterdam",   "tz": "Europe/Amsterdam",   "lat": 52.3676,  "lon": 4.9041},
    {"name": "Vienna",      "tz": "Europe/Vienna",      "lat": 48.2082,  "lon": 16.3738},
    {"name": "Lisbon",      "tz": "Europe/Lisbon",      "lat": 38.7223,  "lon": -9.1393},
    {"name": "Seoul",       "tz": "Asia/Seoul",         "lat": 37.5665,  "lon": 126.9780},
    {"name": "Hong Kong",   "tz": "Asia/Hong_Kong",     "lat": 22.3193,  "lon": 114.1694},
    {"name": "Mumbai",      "tz": "Asia/Kolkata",       "lat": 19.0760,  "lon": 72.8777},
    {"name": "Jakarta",     "tz": "Asia/Jakarta",       "lat": -6.2088,  "lon": 106.8456},
    {"name": "Kuala Lumpur", "tz": "Asia/Kuala_Lumpur", "lat": 3.1390,   "lon": 101.6869},
    {"name": "Doha",        "tz": "Asia/Qatar",         "lat": 25.2854,  "lon": 51.5310},
    {"name": "Jerusalem",   "tz": "Asia/Jerusalem",     "lat": 31.7683,  "lon": 35.2137},
    {"name": "Auckland",    "tz": "Pacific/Auckland",   "lat": -36.8485, "lon": 174.7633},
    {"name": "Buenos Aires", "tz": "America/Argentina/Buenos_Aires",
     "lat": -34.6037, "lon": -58.3816},
    {"name": "Lima",        "tz": "America/Lima",       "lat": -12.0464, "lon": -77.0428},
    {"name": "Santiago",    "tz": "America/Santiago",   "lat": -33.4489, "lon": -70.6693},
    {"name": "Lagos",       "tz": "Africa/Lagos",       "lat": 6.5244,   "lon": 3.3792},
    {"name": "Cape Town",   "tz": "Africa/Johannesburg", "lat": -33.9249, "lon": 18.4241},
    {"name": "Marrakech",   "tz": "Africa/Casablanca",  "lat": 31.6295,  "lon": -7.9811},
    {"name": "San Francisco", "tz": "America/Los_Angeles", "lat": 37.7749, "lon": -122.4194},
    {"name": "Chicago",     "tz": "America/Chicago",    "lat": 41.8781,  "lon": -87.6298},
    {"name": "Vancouver",   "tz": "America/Vancouver",  "lat": 49.2827,  "lon": -123.1207},
    {"name": "Denver",      "tz": "America/Denver",     "lat": 39.7392,  "lon": -104.9903},
    {"name": "Miami",       "tz": "America/New_York",   "lat": 25.7617,  "lon": -80.1918},
    {"name": "Havana",      "tz": "America/Havana",     "lat": 23.1136,  "lon": -82.3666},
]

WEATHER_URL = "https://api.open-meteo.com/v1/forecast"

# WMO weather codes -> (label, is_severe)
_WEATHER_CODES: dict[int, tuple[str, bool]] = {
    0: ("Clear", False),
    1: ("Mostly Clear", False),
    2: ("Partly Cloudy", False),
    3: ("Overcast", False),
    45: ("Fog", False),
    48: ("Fog", False),
    51: ("Light Drizzle", False),
    53: ("Drizzle", False),
    55: ("Heavy Drizzle", False),
    56: ("Freezing Drizzle", True),
    57: ("Freezing Drizzle", True),
    61: ("Light Rain", False),
    63: ("Rain", False),
    65: ("Heavy Rain", True),
    66: ("Freezing Rain", True),
    67: ("Freezing Rain", True),
    71: ("Light Snow", False),
    73: ("Snow", False),
    75: ("Heavy Snow", True),
    77: ("Snow Grains", False),
    80: ("Rain Showers", False),
    81: ("Rain Showers", False),
    82: ("Violent Showers", True),
    85: ("Snow Showers", False),
    86: ("Snow Showers", True),
    95: ("Thunderstorm", True),
    96: ("Thunderstorm/Hail", True),
    99: ("Severe Thunderstorm", True),
}


def _weather_info(code: int) -> tuple[str, bool]:
    return _WEATHER_CODES.get(code, ("Unknown", False))


# ------------------------------------------------------------------ data fetch

_CACHE_TTL = 600  # seconds
_cache: dict[str, tuple[float, dict]] = {}


def fetch_weather(city: dict) -> dict:
    """Fetch current conditions + today's high for a city, cached for 10 minutes."""
    key = city["name"]
    now = time.time()
    cached = _cache.get(key)
    if cached and now - cached[0] < _CACHE_TTL:
        return cached[1]

    params = {
        "latitude": city["lat"],
        "longitude": city["lon"],
        "current": "temperature_2m,relative_humidity_2m,weather_code",
        "daily": "temperature_2m_max",
        "temperature_unit": "fahrenheit",
        "timezone": city["tz"],
        "forecast_days": 1,
    }
    data: dict = {}
    try:
        resp = httpx.get(WEATHER_URL, params=params, timeout=10)
        resp.raise_for_status()
        body = resp.json()
        current = body.get("current", {})
        daily = body.get("daily", {})
        code = int(current.get("weather_code", 0))
        label, severe = _weather_info(code)
        data = {
            "temp_now": current.get("temperature_2m"),
            "humidity": current.get("relative_humidity_2m"),
            "temp_high": (daily.get("temperature_2m_max") or [None])[0],
            "condition": label,
            "alert": label if severe else None,
        }
    except Exception:
        data = {
            "temp_now": None, "humidity": None, "temp_high": None,
            "condition": "Unavailable", "alert": None,
        }

    _cache[key] = (now, data)
    return data


# ------------------------------------------------------------------ sky palette

def _sky_colors(hour: int) -> tuple[Color, Color]:
    """Return (top, bottom) sky gradient colors for the given local hour (0-23)."""
    if 6 <= hour < 8:      # dawn
        return (30, 30, 70), (255, 150, 90)
    if 8 <= hour < 17:     # day
        return (60, 140, 220), (170, 215, 240)
    if 17 <= hour < 19:    # dusk
        return (40, 30, 80), (255, 110, 70)
    if 19 <= hour < 21:    # early night
        return (10, 10, 35), (60, 40, 80)
    return (4, 4, 18), (18, 18, 45)   # deep night


def _is_night(hour: int) -> bool:
    # Matches the "early night"/"deep night" boundary in _sky_colors so the sky
    # color and the sun-vs-moon choice never disagree (a sun on a black sky reads
    # as a rendering bug, not a design choice).
    return hour < 6 or hour >= 19


def _jitter_color(color: Color, rng: random.Random, spread: int = 16) -> Color:
    return tuple(max(0, min(255, c + rng.randint(-spread, spread))) for c in color)


# ------------------------------------------------------------------ skylines
# Each skyline is a list of (x, width, height) building blocks drawn on top
# of a ground strip, plus an optional landmark polygon drawn separately.

SKY_TOP_Y = 0
GROUND_Y = 150  # skyline sits with its base on this line


def _building_row(
    frame: Frame, blocks: list[tuple[int, int, int]], color: Color, lit: Color | None, hour: int,
) -> None:
    night = _is_night(hour)
    for x, w, h in blocks:
        y = GROUND_Y - h
        frame.rect(x, y, w, h, color)
        if night and lit:
            # a few lit windows
            for wy in range(y + 6, GROUND_Y - 4, 10):
                for wx in range(x + 3, x + w - 3, 7):
                    if (wx + wy) % 5 != 0:
                        frame.rect(wx, wy, 2, 3, lit)


def _skyline_new_york(frame: Frame, hour: int, silhouette: Color) -> None:
    blocks = [
        (4, 14, 55), (20, 10, 40), (32, 16, 70), (50, 12, 50),
        (64, 18, 95), (84, 10, 60), (96, 14, 80), (112, 20, 100),
        (134, 12, 65), (148, 16, 85), (166, 10, 45), (178, 12, 60),
    ]
    _building_row(frame, blocks, silhouette, (255, 220, 120), hour)
    # Empire State Building spire — tallest, centered-ish
    spire_x, spire_w, spire_h = 64, 18, 95
    tip = (spire_x + spire_w // 2, GROUND_Y - spire_h - 22)
    frame.polygon([
        (spire_x + 4, GROUND_Y - spire_h), (spire_x + spire_w - 4, GROUND_Y - spire_h),
        (spire_x + spire_w // 2 + 3, GROUND_Y - spire_h - 14),
        (spire_x + spire_w // 2 - 3, GROUND_Y - spire_h - 14),
    ], silhouette)
    frame.line(tip[0], tip[1], tip[0], GROUND_Y - spire_h - 14, color=silhouette, width=2)


def _skyline_tokyo(frame: Frame, hour: int, silhouette: Color) -> None:
    blocks = [
        (4, 16, 50), (22, 12, 65), (38, 14, 40), (54, 10, 55),
        (110, 14, 60), (126, 18, 45), (146, 12, 70), (162, 16, 50), (180, 10, 40),
    ]
    _building_row(frame, blocks, silhouette, (255, 210, 150), hour)
    # Tokyo Tower — lattice silhouette, red/white by day, lit red at night
    tower_color = (200, 50, 40) if not _is_night(hour) else (255, 70, 60)
    base_x, base_w, h = 80, 26, 110
    top = (base_x + base_w // 2, GROUND_Y - h)
    frame.polygon([
        (base_x, GROUND_Y), (base_x + base_w, GROUND_Y),
        (top[0] + 3, top[1] + 18), (top[0] - 3, top[1] + 18),
    ], tower_color)
    frame.polygon([
        (top[0] - 3, top[1] + 18), (top[0] + 3, top[1] + 18), top,
    ], tower_color)
    white = (240, 240, 240)
    frame.line(base_x + 4, GROUND_Y - 30, base_x + base_w - 4, GROUND_Y - 30, color=white, width=2)
    frame.line(base_x + 8, GROUND_Y - 60, base_x + base_w - 8, GROUND_Y - 60, color=white, width=2)


def _skyline_seville(frame: Frame, hour: int, silhouette: Color) -> None:
    blocks = [
        (6, 20, 30), (30, 16, 24), (140, 18, 28), (162, 16, 22), (178, 14, 26),
    ]
    _building_row(frame, blocks, silhouette, (255, 200, 120), hour)
    # La Giralda — bell tower with a stepped belfry, warm terracotta silhouette
    bx, bw, h = 82, 24, 42
    frame.rect(bx, GROUND_Y - h, bw, h, silhouette)
    frame.rect(bx - 3, GROUND_Y - h - 8, bw + 6, 8, silhouette)
    frame.rect(bx + 4, GROUND_Y - h - 20, bw - 8, 12, silhouette)
    frame.polygon([
        (bx + 4, GROUND_Y - h - 20), (bx + bw - 4, GROUND_Y - h - 20),
        (bx + bw // 2, GROUND_Y - h - 32),
    ], silhouette)
    # small arched windows in the belfry
    if not _is_night(hour):
        frame.rect(bx + 9, GROUND_Y - h + 8, 6, 10, (255, 230, 190))
        frame.rect(bx + bw - 15, GROUND_Y - h + 8, 6, 10, (255, 230, 190))


def _skyline_bangkok(frame: Frame, hour: int, silhouette: Color) -> None:
    blocks = [
        (4, 14, 45), (20, 10, 60), (140, 12, 55), (156, 16, 40), (174, 10, 65),
    ]
    _building_row(frame, blocks, silhouette, (255, 215, 140), hour)
    # Wat Arun style stepped prang (stupa) — tiered silhouette with a spire
    cx = 96
    tiers = [(60, 14), (46, 26), (34, 42), (22, 58), (10, 78)]
    for w, h in tiers:
        frame.polygon([
            (cx - w // 2, GROUND_Y - h), (cx + w // 2, GROUND_Y - h),
            (cx, GROUND_Y - h - 16),
        ], silhouette)
    frame.line(cx, GROUND_Y - 78 - 16, cx, GROUND_Y - 110, color=silhouette, width=2)


def _skyline_pune(frame: Frame, hour: int, silhouette: Color) -> None:
    # Rolling Sahyadri hills behind a low fort wall (Shaniwar Wada style gate)
    hill_color = tuple(max(0, c - 18) for c in silhouette)
    hills = [
        (0, GROUND_Y), (0, 108), (48, 130), (96, 96), (150, 132), (192, 112), (192, GROUND_Y),
    ]
    frame.polygon(hills, hill_color)
    blocks = [
        (10, 14, 30), (26, 10, 22), (150, 12, 26), (166, 16, 34),
    ]
    _building_row(frame, blocks, silhouette, (255, 200, 130), hour)
    # Fort gate — stepped crenellated silhouette
    gx, gw, h = 76, 40, 42
    frame.rect(gx, GROUND_Y - h, gw, h, silhouette)
    for i in range(gx, gx + gw, 8):
        frame.rect(i, GROUND_Y - h - 6, 5, 6, silhouette)
    frame.rect(gx + gw // 2 - 6, GROUND_Y - h - 4, 12, 20, (60, 30, 15))


def _skyline_paris(frame: Frame, hour: int, silhouette: Color) -> None:
    blocks = [
        (4, 16, 30), (22, 12, 24), (150, 14, 26), (168, 16, 32),
    ]
    _building_row(frame, blocks, silhouette, (255, 210, 140), hour)
    # Eiffel Tower — tapering lattice legs to a spire
    cx, base_w, h = 96, 46, 100
    frame.polygon([
        (cx - base_w // 2, GROUND_Y), (cx - 6, GROUND_Y - h + 20),
        (cx + 6, GROUND_Y - h + 20), (cx + base_w // 2, GROUND_Y),
    ], silhouette)
    frame.polygon([
        (cx - 6, GROUND_Y - h + 20), (cx - 2, GROUND_Y - h),
        (cx + 2, GROUND_Y - h), (cx + 6, GROUND_Y - h + 20),
    ], silhouette)
    frame.line(cx, GROUND_Y - h, cx, GROUND_Y - h - 12, color=silhouette, width=2)
    leg_x0, leg_x1 = cx - base_w // 2 + 4, cx + base_w // 2 - 4
    frame.line(leg_x0, GROUND_Y - 34, leg_x1, GROUND_Y - 34, color=silhouette, width=2)


def _skyline_london(frame: Frame, hour: int, silhouette: Color) -> None:
    blocks = [
        (6, 18, 32), (30, 14, 24), (140, 16, 30), (160, 14, 22),
    ]
    _building_row(frame, blocks, silhouette, (255, 210, 140), hour)
    # Big Ben — clock tower with a pointed roof
    bx, bw, h = 84, 22, 80
    frame.rect(bx, GROUND_Y - h, bw, h, silhouette)
    frame.polygon([
        (bx - 2, GROUND_Y - h), (bx + bw + 2, GROUND_Y - h), (bx + bw // 2, GROUND_Y - h - 22),
    ], silhouette)
    face = (255, 235, 190) if not _is_night(hour) else (255, 220, 120)
    frame.ellipse(bx + bw // 2 - 6, GROUND_Y - h + 10, 12, 12, face)


def _skyline_sydney(frame: Frame, hour: int, silhouette: Color) -> None:
    blocks = [
        (4, 16, 45), (22, 12, 60), (150, 14, 50), (168, 16, 38),
    ]
    _building_row(frame, blocks, silhouette, (255, 210, 140), hour)
    # Opera House — overlapping curved shell silhouettes
    base_y = GROUND_Y - 4
    for i, (w, h) in enumerate([(30, 34), (24, 26), (18, 18)]):
        cx = 70 + i * 20
        frame.polygon([
            (cx - w // 2, base_y), (cx + w // 2, base_y), (cx + w // 4, base_y - h),
        ], silhouette)
    frame.rect(60, base_y - 2, 70, 6, silhouette)


def _skyline_dubai(frame: Frame, hour: int, silhouette: Color) -> None:
    blocks = [
        (4, 16, 40), (22, 12, 55), (140, 14, 45), (158, 16, 65), (176, 10, 35),
    ]
    _building_row(frame, blocks, silhouette, (255, 220, 150), hour)
    # Burj Khalifa — tall tapering spike
    cx, base_w, h = 96, 26, 130
    frame.polygon([
        (cx - base_w // 2, GROUND_Y), (cx - 3, GROUND_Y - h + 16),
        (cx + 3, GROUND_Y - h + 16), (cx + base_w // 2, GROUND_Y),
    ], silhouette)
    frame.line(cx, GROUND_Y - h + 16, cx, GROUND_Y - h, color=silhouette, width=2)


def _skyline_cairo(frame: Frame, hour: int, silhouette: Color) -> None:
    sand = tuple(max(0, c - 10) for c in silhouette)
    frame.polygon([(0, GROUND_Y), (0, 138), (192, 142), (192, GROUND_Y)], sand)
    # Great Pyramids — three staggered triangles
    for cx, w, h in [(56, 60, 46), (108, 46, 34), (146, 30, 22)]:
        pts = [(cx - w // 2, GROUND_Y), (cx + w // 2, GROUND_Y), (cx, GROUND_Y - h)]
        frame.polygon(pts, silhouette)


def _skyline_rio(frame: Frame, hour: int, silhouette: Color) -> None:
    hill = tuple(max(0, c - 14) for c in silhouette)
    frame.polygon([(0, GROUND_Y), (30, 92), (72, GROUND_Y)], hill)
    blocks = [
        (110, 12, 30), (124, 14, 22), (140, 10, 36), (154, 16, 24), (172, 12, 30),
    ]
    _building_row(frame, blocks, silhouette, (255, 210, 140), hour)
    # Christ the Redeemer — simple robed figure with outstretched arms atop the hill
    cx, cy = 30, 92
    frame.line(cx, cy, cx, cy - 22, color=silhouette, width=3)
    frame.line(cx - 16, cy - 14, cx + 16, cy - 14, color=silhouette, width=3)
    frame.ellipse(cx - 4, cy - 30, 8, 8, silhouette)


def _skyline_generic(frame: Frame, hour: int, silhouette: Color, city_name: str) -> None:
    """Abstract skyline seeded from the city name so it stays recognizable run to run."""
    import random
    rng = random.Random(city_name)
    x = 0
    blocks = []
    while x < 192:
        w = rng.randint(10, 22)
        h = rng.randint(24, 90)
        blocks.append((x, w, h))
        x += w + rng.randint(1, 4)
    _building_row(frame, blocks, silhouette, (255, 210, 150), hour)


def _skyline_rome(frame: Frame, hour: int, silhouette: Color) -> None:
    blocks = [(6, 14, 26), (150, 16, 30), (170, 12, 22)]
    _building_row(frame, blocks, silhouette, (255, 210, 140), hour)
    # Colosseum — squat drum with a rounded top and arched slits
    _, bottom = _sky_colors(hour)
    w, h = 92, 34
    x, y = 96 - w // 2, GROUND_Y - h
    frame.rect(x, y, w, h, silhouette)
    frame.ellipse(x - 4, y - 10, w + 8, 20, silhouette)
    for i in range(x + 6, x + w - 6, 10):
        frame.rect(i, y + 8, 4, h - 8, bottom)


def _skyline_istanbul(frame: Frame, hour: int, silhouette: Color) -> None:
    blocks = [(6, 14, 26), (150, 14, 24), (170, 12, 20)]
    _building_row(frame, blocks, silhouette, (255, 210, 140), hour)
    # Hagia Sophia — central dome flanked by two minarets
    cx = 96
    frame.ellipse(cx - 30, GROUND_Y - 46, 60, 34, silhouette)
    frame.rect(cx - 30, GROUND_Y - 30, 60, 30, silhouette)
    for mx in (cx - 46, cx + 46):
        frame.rect(mx - 3, GROUND_Y - 58, 6, 58, silhouette)
        cap = [(mx - 5, GROUND_Y - 58), (mx + 5, GROUND_Y - 58), (mx, GROUND_Y - 70)]
        frame.polygon(cap, silhouette)


def _skyline_seoul(frame: Frame, hour: int, silhouette: Color) -> None:
    hill = tuple(max(0, c - 14) for c in silhouette)
    frame.polygon([(60, GROUND_Y), (96, 108), (132, GROUND_Y)], hill)
    blocks = [(6, 14, 40), (24, 12, 55), (140, 12, 50), (158, 16, 36), (176, 10, 44)]
    _building_row(frame, blocks, silhouette, (255, 210, 140), hour)
    # N Seoul Tower on the hill
    cx, base_y = 96, 108
    frame.rect(cx - 3, base_y - 24, 6, 24, silhouette)
    frame.ellipse(cx - 10, base_y - 36, 20, 12, silhouette)
    frame.line(cx, base_y - 36, cx, base_y - 46, color=silhouette, width=2)


def _skyline_mumbai(frame: Frame, hour: int, silhouette: Color) -> None:
    blocks = [(6, 14, 30), (140, 16, 26), (160, 12, 34), (176, 10, 22)]
    _building_row(frame, blocks, silhouette, (255, 210, 140), hour)
    # Gateway of India — arched monument
    _, bottom = _sky_colors(hour)
    x, w, h = 74, 44, 60
    frame.rect(x, GROUND_Y - h, 10, h, silhouette)
    frame.rect(x + w - 10, GROUND_Y - h, 10, h, silhouette)
    frame.ellipse(x + 6, GROUND_Y - h - 2, w - 12, 40, silhouette)
    frame.ellipse(x + 14, GROUND_Y - h + 10, w - 28, h - 6, bottom)


def _skyline_kuala_lumpur(frame: Frame, hour: int, silhouette: Color) -> None:
    blocks = [(6, 14, 30), (150, 14, 28), (170, 12, 20)]
    _building_row(frame, blocks, silhouette, (255, 210, 140), hour)
    # Petronas Towers — twin tapering spires with a skybridge
    for cx in (82, 110):
        w, h = 16, 78
        frame.polygon([
            (cx - w // 2, GROUND_Y), (cx - 3, GROUND_Y - h + 10),
            (cx + 3, GROUND_Y - h + 10), (cx + w // 2, GROUND_Y),
        ], silhouette)
        frame.line(cx, GROUND_Y - h + 10, cx, GROUND_Y - h, color=silhouette, width=2)
    frame.rect(80, GROUND_Y - 40, 32, 4, silhouette)


def _skyline_jerusalem(frame: Frame, hour: int, silhouette: Color) -> None:
    blocks = [(6, 14, 24), (150, 14, 26), (170, 12, 20)]
    _building_row(frame, blocks, silhouette, (255, 210, 140), hour)
    # Dome of the Rock — golden dome on a squat base
    cx, base_y = 96, GROUND_Y
    frame.rect(cx - 24, base_y - 26, 48, 26, silhouette)
    dome_color = (180, 150, 40) if not _is_night(hour) else (90, 75, 20)
    frame.ellipse(cx - 18, base_y - 46, 36, 26, dome_color)
    frame.line(cx, base_y - 46, cx, base_y - 54, color=dome_color, width=2)


def _skyline_auckland(frame: Frame, hour: int, silhouette: Color) -> None:
    blocks = [(6, 14, 26), (140, 14, 30), (160, 12, 22), (176, 10, 34)]
    _building_row(frame, blocks, silhouette, (255, 210, 140), hour)
    # Sky Tower — thin spire with an observation deck bulge
    cx, mast_h, deck_y = 96, 55, GROUND_Y - 48
    frame.rect(cx - 3, GROUND_Y - mast_h, 6, mast_h, silhouette)
    frame.ellipse(cx - 9, deck_y, 18, 12, silhouette)
    frame.line(cx, deck_y, cx, deck_y - 22, color=silhouette, width=2)


def _skyline_buenos_aires(frame: Frame, hour: int, silhouette: Color) -> None:
    blocks = [(6, 14, 28), (24, 12, 20), (140, 14, 30), (160, 16, 24), (178, 10, 20)]
    _building_row(frame, blocks, silhouette, (255, 210, 140), hour)
    # Obelisco — tall obelisk with a pointed cap
    cx, w, h = 96, 16, 55
    frame.polygon([
        (cx - w // 2, GROUND_Y), (cx - 3, GROUND_Y - h + 8),
        (cx + 3, GROUND_Y - h + 8), (cx + w // 2, GROUND_Y),
    ], silhouette)
    tip = [(cx - 3, GROUND_Y - h + 8), (cx + 3, GROUND_Y - h + 8), (cx, GROUND_Y - h)]
    frame.polygon(tip, silhouette)


def _skyline_cape_town(frame: Frame, hour: int, silhouette: Color) -> None:
    hill = tuple(max(0, c - 14) for c in silhouette)
    frame.polygon([(10, GROUND_Y), (30, 70), (150, 70), (172, GROUND_Y)], hill)
    blocks = [(4, 14, 26), (160, 14, 24), (176, 10, 20)]
    _building_row(frame, blocks, silhouette, (255, 210, 140), hour)


def _skyline_marrakech(frame: Frame, hour: int, silhouette: Color) -> None:
    blocks = [(6, 14, 22), (150, 14, 20), (170, 12, 18)]
    _building_row(frame, blocks, silhouette, (255, 200, 120), hour)
    # Koutoubia minaret — square tower with a domed cap
    bx, bw, h = 84, 20, 50
    frame.rect(bx, GROUND_Y - h, bw, h, silhouette)
    frame.ellipse(bx + 2, GROUND_Y - h - 12, bw - 4, 14, silhouette)
    cap_x = bx + bw // 2
    frame.line(cap_x, GROUND_Y - h - 12, cap_x, GROUND_Y - h - 20, color=silhouette, width=2)


def _skyline_san_francisco(frame: Frame, hour: int, silhouette: Color) -> None:
    blocks = [(6, 14, 26), (150, 14, 28), (170, 12, 22)]
    _building_row(frame, blocks, silhouette, (255, 210, 140), hour)
    # Golden Gate Bridge — twin towers with a cable swoop
    rust = (170, 60, 50)
    for tx in (70, 122):
        frame.rect(tx - 3, GROUND_Y - 70, 6, 70, rust)
        frame.rect(tx - 8, GROUND_Y - 72, 16, 4, rust)
    frame.line(70, GROUND_Y - 66, 96, GROUND_Y - 30, color=rust, width=2)
    frame.line(96, GROUND_Y - 30, 122, GROUND_Y - 66, color=rust, width=2)


def _skyline_chicago(frame: Frame, hour: int, silhouette: Color) -> None:
    blocks = [(6, 14, 40), (24, 12, 55), (140, 12, 50), (158, 16, 36), (176, 10, 44)]
    _building_row(frame, blocks, silhouette, (255, 210, 140), hour)
    # Willis Tower — twin antenna, stepped black slab
    x, w, h = 88, 24, 110
    frame.rect(x, GROUND_Y - h, w, h, silhouette)
    frame.line(x + 6, GROUND_Y - h, x + 6, GROUND_Y - h - 14, color=silhouette, width=2)
    frame.line(x + w - 6, GROUND_Y - h, x + w - 6, GROUND_Y - h - 14, color=silhouette, width=2)


_SKYLINES = {
    "Pune": _skyline_pune,
    "New York": _skyline_new_york,
    "Seville": _skyline_seville,
    "Tokyo": _skyline_tokyo,
    "Bangkok": _skyline_bangkok,
    "Paris": _skyline_paris,
    "London": _skyline_london,
    "Sydney": _skyline_sydney,
    "Dubai": _skyline_dubai,
    "Cairo": _skyline_cairo,
    "Rio de Janeiro": _skyline_rio,
    "Rome": _skyline_rome,
    "Istanbul": _skyline_istanbul,
    "Seoul": _skyline_seoul,
    "Mumbai": _skyline_mumbai,
    "Kuala Lumpur": _skyline_kuala_lumpur,
    "Jerusalem": _skyline_jerusalem,
    "Auckland": _skyline_auckland,
    "Buenos Aires": _skyline_buenos_aires,
    "Cape Town": _skyline_cape_town,
    "Marrakech": _skyline_marrakech,
    "San Francisco": _skyline_san_francisco,
    "Chicago": _skyline_chicago,
}


# ------------------------------------------------------------------ stars / sun / moon / clouds

# Moon corners keep it clear of the centered header text while still varying per city.
_MOON_CORNERS = {
    "tl": ((14, 40), (10, 30)),
    "tr": ((150, 175), (10, 30)),
    "ml": ((10, 35), (72, 118)),
    "mr": ((155, 180), (72, 118)),
}


def _stars(frame: Frame, hour: int, city_name: str) -> None:
    """Background starfield — drawn before the skyline, fine either way since a few
    stars landing 'inside' a building silhouette just reads like a lit window."""
    if not _is_night(hour):
        return
    rng = random.Random(f"{city_name}-{hour}-stars")
    star_count = rng.randint(20, 40)
    for _ in range(star_count):
        x, y = rng.randint(0, 191), rng.randint(0, 128)
        size = 2 if rng.random() < 0.15 else 1
        frame.rect(x, y, size, size, (220, 220, 240))


def _sun_or_moon(frame: Frame, hour: int, city_name: str) -> None:
    """The sun/moon disc — drawn AFTER the skyline so it's always fully visible,
    never partially clipped behind a tall landmark (that reads as a rendering bug)."""
    rng = random.Random(f"{city_name}-{hour}-celestial")
    if _is_night(hour):
        (x0, x1), (y0, y1) = _MOON_CORNERS[rng.choice(list(_MOON_CORNERS))]
        mx, my = rng.randint(x0, x1), rng.randint(y0, y1)
        moon_size = rng.randint(16, 26)
        frame.ellipse(mx, my, moon_size, moon_size, (235, 235, 210))
        if rng.random() < 0.5:
            # waning/waxing crescent: shave off part of the disc with a dark overlap
            shift = int(moon_size * rng.choice([-0.4, 0.4]))
            frame.ellipse(mx + shift, my - 2, moon_size, moon_size, (6, 6, 20))
    else:
        # sun position drifts across the day; size/warmth vary a little per city for flavor
        t = max(0.0, min(1.0, (hour - 6) / 15))
        sx = int(20 + t * 150)
        arc = 1 - abs(t - 0.5) * 2  # 0 at sunrise/sunset, 1 at midday
        sy = int(45 - 25 * arc)
        size = rng.randint(22, 30)
        warmth = rng.randint(-15, 15)
        sun_color = (255, max(0, min(255, 235 + warmth // 2)), max(0, min(255, 140 + warmth)))
        frame.ellipse(sx, sy, size, size, sun_color)


def _clouds(frame: Frame, hour: int, city_name: str, condition: str) -> None:
    """Draw a few soft, semi-transparent clouds when conditions call for it."""
    cond = (condition or "").lower()
    keywords = ("cloud", "overcast", "fog", "drizzle", "rain", "snow", "shower", "thunder")
    if not any(k in cond for k in keywords):
        return

    rng = random.Random(f"{city_name}-clouds")
    tint = (235, 235, 245) if not _is_night(hour) else (110, 110, 135)
    count = 4 if "overcast" in cond else (2 if "partly" in cond else 3)

    for _ in range(count):
        w, h = rng.randint(34, 58), rng.randint(12, 18)
        cx = rng.randint(w // 2 + 4, 192 - w // 2 - 4)
        cy = rng.randint(16, 66)
        cloud_img = Image.new("RGBA", (w, h + 6), (0, 0, 0, 0))
        d = ImageDraw.Draw(cloud_img)
        fill = tint + (255,)
        d.ellipse([0, 6, w * 0.6, h], fill=fill)
        d.ellipse([w * 0.3, 0, w * 0.85, h * 0.85], fill=fill)
        d.ellipse([w * 0.5, 4, w, h + 2], fill=fill)
        frame.paste(cloud_img, cx - w // 2, cy - h // 2, opacity=0.4)


# ------------------------------------------------------------------ rendering

def render_city(city: dict, weather: dict) -> Frame:
    tz = ZoneInfo(city["tz"])
    now = datetime.now(tz)
    hour = now.hour
    name = city["name"]

    temp_high = weather.get("temp_high")
    humidity = weather.get("humidity")
    condition = weather.get("condition", "—")
    alert = weather.get("alert")

    base_top, base_bottom = _sky_colors(hour)
    sky_rng = random.Random(f"{name}-sky")
    top = _jitter_color(base_top, sky_rng)
    bottom = _jitter_color(base_bottom, sky_rng)
    frame = Frame(bg=bottom)
    frame.vgradient(0, SKY_TOP_Y, 192, GROUND_Y, top, bottom)

    _stars(frame, hour, name)

    silhouette = (10, 10, 16) if not _is_night(hour) else (2, 2, 8)
    draw_skyline = _SKYLINES.get(name)
    if draw_skyline:
        draw_skyline(frame, hour, silhouette)
    else:
        _skyline_generic(frame, hour, silhouette, name)

    # sun/moon and clouds go on top of the skyline so tall landmarks never clip them
    _sun_or_moon(frame, hour, name)
    _clouds(frame, hour, name, condition)

    # ground strip
    frame.rect(0, GROUND_Y, 192, 192 - GROUND_Y, (16, 16, 20))
    frame.line(0, GROUND_Y, 191, GROUND_Y, color=(0, 0, 0), width=1)

    # header: city name
    frame.text(96, 12, name, size=18, color=(255, 255, 255), anchor="mm")

    # big clock, readable against sky
    time_str = now.strftime("%-I:%M %p")
    frame.text(96, 38, time_str, size=26, color=(255, 255, 255), anchor="mm")
    frame.text(96, 58, now.strftime("%a %b %-d"), size=11, color=(230, 230, 230), anchor="mm")

    # bottom info strip: high temp, humidity, condition, alert — auto-shrink so nothing clips
    high_str = f"{temp_high:.0f}°F" if isinstance(temp_high, (int, float)) else "--"
    hum_str = f"{humidity:.0f}%" if isinstance(humidity, (int, float)) else "--"

    stats_line = f"High {high_str} • Humidity {hum_str}"
    frame.text_fit(96, 162, stats_line, max_width=186, size=12, min_size=8, color=(220, 220, 220))
    frame.text_fit(96, 176, condition, max_width=186, size=11, min_size=8, color=(160, 160, 160))

    if alert:
        frame.rect(0, 186, 192, 6, (200, 40, 30))
        alert_line = f"⚠ {alert} ALERT"
        frame.text_fit(
            96, 189, alert_line, max_width=186, size=8, min_size=6, color=(255, 255, 255),
        )

    return frame


def render_all(cities: list[dict] | None = None) -> list[tuple[str, Frame]]:
    frames = []
    for city in cities if cities is not None else CITIES:
        weather = fetch_weather(city)
        frames.append((city["name"], render_city(city, weather)))
    return frames
