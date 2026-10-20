#!/usr/bin/env python3
"""Merge plans.csv + providers.json into data.json (run from anywhere: python3 scripts/build.py)."""
import csv
import json
import sys
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

# Approximate fixed rates -> EUR. Edit these when you update prices.
RATES_TO_EUR = {"EUR": 1.0, "USD": 0.86, "ILS": 0.26}

UNLIMITED_GB = 999  # sentinel used in the sheet


def parse_days(raw):
    raw = raw.strip()
    if raw.isdigit():
        return int(raw), raw
    if raw.lower() == "unlimited":
        return None, "ללא תפוגה"
    return None, raw  # e.g. "4 שנים" (long validity)


def main():
    providers = json.loads((ROOT / "providers.json").read_text(encoding="utf-8"))["providers"]
    rows = []
    with open(ROOT / "plans.csv", encoding="utf-8", newline="") as f:
        for r in csv.DictReader(f):
            currency = r["currency"].strip().upper()
            if currency not in RATES_TO_EUR:
                sys.exit(f"Unknown currency {currency!r} for {r['provider']}")
            name = r["provider"].strip()
            if name not in providers:
                sys.exit(f"Provider {name!r} is missing from providers.json")
            days, days_label = parse_days(r["days"])
            gb = float(r["gb"])
            price = float(r["price"])
            unlimited_data = gb >= UNLIMITED_GB
            price_eur = round(price * RATES_TO_EUR[currency], 2)
            rows.append({
                "provider": name,
                "days": days,
                "daysLabel": days_label,
                # Plans with no numeric day count are shown under the "Unlimited" filter.
                "unlimitedDays": days is None,
                "region": r["region"].strip(),
                "gb": None if unlimited_data else gb,
                "unlimitedData": unlimited_data,
                "price": price,
                "currency": currency,
                "priceEur": price_eur,
                "perks": r["perks"].strip(),
                "notes": r["notes"].strip(),
            })

    out = {
        "updated": date.today().isoformat(),
        "rates": RATES_TO_EUR,
        "providers": providers,
        "plans": rows,
    }
    (ROOT / "data.json").write_text(
        json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8"
    )
    print(f"Wrote {len(rows)} plans to data.json")


if __name__ == "__main__":
    main()
