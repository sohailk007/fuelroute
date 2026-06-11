# ⛽ Fuel Route Optimizer

> Plan any road trip in the USA and pay the **minimum possible** for fuel.

![Python](https://img.shields.io/badge/Python-3.11+-blue)
![Django](https://img.shields.io/badge/Django-6.0-092E20)
![DRF](https://img.shields.io/badge/Django%20REST%20Framework-3.17-red)
![Tests](https://img.shields.io/badge/tests-14%20passing-brightgreen)

Give the API a **start** and a **finish**, and it returns the driving route, the smartest fuel stops along the way, and the total fuel cost — using **exactly one call** to an external routing API.

| The vehicle | The data |
|---|---|
| 🛣️ 500 miles max per tank | 📄 8,151 truckstops with real prices (CSV) |
| ⛽ 10 miles per gallon | 🗺️ Free OSRM routing, no API key needed |

---

## ✨ What it does

- 🗺️ **Returns the route** — distance, drive time, and map geometry (GeoJSON)
- 💰 **Picks the cheapest fuel stops** — using an optimal "gas station problem" algorithm
- 🧾 **Calculates total fuel cost** — every mile of the trip is paid for, honestly
- ⚡ **Responds fast** — 50–220 ms of compute, even coast-to-coast
- 🔌 **One external API call per trip** — repeated trips cost zero (cached)

---

## 🚀 Quick start

Needs Python 3.11+.

```bash
pip install -r requirements.txt
python manage.py migrate                # optional, silences a startup notice
python manage.py build_station_cache    # one-time: geocode the fuel CSV (~0.1s)
python manage.py runserver
```

Now open the built-in demo map:

**<http://127.0.0.1:8000/map/?start=Seattle,%20WA&finish=Miami,%20FL>**

---

## 📡 API

### `GET or POST /api/route/`

| Param | Required | Format |
|---|---|---|
| `start` | ✅ | `"City, ST"`, `"City, State"`, or `"lat,lon"` |
| `finish` | ✅ | same as `start` |
| `geometry` | — | `false` to omit the route line (smaller response) |

```bash
curl "http://127.0.0.1:8000/api/route/?start=Chicago,%20IL&finish=Houston,%20TX"
```

<details>
<summary><b>Example response</b> (click to expand)</summary>

```jsonc
{
  "route":   { "total_distance_miles": 1085.2, "estimated_drive_time_hours": 16.1, "geojson": {...} },
  "vehicle": { "range_miles": 500, "mpg": 10 },
  "feasible": true,
  "fuel":    { "total_gallons": 108.5, "total_cost_usd": 322.10, "number_of_stops": 4 },
  "fuel_stops": [
    { "name": "Departure (Chicago, IL)", "miles_into_trip": 0.0, "price_per_gallon": 3.45,
      "gallons_purchased": 8.1, "leg_cost_usd": 27.95, "pre_trip_topup": true },
    { "name": "Some Truckstop", "city": "Springfield", "state": "IL", "miles_into_trip": 81.0,
      "price_per_gallon": 3.19, "gallons_purchased": 50.0, "leg_cost_usd": 159.50, "pre_trip_topup": false }
  ]
}
```
</details>

> 💡 The first stop is always the **departure**: a virtual fill-up at mile 0, at the start point, priced at the nearest reachable station — so every mile of the trip is paid for. All later stops are real truckstops.

| Status | Meaning |
|---|---|
| `200` | Route found and feasible |
| `422` | Trip not possible (a gap between stations longer than 500 mi) |
| `400` | Bad input or unknown location |
| `502` | Routing provider unreachable |

There is also **`GET /map/?start=...&finish=...`** — a Leaflet page that draws the route and stops.

---

## ⚙️ How it works

flowchart LR
    A["📍 Geocode start/finish<br/>(offline, 0 calls)"] --> B["🛣️ Fetch route from OSRM<br/>(the single API call)"]
    B --> C["⛽ Keep stations within<br/>25 mi of the route"]
    C --> D["🧮 Greedy optimizer<br/>stops + total cost"]
```

1. **Geocode offline.** "Seattle, WA" is looked up in a bundled table of ~30,000 US cities. No geocoding API needed.
2. **One routing call.** OSRM returns geometry + distance + duration in a single response. Results are cached → repeating a trip costs **zero** calls.
3. **Find nearby stations.** The fuel CSV has no coordinates (only city/state), so all 8,151 stations are geocoded offline once and cached to a fast binary file (~99.8% US coverage). Distance math is vectorized with NumPy.
4. **Optimize the stops.** The classic *gas station problem* — provably optimal greedy rule: at each stop, if a **cheaper** station is reachable on the current tank, buy **just enough** fuel to coast there; otherwise **fill up**. You never carry expensive fuel past a cheap pump.

---

## 📌 Assumptions (made on purpose)

- Stations sit at their **town's center** — the CSV gives no street addresses — so the 25-mile route corridor is intentionally generous.
- Departure fuel is priced at the **nearest** station, not a bargain 300 miles away. You can't buy cheap fuel from your driveway.
- ~620 CSV rows are Canadian truckstops (outside the "within USA" scope); 15 tiny US towns are missing from the city table. Set `NOMINATIM_FALLBACK=1` for full street-address geocoding (off by default to keep external calls minimal).
- Range and mpg are **settings**, not hard-coded: `VEHICLE_RANGE_MILES`, `VEHICLE_MPG`.

---

## 🔧 Configuration

All optional, via environment variables (see `.env.example`):

| Variable | Default | What it does |
|---|---|---|
| `OSRM_BASE_URL` | public OSRM server | Any OSRM-compatible routing host |
| `VEHICLE_RANGE_MILES` | `500` | Tank range |
| `VEHICLE_MPG` | `10` | Fuel economy |
| `FUEL_CORRIDOR_MILES` | `25` | How far off-route a station may sit |
| `NOMINATIM_FALLBACK` | `0` | Allow full street-address geocoding |

---

## 🧪 Tests

```bash
python manage.py test    # 14 tests, fully offline (routing is mocked)
```

Covers the optimizer (including a hand-verified multi-stop cost and all infeasible cases), corridor matching, geocoding, and the API's success and error paths. `verify_fix.py` additionally checks a live running server end-to-end.

---

## 📁 Project layout

```
fuelroute/            Django settings and URLs
routing/views.py      API endpoint + map page
routing/services/     osrm.py        → the one external call
                      geocoding.py   → offline place lookup
                      fuel_data.py   → station table + cache
                      optimizer.py   → greedy solver + corridor match
data/                 fuel-prices.csv · us_cities.csv · stations_cache.npz
```

---

## 🙏 Credits

Routing by [OSRM](https://project-osrm.org/) · Map data © [OpenStreetMap](https://www.openstreetmap.org/) contributors · City coordinates from [kelvins/US-Cities-Database](https://github.com/kelvins/US-Cities-Database) (MIT) · Map UI by [Leaflet](https://leafletjs.com/)