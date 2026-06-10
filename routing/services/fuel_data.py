"""Load the truck-stop price list and attach coordinates, once per process.

The supplied price file has no latitude/longitude -- only city and state. We
geocode each stop **offline** against a bundled US-cities table (no network,
no per-request cost). The joined, de-duplicated result is cached on disk as a
``.npz`` so subsequent process starts are effectively instant, and held in a
module-level singleton so it is built at most once per worker.
"""
from __future__ import annotations

import csv
import logging
import threading
from dataclasses import dataclass
from pathlib import Path

import numpy as np
from django.conf import settings

logger = logging.getLogger(__name__)


@dataclass
class StationStore:
    """Vectorised, ready-to-query view of every geocoded truck stop."""

    lat: np.ndarray
    lon: np.ndarray
    price: np.ndarray
    meta: list[dict]


_store: StationStore | None = None
_lock = threading.Lock()


def _load_city_index(path: Path) -> dict[tuple[str, str], tuple[float, float]]:
    """(CITY, STATE) -> (lat, lon) from the bundled offline gazetteer."""
    index: dict[tuple[str, str], tuple[float, float]] = {}
    with path.open(newline="", encoding="utf-8") as fh:
        for row in csv.DictReader(fh):
            key = (row["CITY"].strip().upper(), row["STATE_CODE"].strip().upper())
            index.setdefault(key, (float(row["LATITUDE"]), float(row["LONGITUDE"])))
    return index


def _build_store() -> StationStore:
    fuel_path = Path(settings.FUEL_PRICES_CSV)
    cities_path = Path(settings.US_CITIES_CSV)
    cache_path = Path(settings.STATION_CACHE)

    if cache_path.exists():
        try:
            data = np.load(cache_path, allow_pickle=True)
            logger.info("Loaded %d stations from cache %s", len(data["price"]), cache_path)
            return StationStore(
                lat=data["lat"], lon=data["lon"], price=data["price"],
                meta=list(data["meta"]),
            )
        except Exception:  # noqa: BLE001 - corrupt cache should just rebuild
            logger.warning("Station cache unreadable; rebuilding.")

    city_index = _load_city_index(cities_path)

    # Group by OPIS Truckstop ID, keeping the cheapest retail price seen for
    # that physical stop (the same ID can appear several times in the feed).
    best: dict[str, dict] = {}
    geocoded = missed = 0
    with fuel_path.open(newline="", encoding="utf-8-sig") as fh:
        for row in csv.DictReader(fh):
            city = row["City"].strip()
            state = row["State"].strip()
            try:
                price = float(row["Retail Price"])
            except (TypeError, ValueError):
                continue
            coord = city_index.get((city.upper(), state.upper()))
            if coord is None:
                missed += 1
                continue
            geocoded += 1
            sid = row["OPIS Truckstop ID"].strip() or f"{city}|{state}|{row['Truckstop Name']}"
            existing = best.get(sid)
            if existing is None or price < existing["price"]:
                best[sid] = {
                    "price": price,
                    "lat": coord[0],
                    "lon": coord[1],
                    "name": row["Truckstop Name"].strip().title(),
                    "address": row["Address"].strip(),
                    "city": city.title(),
                    "state": state.upper(),
                }

    logger.info(
        "Geocoded %d/%d rows (%d unmatched, mostly non-US); %d unique stops.",
        geocoded, geocoded + missed, missed, len(best),
    )

    lat = np.array([s["lat"] for s in best.values()], dtype=float)
    lon = np.array([s["lon"] for s in best.values()], dtype=float)
    price = np.array([s["price"] for s in best.values()], dtype=float)
    meta = [
        {k: s[k] for k in ("name", "address", "city", "state", "lat", "lon", "price")}
        for s in best.values()
    ]

    cache_path.parent.mkdir(parents=True, exist_ok=True)
    np.savez(cache_path, lat=lat, lon=lon, price=price, meta=np.array(meta, dtype=object))
    logger.info("Wrote station cache to %s", cache_path)
    return StationStore(lat=lat, lon=lon, price=price, meta=meta)


def get_station_store() -> StationStore:
    """Return the process-wide singleton, building it on first use."""
    global _store
    if _store is None:
        with _lock:
            if _store is None:
                _store = _build_store()
    return _store
