#!/usr/bin/env python3
"""Weekly price sanity check. Fetches each provider page and looks for every plan's price
in the page text, then prints a Markdown report. It never edits plans.csv: a human reviews it.

Caveat: a price missing from the HTML does not prove the price changed. Some shops render
prices with JavaScript, so their pages can look empty to this script. Treat it as a hint.

Usage: python3 scripts/check_prices.py [report.md]
Exit code is 1 when anything needs a look, so CI can open an issue.
"""
import csv
import json
import re
import sys
import urllib.request
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; esim-compare-price-check)"}


def fetch_text(url):
    req = urllib.request.Request(url, headers=HEADERS)
    html = urllib.request.urlopen(req, timeout=30).read().decode("utf-8", "ignore")
    html = re.sub(r"(?is)<(script|style).*?</\1>", " ", html)
    return re.sub(r"<[^>]+>", " ", html)


def price_variants(price):
    # "2.49" -> also "2,49"; "18.0" / "18" -> "18"
    s = f"{float(price):.2f}".rstrip("0").rstrip(".")
    return {s, s.replace(".", ",")}


def has_price(text, price):
    for v in price_variants(price):
        if re.search(rf"(?<![\d.,]){re.escape(v)}(?![\d])", text):
            return True
    return False


def main():
    providers = json.loads((ROOT / "providers.json").read_text(encoding="utf-8"))["providers"]
    by_provider = defaultdict(list)
    with open(ROOT / "plans.csv", encoding="utf-8", newline="") as f:
        for row in csv.DictReader(f):
            by_provider[row["provider"]].append(row)

    lines, problems = [], 0
    for name, rows in by_provider.items():
        url = providers[name]["url"]
        try:
            text = fetch_text(url)
        except Exception as e:  # network, TLS, HTTP errors
            problems += 1
            lines.append(f"### {name}\nPage unreachable ({e.__class__.__name__}: {e}) - check {url} by hand.\n")
            continue
        missing = [r for r in rows if not has_price(text, r["price"])]
        if not missing:
            lines.append(f"### {name}\nAll {len(rows)} prices found on the page.\n")
            continue
        problems += 1
        if len(missing) == len(rows):
            lines.append(f"### {name}\nNone of {len(rows)} prices found. The page probably renders prices with "
                         f"JavaScript, so this can't be checked automatically - check {url} by hand.\n")
        else:
            items = "\n".join(
                f"- {r['days']} days, {r['gb']} GB: {r['price']} {r['currency']}" for r in missing)
            lines.append(f"### {name}\n{len(missing)} of {len(rows)} prices not found on the page "
                         f"(changed, or hidden by JavaScript). Check {url}:\n{items}\n")

    report = "# Weekly price check\n\n" + "\n".join(lines)
    if len(sys.argv) > 1:
        Path(sys.argv[1]).write_text(report, encoding="utf-8")
    print(report)
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
