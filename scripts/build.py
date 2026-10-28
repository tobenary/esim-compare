#!/usr/bin/env python3
"""Merge data/plans.json + providers.json + destinations.json into public/data.json.

data/plans.json is refreshed daily by scripts/update_data.py (run from anywhere: python3 scripts/build.py).
"""
import json
import sys
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

# Fallback rates -> EUR, used only if data/plans.json has none.
RATES_TO_EUR = {"EUR": 1.0, "USD": 0.86, "ILS": 0.26}

UNLIMITED_GB = 999  # sentinel for unlimited data


def parse_days(raw):
    raw = str(raw).strip()
    if raw.isdigit():
        return int(raw), raw
    if raw.lower() == "unlimited":
        return None, "ללא תפוגה"
    return None, raw  # e.g. "4 שנים" (long validity)


def load(name):
    return json.loads((ROOT / name).read_text(encoding="utf-8"))


def main():
    providers = load("providers.json")["providers"]
    destinations = load("destinations.json")
    store = load("data/plans.json")
    rates = store.get("rates") or RATES_TO_EUR
    valid_regions = set(destinations["regions"]) | {c for g in destinations["groups"] for c in g["countries"]}

    rows, skipped = [], {}
    for name, prov in store["providers"].items():
        if name not in providers:
            sys.exit(f"Provider {name!r} is missing from providers.json")
        for r in prov["plans"]:
            if r["currency"] not in rates:
                sys.exit(f"Unknown currency {r['currency']!r} for {name}")
            if r["region"] not in valid_regions:
                # Scraped data can contain codes we don't list (e.g. GigSky's "BL" or internal "1N"): skip and say so.
                skipped[(name, r["region"])] = skipped.get((name, r["region"]), 0) + 1
                continue
            days, days_label = parse_days(r["days"])
            gb = float(r["gb"])
            unlimited_data = gb >= UNLIMITED_GB
            rows.append({
                "provider": name,
                "days": days,
                "daysLabel": days_label,
                # Plans with no numeric day count are shown under the "Unlimited" filter.
                "unlimitedDays": days is None,
                "region": r["region"],
                "gb": None if unlimited_data else gb,
                "unlimitedData": unlimited_data,
                "price": r["price"],
                "currency": r["currency"],
                "priceEur": round(r["price"] * rates[r["currency"]], 2),
                "perks": r.get("perks", "").strip(),
                "notes": r.get("notes", "").strip(),
                "url": (r.get("url") or "").strip(),
                # True when the shop isn't refreshed automatically (or its last refresh failed).
                "stale": prov["status"] != "ok",
                **({"countries": r["countries"]} if r.get("countries") else {}),  # exact coverage, when the shop lists it
            })

    out = {
        "updated": (store.get("updatedAt") or date.today().isoformat())[:10],
        "rates": rates,
        "providers": providers,
        "destinations": destinations,
        "plans": rows,
    }
    (ROOT / "public" / "data.json").write_text(
        json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8"
    )
    for (name, region), n in sorted(skipped.items()):
        print(f"warning: skipped {n} {name} plans for unknown destination {region!r} (add it to destinations.json to show it)")
    print(f"Wrote {len(rows)} plans to public/data.json")


if __name__ == "__main__":
    main()
