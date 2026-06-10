"""Request/response serializers for the route API."""
from __future__ import annotations

from rest_framework import serializers

from .services import TripResult


class RouteRequestSerializer(serializers.Serializer):
    """Validates the two required inputs."""

    start = serializers.CharField(
        help_text="Origin: 'City, ST', 'lat,lon', or a full address "
                  "(if the Nominatim fallback is enabled)."
    )
    finish = serializers.CharField(help_text="Destination, same formats as start.")


def serialize_trip(result: TripResult, *, include_geometry: bool = True) -> dict:
    """Shape a :class:`TripResult` into the JSON response body."""
    plan = result.plan
    body: dict = {
        "start": {"lat": result.start[0], "lon": result.start[1]},
        "finish": {"lat": result.finish[0], "lon": result.finish[1]},
        "route": {
            "total_distance_miles": round(result.route.distance_miles, 1),
            "estimated_drive_time_hours": round(result.route.duration_seconds / 3600, 2),
        },
        "vehicle": {"range_miles": 500, "mpg": 10},
        "feasible": plan.feasible,
    }

    if not plan.feasible:
        body["error"] = plan.reason
        body["fuel_stops"] = []
        return body

    body["fuel"] = {
        "total_gallons": round(plan.total_gallons, 1),
        "total_cost_usd": round(plan.total_cost, 2),
        "number_of_stops": len(plan.stops),
    }
    body["fuel_stops"] = [
        {
            "name": s.meta.get("name"),
            "address": s.meta.get("address"),
            "city": s.meta.get("city"),
            "state": s.meta.get("state"),
            "lat": s.meta.get("lat"),
            "lon": s.meta.get("lon"),
            "price_per_gallon": s.price,
            "miles_into_trip": s.position_miles,
            "gallons_purchased": s.gallons,
            "leg_cost_usd": s.cost,
            "pre_trip_topup": bool(s.meta.get("origin_topup")),
        }
        for s in plan.stops
    ]

    if include_geometry:
        # GeoJSON LineString uses [lon, lat]; emit it client-ready for mapping.
        body["route"]["geojson"] = {
            "type": "LineString",
            "coordinates": [[round(lon, 5), round(lat, 5)]
                            for lat, lon in result.route.coords],
        }
    return body
