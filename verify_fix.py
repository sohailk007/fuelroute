"""Live verification of the departure-stop fix. Server must be running."""
import sys
import requests

BASE = "http://127.0.0.1:8000"
ROUTES = [("Big Cabin, OK", "Tomah, WI"), ("Seattle, WA", "Miami, FL")]
ok = True

def check(cond, msg):
    global ok
    print(("PASS" if cond else "FAIL"), "-", msg)
    ok = ok and cond

for start, finish in ROUTES:
    r = requests.get(f"{BASE}/api/route/",
                     params={"start": start, "finish": finish, "geometry": "false"},
                     timeout=90)
    check(r.status_code == 200, f"{start} -> {finish}: HTTP 200")
    if r.status_code != 200:
        continue
    d = r.json()
    stops = d["fuel_stops"]
    s0 = stops[0]
    check(s0["name"].startswith("Departure ("),
          "stop #1 is the labelled Departure entry (not a borrowed station name)")
    check(s0["miles_into_trip"] == 0.0 and s0["pre_trip_topup"] is True,
          "departure sits at mile 0 and is flagged pre_trip_topup")
    check(s0["city"] is None and s0["state"] is None,
          "departure carries no borrowed city/state")
    check(abs(s0["lat"] - d["start"]["lat"]) < 0.01
          and abs(s0["lon"] - d["start"]["lon"]) < 0.01,
          "departure coordinates == trip start coordinates")
    check(sum(1 for s in stops if s["pre_trip_topup"]) == 1,
          "exactly one pre-trip top-up; all later stops are real stations")
    avg = d["fuel"]["total_cost_usd"] / d["fuel"]["total_gallons"]
    cheapest = min(s["price_per_gallon"] for s in stops)
    check(avg >= cheapest - 1e-6,
          f"avg paid ${avg:.3f}/gal >= cheapest used price ${cheapest:.3f} (old bug violated this)")

r = requests.get(f"{BASE}/api/route/", params={"start": "40,-100"}, timeout=30)
check(r.status_code == 400, "missing finish -> 400")
r = requests.get(f"{BASE}/api/route/",
                 params={"start": "Nowheresville, ZZ", "finish": "Chicago, IL"}, timeout=30)
check(r.status_code == 400, "unresolvable location -> 400")

print("\nALL CHECKS PASSED" if ok else "\nSOME CHECKS FAILED")
sys.exit(0 if ok else 1)
