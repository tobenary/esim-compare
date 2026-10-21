#!/usr/bin/env python3
"""Refresh data/plans.json from the shops' websites (run daily by .github/workflows/daily-update.yml).

For every shop with a scraper in scrapers.py the plans are replaced by what the site shows today.
If a scraper fails or finds far fewer plans than before, the previous plans are kept and marked stale,
and the run exits with code 1 so CI can open an issue. Shops without a scraper keep their last known
prices (status "manual"). Writes report.md with a summary.

Usage: python3 scripts/update_data.py
"""
import csv
import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import scrapers  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data" / "plans.json"
DEFAULT_RATES = {"EUR": 1.0, "USD": 0.86, "ILS": 0.26}
MIN_KEEP_RATIO = 0.5  # fewer than half the previous plans -> treat as a broken scraper
BIG_CHANGE = 0.4  # report price moves larger than this


def seed_from_csv():
    """One-time migration from the old hand-edited plans.csv."""
    providers = {}
    with open(ROOT / "plans.csv", encoding="utf-8", newline="") as f:
        for r in csv.DictReader(f):
            p = providers.setdefault(r["provider"], {"status": "manual", "fetchedAt": None, "error": None, "plans": []})
            p["plans"].append({"days": r["days"], "region": r["region"], "gb": float(r["gb"]), "price": float(r["price"]),
                               "currency": r["currency"], "perks": r["perks"], "notes": r["notes"], "url": r.get("url", "")})
    return {"rates": dict(DEFAULT_RATES), "ratesAsOf": None, "providers": providers}


def fetch_rates(prev):
    """Daily EUR conversion rates (ECB via frankfurter). Keeps the previous ones if the API is down."""
    rates, as_of = dict(prev.get("rates") or DEFAULT_RATES), prev.get("ratesAsOf")
    used = {p["currency"] for prov in prev["providers"].values() for p in prov["plans"]}
    for cur in sorted((used | {"USD", "ILS"}) - {"EUR"}):
        try:
            body = scrapers.fetch(f"https://api.frankfurter.dev/v1/latest?base={cur}&symbols=EUR", timeout=20)
            d = json.loads(body)
            rates[cur], as_of = round(d["rates"]["EUR"], 4), d["date"]
        except Exception as e:  # noqa: BLE001 - any failure just keeps the old rate
            print(f"rate {cur}: keeping previous ({e})")
    return rates, as_of


def key(p):
    return (p["region"], str(p["days"]), p["gb"], p.get("perks", ""))


def validate(plans):
    if not plans:
        raise RuntimeError("no plans found: page layout changed or the page was blocked")
    for p in plans:
        if not (p["price"] > 0 and p["gb"] > 0 and p["days"]):
            raise RuntimeError(f"implausible plan {p}")


def main():
    if DATA.exists():
        data = json.loads(DATA.read_text(encoding="utf-8"))
    elif (ROOT / "plans.csv").exists():
        data = seed_from_csv()
    else:
        sys.exit("no data/plans.json and no plans.csv to seed from")

    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%MZ")
    report, failed = [], False
    for name, scrape in scrapers.SCRAPERS.items():
        prov = data["providers"].setdefault(name, {"status": "manual", "fetchedAt": None, "error": None, "plans": []})
        old = prov["plans"]
        try:
            new = scrape()
            validate(new)
            if prov["status"] == "ok" and len(new) < MIN_KEEP_RATIO * len(old):
                raise RuntimeError(f"only {len(new)} plans found, previously {len(old)}")
        except Exception as e:  # noqa: BLE001 - keep old data, report, carry on with the other shops
            failed = True
            prov["status"], prov["error"] = "stale", str(e)[:300]
            report.append(f"- **{name}**: FAILED, kept previous {len(old)} plans ({prov['error']})")
            continue
        old_by_key = {key(p): p for p in old}
        changes = []
        for p in new:
            o = old_by_key.get(key(p))
            if o and o["price"] and abs(p["price"] - o["price"]) / o["price"] > BIG_CHANGE and p["currency"] == o["currency"]:
                changes.append(f"{p['region']} {p['days']}d {p['gb']}GB: {o['price']} -> {p['price']} {p['currency']}")
        prov.update(plans=new, status="ok", fetchedAt=now, error=None)
        line = f"- **{name}**: {len(new)} plans (was {len(old)})"
        report.append(line + ("; big price moves: " + "; ".join(changes) if changes else ""))

    for name, prov in data["providers"].items():
        if name not in scrapers.SCRAPERS:
            report.append(f"- {name}: no scraper, last known prices kept ({len(prov['plans'])} plans)")

    data["rates"], data["ratesAsOf"] = fetch_rates(data)
    data["updatedAt"] = now
    DATA.parent.mkdir(exist_ok=True)
    DATA.write_text(json.dumps(data, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    (ROOT / "report.md").write_text("# Daily data update\n\n" + "\n".join(report) + "\n", encoding="utf-8")
    print("\n".join(report))
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
