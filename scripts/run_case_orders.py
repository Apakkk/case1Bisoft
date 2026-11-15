"""Send the case's seven test orders to a running API and compare with the expected results.

Run: make case-orders   (API on http://localhost:8000; override with BASE_URL)
Exit code 1 if any order differs. Structured orders: no Jev call unless a carrier note restricts.
"""

import os
import sys

import httpx

ORDERS = [
    (1, "Miami", "Fort Lauderdale", 40, "Reefer", "M-Logistics", "30.00"),
    (2, "Miami", "Orlando", 40, "Dry", "S-Logistics", "94.00"),
    (3, "Miami", "Atlanta", 20, "Reefer", "B-Logistics", "660.00"),
    (4, "Jacksonville", "Savannah", 45, "Hazardous", "A-Logistics", "280.00"),
    (5, "Tampa", "Jacksonville", 45, "Dry", "S-Logistics", "80.00"),
    (6, "Miami", "Houston", 45, "Reefer", None, None),
    (7, "Tampa", "Orlando", 20, "Hazardous", "M-Logistics", "85.00"),
]


def main() -> int:
    base_url = os.environ.get("BASE_URL", "http://localhost:8000")
    failures = 0
    print(f"{'#':<3}{'Route':<30}{'Order':<16}{'Expected':<26}{'Got':<26}{'Status':<14}")
    with httpx.Client(base_url=base_url, timeout=30) as client:
        for n, origin, destination, size, cargo, carrier, cost in ORDERS:
            body = {"origin": origin, "destination": destination, "container_size": size, "cargo_type": cargo}
            data = client.post("/api/v1/quotes", json=body).raise_for_status().json()
            expected = f"{carrier} ${cost}" if carrier else "no carrier"
            got = f"{data['carrier']} ${data['total_cost']}" if data["carrier"] else "no carrier"
            ok = (data["carrier"], data["total_cost"]) == (carrier, cost)
            failures += not ok
            mark = "ok" if ok else "MISMATCH"
            route = f"{origin} -> {destination}"
            print(f"{n:<3}{route:<30}{f'{size} ft {cargo}':<16}{expected:<26}{got:<26}{data['status']:<14}{mark}")
    print(f"\n{len(ORDERS) - failures}/{len(ORDERS)} orders match the case.")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
