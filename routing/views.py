"""HTTP layer: the JSON route API plus a small HTML map for demos."""
from __future__ import annotations

import logging

from django.shortcuts import render
from rest_framework import status
from rest_framework.response import Response
from rest_framework.views import APIView

from .serializers import RouteRequestSerializer, serialize_trip
from .services import plan_trip
from .services.geocoding import GeocodingError
from .services.osrm import RoutingError

logger = logging.getLogger(__name__)


class RouteView(APIView):
    """``/api/route/`` -- the main endpoint.

    Accepts ``start`` and ``finish`` either as query parameters (GET) or in a
    JSON body (POST). Returns the route geometry, the optimal cost-effective
    fuel stops, and the total fuel spend for the trip.
    """

    def get(self, request):
        return self._handle(request.query_params, request)

    def post(self, request):
        return self._handle(request.data, request)

    def _handle(self, data, request):
        req = RouteRequestSerializer(data=data)
        req.is_valid(raise_exception=True)
        start = req.validated_data["start"]
        finish = req.validated_data["finish"]

        include_geometry = str(
            request.query_params.get("geometry", "true")
        ).lower() not in {"0", "false", "no"}

        try:
            result = plan_trip(start, finish)
        except GeocodingError as exc:
            return Response({"error": str(exc)}, status=status.HTTP_400_BAD_REQUEST)
        except RoutingError as exc:
            return Response({"error": str(exc)}, status=status.HTTP_502_BAD_GATEWAY)
        except Exception:  # noqa: BLE001
            logger.exception("Unexpected error planning trip %s -> %s", start, finish)
            return Response(
                {"error": "Internal error while planning the route."},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )

        body = serialize_trip(result, include_geometry=include_geometry)
        http_status = (
            status.HTTP_200_OK if body["feasible"]
            else status.HTTP_422_UNPROCESSABLE_ENTITY
        )
        return Response(body, status=http_status)


def map_view(request):
    """``/map/?start=...&finish=...`` -- renders the route + stops on a map.

    Pure client-side Leaflet that calls the JSON API; handy for the Loom wal
    through and for eyeballing results. Not required by the spec, but it makes
    "return a map of the route" literal.
    """
    return render(
        request,
        "routing/map.html",
        {
            "start": request.GET.get("start", "Seattle, WA"),
            "finish": request.GET.get("finish", "Miami, FL"),
        },
    )
