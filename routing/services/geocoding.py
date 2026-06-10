"""Resolve a free-text start/finish location to ``(lat, lon)``.

Resolution order (cheapest first, so the common cases cost zero network calls):

1. Raw ``"lat, lon"`` -- parsed directly.
2. ``"City, ST"`` / ``"City, State"`` -- looked up in the bundled offline
   gazetteer (the same table used to geocode the stops).
3. Optional Nominatim (OpenStreetMap) fallback for full street addresses --
   **off by default** to honour the "few external calls" requirement; enable
   with ``NOMINATIM_FALLBACK=1`` if you need arbitrary-address support.

Results are cached in Django's cache, so repeated lookups are free.
"""
from __future__ import annotations

import csv
import hashlib
import re
import threading
from functools import lru_cache
from pathlib import Path

import requests
from django.conf import settings
from django.core.cache import cache

US_STATE_NAME_TO_CODE = {
    "alabama": "AL", "alaska": "AK", "arizona": "AZ", "arkansas": "AR",
    "california": "CA", "colorado": "CO", "connecticut": "CT", "delaware": "DE",
    "florida": "FL", "georgia": "GA", "hawaii": "HI", "idaho": "ID",
    "illinois": "IL", "indiana": "IN", "iowa": "IA", "kansas": "KS",
    "kentucky": "KY", "louisiana": "LA", "maine": "ME", "maryland": "MD",
    "massachusetts": "MA", "michigan": "MI", "minnesota": "MN", "mississippi": "MS",
    "missouri": "MO", "montana": "MT", "nebraska": "NE", "nevada": "NV",
    "new hampshire": "NH", "new jersey": "NJ", "new mexico": "NM", "new york": "NY",
    "north carolina": "NC", "north dakota": "ND", "ohio": "OH", "oklahoma": "OK",
    "oregon": "OR", "pennsylvania": "PA", "rhode island": "RI",
    "south carolina": "SC", "south dakota": "SD", "tennessee": "TN", "texas": "TX",
    "utah": "UT", "vermont": "VT", "virginia": "VA", "washington": "WA",
    "west virginia": "WV", "wisconsin": "WI", "wyoming": "WY",
    "district of columbia": "DC",
}

_LATLON_RE = re.compile(r"^\s*(-?\d+(?:\.\d+)?)\s*,\s*(-?\d+(?:\.\d+)?)\s*$")
_city_index: dict[tuple[str, str], tuple[float, float]] | None = None
_lock = threading.Lock()


class GeocodingError(ValueError):
    """Raised when a location string cannot be resolved."""


def _get_city_index() -> dict[tuple[str, str], tuple[float, float]]:
    global _city_index
    if _city_index is None:
        with _lock:
            if _city_index is None:
                idx: dict[tuple[str, str], tuple[float, float]] = {}
                with Path(settings.US_CITIES_CSV).open(newline="", encoding="utf-8") as fh:
                    for row in csv.DictReader(fh):
                        key = (row["CITY"].strip().upper(), row["STATE_CODE"].strip().upper())
                        idx.setdefault(key, (float(row["LATITUDE"]), float(row["LONGITUDE"])))
                _city_index = idx
    return _city_index


def _normalise_state(token: str) -> str | None:
    token = token.strip()
    if len(token) == 2 and token.upper() in {v for v in US_STATE_NAME_TO_CODE.values()}:
        return token.upper()
    return US_STATE_NAME_TO_CODE.get(token.lower())


def _try_latlon(text: str):
    m = _LATLON_RE.match(text)
    if not m:
        return None
    lat, lon = float(m.group(1)), float(m.group(2))
    if -90 <= lat <= 90 and -180 <= lon <= 180:
        return lat, lon
    return None


def _try_city_state(text: str):
    if "," not in text:
        return None
    city, _, rest = text.partition(",")
    state = _normalise_state(rest.split(",")[0]) or _normalise_state(rest)
    if not state:
        return None
    return _get_city_index().get((city.strip().upper(), state))


@lru_cache(maxsize=8)
def _nominatim(text: str):
    resp = requests.get(
        "https://nominatim.openstreetmap.org/search",
        params={"q": text, "format": "json", "limit": 1, "countrycodes": "us"},
        headers={"User-Agent": settings.NOMINATIM_USER_AGENT},
        timeout=settings.HTTP_TIMEOUT,
    )
    resp.raise_for_status()
    data = resp.json()
    if not data:
        return None
    return float(data[0]["lat"]), float(data[0]["lon"])


def geocode(text: str) -> tuple[float, float]:
    """Resolve ``text`` to ``(lat, lon)`` or raise :class:`GeocodingError`."""
    text = (text or "").strip()
    if not text:
        raise GeocodingError("Empty location.")

    cache_key = "geocode:" + hashlib.md5(text.lower().encode()).hexdigest()
    cached = cache.get(cache_key)
    if cached:
        return cached

    coord = _try_latlon(text) or _try_city_state(text)
    if coord is None and settings.NOMINATIM_FALLBACK:
        coord = _nominatim(text)
    if coord is None:
        raise GeocodingError(
            f"Could not resolve '{text}'. Use 'City, ST', 'lat,lon', "
            "or enable the Nominatim fallback for full addresses."
        )

    cache.set(cache_key, coord, timeout=settings.GEOCODE_CACHE_TTL)
    return coord
