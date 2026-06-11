"""Core optimisation: pick the cheapest legal sequence of fuel stops.

Two independent steps:

1. ``stations_along_route`` -- project every truck stop onto the driving route
   and keep the ones inside a thin corridor, recording how many miles into the
   trip each one sits.
2. ``optimal_fuel_plan`` -- given those mile-positioned, priced stations, solve
   the classic "gas station problem" to minimise total fuel spend subject to
   the tank range.

The optimiser is deliberately framework-free so it can be unit-tested without
Django, a network, or any I/O.
"""
from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np

from .geo import haversine_miles


# --------------------------------------------------------------------------- #
# Step 1: which stations lie along the route, and where?
# --------------------------------------------------------------------------- #
@dataclass
class CandidateStation:
    position_miles: float  # distance from origin along the route
    price: float           # USD per gallon
    meta: dict             # name / address / city / state / lat / lon


def stations_along_route(
    route_coords: np.ndarray,   # (N, 2) lat, lon  (already downsampled)
    route_cumulative: np.ndarray,  # (N,) miles from origin at each vertex
    station_lat: np.ndarray,
    station_lon: np.ndarray,
    station_price: np.ndarray,
    station_meta: list[dict],
    corridor_miles: float,
) -> list[CandidateStation]:
    """Return stations within ``corridor_miles`` of the route, mile-positioned.

    For each candidate we find the nearest route vertex (vectorised), use its
    cumulative mileage as the station's trip position, and keep it only if it is
    inside the corridor. A bounding-box pre-filter discards the ~99% of
    stations that are nowhere near the route before doing any trig.
    """
    if len(station_lat) == 0 or len(route_coords) == 0:
        return []

    # Corridor expressed loosely in degrees for the cheap bbox pre-filter
    # (1 deg latitude ~= 69 mi; longitude is narrower but the margin is padded).
    deg_margin = corridor_miles / 69.0 + 0.1
    lat_min, lat_max = route_coords[:, 0].min(), route_coords[:, 0].max()
    lon_min, lon_max = route_coords[:, 1].min(), route_coords[:, 1].max()
    in_box = (
        (station_lat >= lat_min - deg_margin)
        & (station_lat <= lat_max + deg_margin)
        & (station_lon >= lon_min - deg_margin)
        & (station_lon <= lon_max + deg_margin)
    )
    idx = np.nonzero(in_box)[0]
    if idx.size == 0:
        return []

    route_lat = route_coords[:, 0]
    route_lon = route_coords[:, 1]
    candidates: list[CandidateStation] = []
    for i in idx:
        d = haversine_miles(station_lat[i], station_lon[i], route_lat, route_lon)
        nearest = int(np.argmin(d))
        if d[nearest] <= corridor_miles:
            candidates.append(
                CandidateStation(
                    position_miles=float(route_cumulative[nearest]),
                    price=float(station_price[i]),
                    meta=station_meta[i],
                )
            )
    candidates.sort(key=lambda c: c.position_miles)
    return candidates


# --------------------------------------------------------------------------- #
# Step 2: the gas-station problem
# --------------------------------------------------------------------------- #
@dataclass
class FuelStop:
    position_miles: float
    price: float
    gallons: float
    cost: float
    meta: dict


@dataclass
class FuelPlan:
    feasible: bool
    total_distance_miles: float
    total_gallons: float
    total_cost: float
    stops: list[FuelStop] = field(default_factory=list)
    reason: str = ""  # populated when infeasible


def optimal_fuel_plan(
    candidates: list[CandidateStation],
    total_distance_miles: float,
    range_miles: float,
    mpg: float,
    origin_meta: dict | None = None,
) -> FuelPlan:
    """Minimise total fuel cost for the trip.

    Model / assumptions (see README for the rationale):

    * Tank holds ``range_miles`` of range; ``mpg`` converts miles<->gallons.
    * The whole trip's fuel is paid for: ``total_gallons = distance / mpg``.
    * Refuelling is only possible at the supplied stations.
    * Departure is modelled as a virtual stop at mile 0, priced at the *nearest*
      reachable station -- i.e. you fill up before leaving at the closest truck
      stop you could realistically reach, not at the cheapest one far down the
      route. ``origin_meta`` (the trip's start point) labels that stop; the
      greedy is then free to buy only the minimum there and save the rest for
      cheaper stations ahead.
    * No leg (origin->first stop, stop->stop, last stop->destination) may exceed
      the tank range, otherwise the trip is infeasible.

    Strategy is the textbook optimal greedy for a fixed-capacity tank: standing
    at a stop, if a cheaper stop is reachable, buy *just enough* to roll to it;
    otherwise fill the tank and advance to the cheapest reachable stop.
    """
    gpm = 1.0 / mpg  # gallons per mile
    D = total_distance_miles

    if D <= 0:
        return FuelPlan(True, 0.0, 0.0, 0.0, [], "")

    if not candidates:
        return FuelPlan(
            False, D, D * gpm, 0.0, [],
            "No fuel stations found within the route corridor.",
        )

    # Synthetic departure stop at mile 0, priced at the NEAREST reachable
    # station: you fill up before leaving at the closest truck stop you could
    # actually get to, rather than magically paying the cheapest price found
    # hundreds of miles away. The greedy below can still buy only the minimum
    # here and save the rest for cheaper stations ahead.
    reachable_from_origin = [c for c in candidates if c.position_miles <= range_miles]
    if not reachable_from_origin:
        return FuelPlan(
            False, D, D * gpm, 0.0, [],
            f"First fuel station is {candidates[0].position_miles:.0f} mi away, "
            f"beyond the {range_miles:.0f} mi range.",
        )
    nearest = min(reachable_from_origin, key=lambda c: c.position_miles)
    origin_price = nearest.price
    display_meta = dict(origin_meta) if origin_meta else {"name": "Departure (full tank)"}
    display_meta["origin_topup"] = True

    # stops[0] is the departure stop; the rest are real stations ahead of it.
    stops: list[CandidateStation] = [
        CandidateStation(0.0, origin_price, display_meta)
    ]
    stops.extend(c for c in candidates if c.position_miles > 0.0)
    n = len(stops)

    plan_stops: list[FuelStop] = []
    total_cost = 0.0
    cur_fuel = 0.0  # miles of range currently in the tank
    i = 0

    while True:
        pos = stops[i].position_miles
        price = stops[i].price

        # Can we reach the destination from here without another stop?
        if D - pos <= range_miles + 1e-9:
            need = max(0.0, (D - pos) - cur_fuel)
            if need > 0:
                gal = need * gpm
                total_cost += gal * price
                plan_stops.append(_mk_stop(stops[i], gal, gal * price))
            break

        # Stations strictly ahead and reachable on a full tank from here.
        reach = [
            k for k in range(i + 1, n)
            if stops[k].position_miles <= pos + range_miles + 1e-9
        ]
        if not reach:
            nxt_pos = stops[i + 1].position_miles if i + 1 < n else D
            return FuelPlan(
                False, D, D * gpm, 0.0, [],
                f"Gap of {nxt_pos - pos:.0f} mi near mile {pos:.0f} exceeds the "
                f"{range_miles:.0f} mi range -- no reachable fuel stop.",
            )

        cheaper = [k for k in reach if stops[k].price < price]
        if cheaper:
            # Buy only enough to coast to the nearest cheaper stop.
            nxt = min(cheaper, key=lambda k: stops[k].position_miles)
            need = max(0.0, (stops[nxt].position_miles - pos) - cur_fuel)
        else:
            # Nothing cheaper in range: fill up, push to the cheapest reachable.
            nxt = min(reach, key=lambda k: stops[k].price)
            need = range_miles - cur_fuel

        if need > 0:
            gal = need * gpm
            total_cost += gal * price
            cur_fuel += need
            plan_stops.append(_mk_stop(stops[i], gal, gal * price))

        cur_fuel -= stops[nxt].position_miles - pos
        i = nxt

    return FuelPlan(
        feasible=True,
        total_distance_miles=D,
        total_gallons=D * gpm,
        total_cost=round(total_cost, 2),
        stops=plan_stops,
    )


def _mk_stop(s: CandidateStation, gallons: float, cost: float) -> FuelStop:
    return FuelStop(
        position_miles=round(s.position_miles, 1),
        price=round(s.price, 4),
        gallons=round(gallons, 2),
        cost=round(cost, 2),
        meta=s.meta,
    )
