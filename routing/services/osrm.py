"""Thin client for the routing API (OSRM by default).

We use OSRM because its public demo server (``router.project-osrm.org``) is
free, needs no API key, and returns the full route geometry, distance and
duration in a **single** request -- satisfying the "one call to the map/route
API is ideal" requirement. The base URL is configurable, so you can point this
at a self-hosted OSRM or any OSRM-compatible endpoint.

Successful routes are cached (keyed on rounded coordinates) so repeated or
near-identical requests make *zero* additional calls.
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import requests
from django.conf import settings
from django.core.cache import cache

METERS_PER_MILE = 1609.344


class RoutingError(RuntimeError):
    """Raised when the routing provider fails or returns no route."""


@dataclass
class Route:
    coords: np.ndarray         # (N, 2) array of [lat, lon] along the route
    distance_miles: float
    duration_seconds: float


def _cache_key(a, b) -> str:
    return f"route:{a[0]:.3f},{a[1]:.3f};{b[0]:.3f},{b[1]:.3f}"


def get_route(start: tuple[float, float], finish: tuple[float, float]) -> Route:
    """Fetch the driving route between two ``(lat, lon)`` points (one API call).

    OSRM expects ``lon,lat`` ordering in the path; we convert its returned
    ``[lon, lat]`` geometry back to ``[lat, lon]`` for internal consistency.
    """
    key = _cache_key(start, finish)
    cached = cache.get(key)
    if cached is not None:
        return cached

    url = (
        f"{settings.OSRM_BASE_URL.rstrip('/')}/route/v1/driving/"
        f"{start[1]},{start[0]};{finish[1]},{finish[0]}"
    )
    try:
        resp = requests.get(
            url,
            params={"overview": "full", "geometries": "geojson", "alternatives": "false", "steps": "false"},
            timeout=settings.HTTP_TIMEOUT,
        )
        resp.raise_for_status()
        data = resp.json()
    except requests.RequestException as exc:
        raise RoutingError(f"Routing provider request failed: {exc}") from exc

    if data.get("code") != "Ok" or not data.get("routes"):
        raise RoutingError(
            f"No route found between the given points (provider said: {data.get('code')})."
        )

    route = data["routes"][0]
    lonlat = np.array(route["geometry"]["coordinates"], dtype=float)  # [lon, lat]
    coords = lonlat[:, ::-1].copy()  # -> [lat, lon]
    result = Route(
        coords=coords,
        distance_miles=route["distance"] / METERS_PER_MILE,
        duration_seconds=route["duration"],
    )
    cache.set(key, result, timeout=settings.ROUTE_CACHE_TTL)
    return result
