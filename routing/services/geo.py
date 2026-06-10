"""Geographic helper functions (pure, dependency-light).

All distances are in **miles** unless stated otherwise. We work with plain
``numpy`` rather than a heavy GIS stack because the only spatial operations we
need are great-circle distance and nearest-vertex lookups, both of which
vectorise cleanly.
"""
from __future__ import annotations

import numpy as np

EARTH_RADIUS_MILES = 3958.7613


def haversine_miles(lat1, lon1, lat2, lon2):
    """Great-circle distance in miles. Fully vectorised over numpy arrays.

    Any argument may be a scalar or an ``ndarray``; standard broadcasting
    applies, so e.g. ``haversine_miles(stations_lat, stations_lon, p_lat,
    p_lon)`` returns one distance per station.
    """
    lat1 = np.radians(lat1)
    lon1 = np.radians(lon1)
    lat2 = np.radians(lat2)
    lon2 = np.radians(lon2)
    dlat = lat2 - lat1
    dlon = lon2 - lon1
    a = np.sin(dlat / 2.0) ** 2 + np.cos(lat1) * np.cos(lat2) * np.sin(dlon / 2.0) ** 2
    return 2.0 * EARTH_RADIUS_MILES * np.arcsin(np.sqrt(np.clip(a, 0.0, 1.0)))


def cumulative_miles(coords: np.ndarray) -> np.ndarray:
    """Cumulative distance (miles) from the first vertex to each vertex.

    ``coords`` is an ``(N, 2)`` array of ``[lat, lon]`` pairs ordered along the
    route. Returns an ``(N,)`` array whose first element is 0.
    """
    if len(coords) < 2:
        return np.zeros(len(coords))
    seg = haversine_miles(
        coords[:-1, 0], coords[:-1, 1], coords[1:, 0], coords[1:, 1]
    )
    return np.concatenate([[0.0], np.cumsum(seg)])


def downsample_polyline(coords: np.ndarray, cum: np.ndarray, spacing_miles: float):
    """Thin a dense polyline so consecutive kept vertices are >= spacing apart.

    OSRM returns very dense geometry (often thousands of points for a long
    route). For corridor matching we don't need every vertex -- one every
    couple of miles preserves position accuracy while making the
    station-to-route distance computation an order of magnitude cheaper. The
    first and last vertices are always kept.
    """
    if len(coords) <= 2:
        return coords, cum
    keep = [0]
    last = cum[0]
    for i in range(1, len(coords) - 1):
        if cum[i] - last >= spacing_miles:
            keep.append(i)
            last = cum[i]
    keep.append(len(coords) - 1)
    keep = np.array(keep)
    return coords[keep], cum[keep]
