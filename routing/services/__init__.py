"""High-level orchestration: location strings in, full fuel plan out."""
from __future__ import annotations

from dataclasses import dataclass

from django.conf import settings

from . import geo, osrm
from .fuel_data import get_station_store
from .geocoding import geocode
from .optimizer import FuelPlan, optimal_fuel_plan, stations_along_route


@dataclass
class TripResult:
    start: tuple[float, float]
    finish: tuple[float, float]
    route: osrm.Route
    plan: FuelPlan


def plan_trip(start_text: str, finish_text: str) -> TripResult:
    """Geocode endpoints, fetch the route (1 call), and optimise fuel stops."""
    start = geocode(start_text)
    finish = geocode(finish_text)

    route = osrm.get_route(start, finish)  # <-- the single map/route API call

    cum = geo.cumulative_miles(route.coords)
    # Rescale cumulative distance so the polyline total matches OSRM's reported
    # driving distance (haversine of the geometry is very close but not exact).
    if cum[-1] > 0:
        cum = cum * (route.distance_miles / cum[-1])
    coords_ds, cum_ds = geo.downsample_polyline(
        route.coords, cum, settings.ROUTE_SAMPLE_MILES
    )

    store = get_station_store()
    candidates = stations_along_route(
        coords_ds, cum_ds,
        store.lat, store.lon, store.price, store.meta,
        corridor_miles=settings.FUEL_CORRIDOR_MILES,
    )

    plan = optimal_fuel_plan(
        candidates,
        total_distance_miles=route.distance_miles,
        range_miles=settings.VEHICLE_RANGE_MILES,
        mpg=settings.VEHICLE_MPG,
    )
    return TripResult(start=start, finish=finish, route=route, plan=plan)
