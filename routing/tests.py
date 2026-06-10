"""Tests that run fully offline (the one external call is mocked)."""
from __future__ import annotations

from unittest import mock

import numpy as np
from django.test import TestCase
from rest_framework.test import APIClient

from routing.services import geo, osrm
from routing.services.fuel_data import StationStore
from routing.services.geocoding import GeocodingError, geocode
from routing.services.optimizer import (
    CandidateStation,
    optimal_fuel_plan,
    stations_along_route,
)


def cs(pos, price, name="s"):
    return CandidateStation(pos, price, {"name": name, "lat": 0, "lon": 0})


class OptimizerTests(TestCase):
    def test_short_trip_single_tank(self):
        plan = optimal_fuel_plan([cs(50, 3.0)], 300, 500, 10)
        self.assertTrue(plan.feasible)
        self.assertAlmostEqual(plan.total_gallons, 30.0)
        self.assertAlmostEqual(plan.total_cost, 90.0)

    def test_multi_stop_minimises_cost(self):
        stns = [cs(100, 4.0), cs(400, 3.0), cs(600, 5.0), cs(900, 2.0)]
        plan = optimal_fuel_plan(stns, 1000, 500, 10)
        self.assertTrue(plan.feasible)
        self.assertAlmostEqual(plan.total_gallons, 100.0)
        # Hand-computed optimum for this layout.
        self.assertAlmostEqual(plan.total_cost, 290.0)

    def test_prefers_cheaper_reachable_station(self):
        plan = optimal_fuel_plan([cs(10, 5.0, "pricey"), cs(480, 2.0, "cheap")], 900, 500, 10)
        # All fuel should be sourced at $2 (cheapest within range of origin).
        self.assertAlmostEqual(plan.total_cost, 180.0)
        self.assertTrue(all(s.price == 2.0 for s in plan.stops))

    def test_infeasible_when_gap_exceeds_range(self):
        plan = optimal_fuel_plan([cs(50, 3.0), cs(700, 3.0)], 1000, 500, 10)
        self.assertFalse(plan.feasible)
        self.assertIn("exceeds", plan.reason)

    def test_infeasible_with_no_stations(self):
        plan = optimal_fuel_plan([], 300, 500, 10)
        self.assertFalse(plan.feasible)

    def test_first_station_out_of_range(self):
        plan = optimal_fuel_plan([cs(600, 3.0)], 1000, 500, 10)
        self.assertFalse(plan.feasible)


class CorridorMatchingTests(TestCase):
    def test_only_near_stations_are_kept_and_positioned(self):
        # Straight west->east route along the equator-ish line lat=40.
        lats = np.full(11, 40.0)
        lons = np.linspace(-100.0, -90.0, 11)
        coords = np.column_stack([lats, lons])
        cum = geo.cumulative_miles(coords)

        # One station right on the line, one ~200 mi north (far off corridor).
        s_lat = np.array([40.0, 43.0])
        s_lon = np.array([-95.0, -95.0])
        s_price = np.array([3.0, 1.0])
        meta = [{"name": "on-route"}, {"name": "far"}]

        out = stations_along_route(coords, cum, s_lat, s_lon, s_price, meta, corridor_miles=25)
        self.assertEqual(len(out), 1)
        self.assertEqual(out[0].meta["name"], "on-route")
        # ~halfway along a ~530 mi route.
        self.assertGreater(out[0].position_miles, 200)
        self.assertLess(out[0].position_miles, 330)


class GeocodingTests(TestCase):
    def test_latlon_string(self):
        self.assertEqual(geocode("40.0, -75.0"), (40.0, -75.0))

    def test_city_state_offline(self):
        lat, lon = geocode("Chicago, IL")
        self.assertAlmostEqual(lat, 41.85, delta=0.6)
        self.assertAlmostEqual(lon, -87.65, delta=0.6)

    def test_full_state_name(self):
        lat, lon = geocode("Denver, Colorado")
        self.assertAlmostEqual(lat, 39.74, delta=0.6)

    def test_unresolvable_raises(self):
        with self.assertRaises(GeocodingError):
            geocode("Nowheresville, ZZ")


class RouteApiTests(TestCase):
    def setUp(self):
        self.client = APIClient()

    def _fake_route(self, start, finish):
        # Synthetic ~520 mi straight line, lat 40, lon -100 -> -90.
        lons = np.linspace(-100.0, -90.0, 50)
        coords = np.column_stack([np.full(50, 40.0), lons])
        return osrm.Route(coords=coords, distance_miles=520.0, duration_seconds=30000)

    def _fake_store(self):
        return StationStore(
            lat=np.array([40.0, 40.0]),
            lon=np.array([-97.0, -92.0]),
            price=np.array([3.50, 3.00]),
            meta=[
                {"name": "Stop A", "address": "I-80", "city": "Kearney", "state": "NE",
                 "lat": 40.0, "lon": -97.0, "price": 3.50},
                {"name": "Stop B", "address": "I-80", "city": "Lincoln", "state": "NE",
                 "lat": 40.0, "lon": -92.0, "price": 3.00},
            ],
        )

    def test_route_endpoint_returns_plan(self):
        with mock.patch("routing.services.osrm.get_route", side_effect=self._fake_route), \
             mock.patch("routing.services.get_station_store", side_effect=self._fake_store):
            resp = self.client.get(
                "/api/route/", {"start": "40.0,-100.0", "finish": "40.0,-90.0"}
            )
        self.assertEqual(resp.status_code, 200)
        body = resp.json()
        self.assertTrue(body["feasible"])
        self.assertEqual(body["route"]["total_distance_miles"], 520.0)
        self.assertAlmostEqual(body["fuel"]["total_gallons"], 52.0, places=1)
        self.assertGreater(body["fuel"]["total_cost_usd"], 0)
        self.assertIn("geojson", body["route"])
        self.assertTrue(len(body["fuel_stops"]) >= 1)

    def test_missing_param_is_400(self):
        resp = self.client.get("/api/route/", {"start": "40,-100"})
        self.assertEqual(resp.status_code, 400)

    def test_bad_location_is_400(self):
        resp = self.client.get(
            "/api/route/", {"start": "Nowheresville, ZZ", "finish": "Chicago, IL"}
        )
        self.assertEqual(resp.status_code, 400)
