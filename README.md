# Fuel Route Optimizer

A Django REST API that, given a **start** and **finish** within the USA, returns:

- the **driving route** (geometry you can draw on a map),
- the **cost-optimal fuel stops** along that route (a 500-mile-range vehicle may need several), and
- the **total fuel cost** for the trip (at 10 miles/gallon).

Fuel prices come from the supplied OPIS truckstop CSV. Routing comes from a free,
key-less OSRM endpoint, and the whole trip is planned with **exactly one** call to
that routing API.

---

## Contents

1. [Quick start](#quick-start)
2. [The API](#the-api)
3. [The map page](#the-map-page)
4. [How it works](#how-it-works)
5. [Assumptions & design decisions](#assumptions--design-decisions)
6. [Performance](#performance)
7. [Configuration](#configuration)
8. [Tests](#tests)
9. [Project layout](#project-layout)
10. [Attribution](#attribution)
11. [Loom talking points](#loom-talking-points)

---

## Quick start

Requires Python 3.11+ (developed on Django 6.0).

```bash
# 1. Install dependencies
pip install -r requirements.txt

# 2. (optional) apply Django's built-in migrations to silence the startup notice
python manage.py migrate

# 3. Build the station cache once (geocodes the CSV, ~0.1s; produces data/stations_cache.npz)
python manage.py build_station_cache

# 4. Run
python manage.py runserver
```

Then open the demo map at <http://127.0.0.1:8000/map/?start=Seattle,%20WA&finish=Miami,%20FL>
or hit the JSON API directly (see below).

> **Note on the station cache:** the cache file ships in `data/stations_cache.npz`, so
> step 3 is optional — the app builds it automatically on first request if it's missing.
> Run the command explicitly when you want a warm cache before the first call (recommended
> before recording a demo). Use `--force` to rebuild after changing the CSV.

> **Network:** the only outbound call at request time is to the OSRM routing server. If
> you are behind a restrictive firewall, point `OSRM_BASE_URL` at any OSRM-compatible host.

---

## The API

### `GET|POST /api/route/`

| Param     | Where                 | Required | Format                                                        |
|-----------|-----------------------|----------|---------------------------------------------------------------|
| `start`   | query (GET) or body   | yes      | `"City, ST"`, `"City, State"`, or `"lat,lon"`                 |
| `finish`  | query (GET) or body   | yes      | same as `start`                                               |
| `geometry`| query                 | no       | `false` to omit the GeoJSON line (smaller payload)            |

**Example**

```bash
curl "http://127.0.0.1:8000/api/route/?start=Los%20Angeles,%20CA&finish=Houston,%20TX"
```

**Response (200, abbreviated)**

```jsonc
{
  "start":  { "lat": 34.0522, "lon": -118.2437 },
  "finish": { "lat": 29.7604, "lon": -95.3698 },
  "route": {
    "total_distance_miles": 1547.9,
    "estimated_drive_time_hours": 22.6,
    "geojson": { "type": "LineString", "coordinates": [[-118.24, 34.05], ...] }
  },
  "vehicle": { "range_miles": 500, "mpg": 10 },
  "feasible": true,
  "fuel": {
    "total_gallons": 154.8,
    "total_cost_usd": 487.21,
    "number_of_stops": 5
  },
  "fuel_stops": [
    {
      "name": "Departure (Los Angeles, CA)",
      "address": null,
      "city": null, "state": null,
      "lat": 34.0522, "lon": -118.2437,
      "price_per_gallon": 3.499,
      "miles_into_trip": 0.0,
      "gallons_purchased": 12.4,
      "leg_cost_usd": 43.39,
      "pre_trip_topup": true
    },
    {
      "name": "Some Truckstop",
      "address": "123 Interstate Dr",
      "city": "Blythe", "state": "CA",
      "lat": 33.61, "lon": -114.59,
      "price_per_gallon": 3.219,
      "miles_into_trip": 124.0,
      "gallons_purchased": 38.2,
      "leg_cost_usd": 122.97,
      "pre_trip_topup": false
    }
  ]
}
```

> The first entry in `fuel_stops` is always the **departure** (`pre_trip_topup: true`):
> a virtual stop at mile 0, at the trip's start coordinates, priced at the nearest
> reachable station. Every entry after it is a real truck stop. Filter on
> `pre_trip_topup` if you only want the physical stops.

**Status codes**

| Code | Meaning                                                                 |
|------|-------------------------------------------------------------------------|
| 200  | Route found and feasible.                                               |
| 422  | Route found but **infeasible** (a gap longer than the 500-mi range, or no stations on a leg). `error` explains why; `fuel_stops` is empty. |
| 400  | Bad/missing input or a location that couldn't be geocoded.              |
| 502  | The routing provider failed or was unreachable.                         |
| 500  | Unexpected server error.                                                |

---

## The map page

### `GET /map/?start=...&finish=...`

A small self-contained Leaflet page that calls the JSON API and draws the route
plus numbered fuel-stop markers (with price/gallons popups) and a cost summary.
It exists purely to make *"return a map of the route"* literal and to make the
Loom walkthrough easy — it is not required by the API itself.

---

## How it works

The request flows through four steps, and **only step 2 touches the network**:

1. **Geocode the endpoints (0 network calls).**
   `start`/`finish` are resolved cheapest-first: a raw `lat,lon` is parsed
   directly; a `City, ST` is looked up in a bundled offline US gazetteer (the
   same table used to place the fuel stations). An optional Nominatim fallback
   for arbitrary street addresses exists but is **off by default**.

2. **Fetch the route — the single map/route API call.**
   One request to OSRM returns the full geometry, total driving distance, and
   duration. Results are cached by rounded coordinates, so repeat trips cost
   **zero** calls.

3. **Find stations in a corridor around the route.**
   The 8,151-row price CSV has only city/state — no coordinates — so every
   station is geocoded offline once and cached to `data/stations_cache.npz`.
   The route polyline is downsampled (~every 2 mi); a bounding-box pre-filter
   plus a vectorised haversine keeps only stations within
   `FUEL_CORRIDOR_MILES` (default 25 mi) of the line, tagged with how far into
   the trip they sit.

4. **Choose the cost-optimal stops (the "gas-station problem").**
   A classic greedy algorithm that is provably optimal for a fixed tank size:
   at each station, if a **cheaper** station is reachable on the current tank,
   buy just enough to coast there; otherwise fill up and jump to the cheapest
   station within range. The whole trip's gallons (`distance / mpg`) are priced;
   departure is a virtual stop at mile 0 priced at the **nearest reachable**
   station (you fill up at the closest truck stop before leaving), so the very
   first miles are costed realistically rather than at some far-off bargain
   price.

---

## Assumptions & design decisions

These are the judgement calls the spec left open. They're all centralised in
`settings.py` so they're easy to change.

- **One routing call, by construction.** OSRM returns geometry + distance +
  duration in a single response. Geocoding is deliberately kept *off* the
  routing budget by doing it offline; the spec's "1 call ideal" refers to the
  map/route API, and we hit it exactly once (zero on a cache hit).

- **Why OSRM?** It's free, needs no API key, and gives everything in one call.
  Any OSRM-compatible endpoint works — set `OSRM_BASE_URL`. (Trade-off: the
  public demo server has no SLA; for production you'd self-host or use a paid
  routing provider.)

- **Offline geocoding of the price CSV.** The CSV has no lat/lon, so stations
  must be positioned somehow. Calling a geocoder 6,600+ times would violate the
  "few external calls" requirement and be slow, so coordinates come from a
  bundled gazetteer keyed on `City, ST`. Coverage is ~99.8% of US rows; ~620
  rows are Canadian truckstops (out of scope) and ~15 are small US towns absent
  from the gazetteer. If you need every last US town, enable the Nominatim
  fallback — but the default keeps the app fully offline and fast.

- **Town-centroid positioning + a generous corridor.** Stations are placed at
  their town's centroid (the finest granularity the data allows), so the
  default 25-mile corridor is intentionally generous to absorb that
  approximation. Tighten `FUEL_CORRIDOR_MILES` if you want stops to hug the
  highway more closely.

- **Cost model & departure.** The vehicle pays for every mile of the trip:
  `total_gallons = total_distance / 10`. Departure is modelled as a virtual
  stop at mile 0, priced at the **nearest reachable station** — you fill up
  before leaving at the closest truck stop you could realistically reach, *not*
  at the cheapest one hundreds of miles down the route. The greedy is then free
  to buy only the minimum at that first (often pricier) stop and source the rest
  at genuinely cheap stations later. This stop is labelled `Departure (<start>)`,
  carries `pre_trip_topup: true`, and sits at the trip's actual start
  coordinates — so it never masquerades as a real station in a far-away city.

- **Feasibility.** A trip is infeasible if any two consecutive reachable
  stations (or the origin-to-first-station gap) exceed the 500-mile range, or if
  a leg has no stations at all. The API returns 422 with an explanation rather
  than a misleading number.

- **500 mi / 10 mpg are configurable**, not hard-coded into the logic
  (`VEHICLE_RANGE_MILES`, `VEHICLE_MPG`).

---

## Performance

Measured end-to-end against the real 6,614-station dataset (compute time
*excludes* the single OSRM round-trip, which dominates wall-clock and is cached
after the first identical request):

| Trip                | Distance | Stops | Compute time |
|---------------------|----------|-------|--------------|
| Chicago → Houston   | 1,127 mi | 4     | ~49 ms       |
| Los Angeles → NYC   | 2,889 mi | 14    | ~137 ms      |
| Seattle → Miami     | 3,222 mi | 19    | ~218 ms      |

The station table is loaded once per process (a thread-safe singleton backed by
the `.npz` cache, ~0.1 s to build) and reused across requests.

---

## Configuration

Everything is environment-overridable; see `.env.example`. Highlights:

| Variable               | Default                          | Purpose                                  |
|------------------------|----------------------------------|------------------------------------------|
| `OSRM_BASE_URL`        | `https://router.project-osrm.org`| Routing provider (any OSRM host).        |
| `VEHICLE_RANGE_MILES`  | `500`                            | Tank range.                              |
| `VEHICLE_MPG`          | `10`                             | Fuel economy.                            |
| `FUEL_CORRIDOR_MILES`  | `25`                             | Max distance a station may sit off-route.|
| `ROUTE_SAMPLE_MILES`   | `2`                              | Polyline downsample granularity.         |
| `NOMINATIM_FALLBACK`   | `0` (off)                        | Allow full street-address geocoding.     |
| `HTTP_TIMEOUT`         | `20`                             | Outbound HTTP timeout (seconds).         |

---

## Tests

```bash
python manage.py test
```

14 tests, all offline (the routing call and station store are mocked), covering
the optimizer (including a hand-verified multi-stop total and all three
infeasibility modes), corridor matching, geocoding, and the API view's success
and error paths.

---

## Project layout

```
fuelroute/
├── manage.py
├── requirements.txt
├── .env.example
├── data/
│   ├── fuel-prices.csv          # the supplied price list
│   ├── us_cities.csv            # bundled offline gazetteer (geocoding)
│   └── stations_cache.npz       # built artifact: geocoded, deduped stations
├── fuelroute/                   # project package (settings, urls, wsgi/asgi)
└── routing/                     # the app
    ├── views.py                 # JSON API + map page
    ├── serializers.py           # request validation + response shaping
    ├── urls.py
    ├── tests.py
    ├── management/commands/
    │   └── build_station_cache.py
    ├── templates/routing/map.html
    └── services/
        ├── __init__.py          # plan_trip() orchestration
        ├── osrm.py              # the single external routing call
        ├── geocoding.py         # endpoint geocoding (offline + optional Nominatim)
        ├── fuel_data.py         # load/cache the station table
        ├── optimizer.py         # corridor matching + greedy gas-station solver
        └── geo.py               # haversine, cumulative miles, downsampling
```

---

## Attribution

- **Routing:** [OSRM](https://project-osrm.org/) via the public demo server
  (`router.project-osrm.org`). Map data © OpenStreetMap contributors.
- **City coordinates:** [kelvins/US-Cities-Database](https://github.com/kelvins/US-Cities-Database)
  (MIT). Bundled as `data/us_cities.csv`.
- **Map tiles (demo page):** OpenStreetMap, rendered with
  [Leaflet](https://leafletjs.com/).
- **Fuel prices:** the OPIS truckstop CSV supplied with the assignment.

---

## Loom talking points

A suggested 5-minute structure:

1. **Postman / browser, ~2 min.** Hit `/api/route/` for a couple of trips
   (e.g. LA → Houston, then a coast-to-coast one) — point out the route summary,
   the ordered fuel stops with prices and gallons, and the total cost. Open
   `/map/` for the same trip to show the route + markers visually. Show a 422 on
   an infeasible/edge case.
2. **Code tour, ~2.5 min.** `plan_trip()` in `services/__init__.py` as the
   spine; emphasise the **single OSRM call** and that geocoding is offline;
   then the greedy solver in `optimizer.py` (the cost-optimality intuition) and
   the corridor matching.
3. **Wrap, ~0.5 min.** Note the assumptions (corridor width, cost model),
   caching (repeat trips = 0 routing calls), and the test suite.
