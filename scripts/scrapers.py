"""Per-shop scrapers. Each returns a list of plan dicts for one provider.

A plan dict has: days (str: "30", "Unlimited" or free text), region (a region id or ISO country code from
destinations.json), gb (number, 999 = unlimited data), price (float), currency, perks, notes, url.

Static pages are fetched with curl; pages that build their prices with JavaScript are rendered in headless
Chrome (set CHROME_BIN to override the binary). Parsers work on the visible page text, so a layout change
shows up as "no plans found" and update_data.py keeps the previous prices instead of publishing garbage.
"""
import html
import os
import re
import shutil
import subprocess
from urllib.parse import quote

UA = "Mozilla/5.0 (compatible; esim-compare-bot)"
UNLIMITED = 999


def fetch(url, timeout=45):
    out = subprocess.run(["curl", "-sSL", "--max-time", str(timeout), "-A", UA, "-w", "\n%{http_code}", url],
                         capture_output=True, timeout=timeout + 15)
    body, _, code = out.stdout.decode("utf-8", "ignore").rpartition("\n")
    if out.returncode != 0 or not code.startswith("2"):
        raise RuntimeError(f"GET {url} failed (curl {out.returncode}, HTTP {code}) {out.stderr.decode()[:120]}")
    return body


def _chrome():
    for c in (os.environ.get("CHROME_BIN"), shutil.which("google-chrome"), shutil.which("chromium"),
              shutil.which("chromium-browser"), "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"):
        if c and os.path.exists(c):
            return c
    raise RuntimeError("No Chrome/Chromium found (set CHROME_BIN)")


def render(url, timeout=120):
    out = subprocess.run([_chrome(), "--headless=new", "--disable-gpu", "--no-sandbox", f"--user-agent={UA}",
                          "--virtual-time-budget=20000", "--dump-dom", url], capture_output=True, timeout=timeout)
    if not out.stdout:
        raise RuntimeError(f"Chrome returned nothing for {url}")
    return out.stdout.decode("utf-8", "ignore")


def text(raw):
    raw = re.sub(r"(?is)<(script|style).*?</\1>", " ", raw)
    return re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", " ", raw)))


def plan(days, region, gb, price, currency, url, perks="", notes=""):
    return {"days": str(days), "region": region, "gb": gb, "price": float(price), "currency": currency,
            "perks": perks, "notes": notes, "url": url}


def _sale(orig, cur="$"):
    return f"מחיר מבצע (במקור {orig}{cur})" if orig else ""


# ---------------------------------------------------------------- Voye Global
def voye():
    url = "https://voyeglobal.com/esim/europe/"
    t = text(fetch(url))
    out = []
    for gb, days, price in re.findall(r"Data (\d+)GB Valid for (\d+) Days More info USD\s*([\d.]+)", t):
        out.append(plan(days, "europe", int(gb), price, "USD", url))
    note = "{} GB ליום במהירות גבוהה, אחר כך מואט"
    for per, days, price in re.findall(r"Unlimited Data Data (\d+)GB/Day Valid for (\d+) Days More info USD\s*([\d.]+)", t):
        out.append(plan(days, "europe", UNLIMITED, price, "USD", url, perks=note.format(per)))
    return out


# ---------------------------------------------------------------------- Yesim
YESIM = [("europe", "https://yesim.tech/regions/europe-esim/", "אירופה + בריטניה (33 מדינות), דאטה בלבד", ""),
         ("asia", "https://yesim.tech/regions/asia-pacific-esim/", "אסיה-פסיפיק (15 מדינות), דאטה בלבד",
          "רשימת המדינות באתר Yesim, ודאו שהיעד כלול"),
         ("north-america", "https://yesim.tech/regions/north-america-esim/", "צפון אמריקה (3 מדינות), דאטה בלבד",
          "רשימת המדינות באתר Yesim, ודאו שהיעד כלול")]


def yesim():
    out = []
    for region, url, perks, note in YESIM:
        t = text(fetch(url))
        for gb, days, price, orig in re.findall(r"(\d+) GB • (\d+) days \$[\d.]+ / GB \$([\d.]+)(?: \$([\d.]+))?", t):
            n = "; ".join(x for x in (_sale(orig), note) if x)
            out.append(plan(days, region, int(gb), price, "USD", url, perks, n))
    return out


# ---------------------------------------------------------------------- WeSIM
WESIM_BASE = "https://wesim.co.il/product-category/"
WESIM_PAGES = [("europe", quote("esim-לאירופה")), ("global", None)] + [(iso, slug) for iso, slug in {
    "AU": "australia", "BG": "bulgaria", "EG": "egypt", "FI": "finland", "GE": "georgia", "HU": "hungary",
    "IS": "iceland", "IN": "india", "JP": "japan", "NL": "netherlands", "NZ": "new-zealand", "PL": "poland",
    "RU": "russian-federation", "TH": "thailand", "TR": "turkey", "AE": "united-arab-emirates",
    "US": "united-states-of-america", "VN": "vietnam", "GR": "greece", "CY": "cyprus", "IT": "italy",
    "FR": "france", "CA": "canada", "GB": "united-kingdom", "PT": "portugal", "DE": "germany"}.items()]
WESIM_GLOBAL = "https://wesim.co.il/" + quote("סים-גלובלי-global-sim") + "/"
WESIM_ROW = re.compile(r"GB\s+(\d+(?:\.\d+)?)\s+.+?\s+(\d+)\s+ימים\s+\$\s*([\d.]+)")


def wesim():
    out, seen_pages = [], 0
    for region, slug in WESIM_PAGES:
        url = WESIM_GLOBAL if region == "global" else f"{WESIM_BASE}{slug}/"
        try:
            t = text(fetch(url))
        except RuntimeError:
            continue  # a country page that no longer exists is not an error
        rows = {(gb, days): price for gb, days, price in WESIM_ROW.findall(t)}
        seen_pages += bool(rows)
        perks = "מעל 200 מדינות" if region == "global" else ""
        for (gb, days), price in rows.items():
            out.append(plan(days, region, float(gb), price, "USD", url, perks))
    if seen_pages < 3:
        raise RuntimeError(f"only {seen_pages} WeSIM pages had plans: layout changed?")
    return out


# --------------------------------------------------------------------- eSIM.io
ESIMIO = [("europe", "regions/esim-europe"), ("asia", "regions/esim-asia-pacific"), ("global", "global/esim-global")] + [
    (iso, f"destinations/esim-{slug}") for iso, slug in {
        "US": "united-states-of-america", "JP": "japan", "IT": "italy", "GB": "united-kingdom", "MX": "mexico",
        "DE": "germany", "FR": "france", "ES": "spain", "TR": "turkey", "GR": "greece", "TH": "thailand",
        "CN": "china", "AE": "united-arab-emirates", "KR": "south-korea", "VN": "vietnam", "IN": "india"}.items()]
UNL_NOTE = "ללא הגבלת נפח (שימוש הוגן), בדקו תנאים אצל הספק"


def esimio():
    out, pages = [], 0
    for region, path in ESIMIO:
        url = f"https://esim.io/{path}"
        try:
            t = text(fetch(url))
        except RuntimeError:
            continue
        m = re.search(r"30 Day Plans (.*?)(?: Unlimited Plans (.*?))? Select a Plan", t)
        if not m:
            continue
        fixed, unl = m.group(1), m.group(2) or ""
        rows = [plan(30, region, int(gb), price, "USD", url) for gb, price in
                re.findall(r"(\d+) GB ([\d.]+) USD [\d.]+ USD / GB", fixed)]
        rows += [plan(days, region, UNLIMITED, price, "USD", url, perks=UNL_NOTE) for days, price in
                 re.findall(r"(\d+) Days ([\d.]+) USD", unl)]
        pages += bool(rows)
        out += rows
    if pages < 3:
        raise RuntimeError(f"only {pages} eSIM.io pages had plans: layout changed?")
    return out


# ---------------------------------------------------------------------- AirHub
def airhub():
    url = "https://www.airhubapp.com/esim/europe"
    t = text(render(url))
    m = re.search(r"Data Only \(\d+\)(.*?)Data \+ Voice \+ SMS", t)
    if not m:
        raise RuntimeError("AirHub 'Data Only' section not found")
    sec = m.group(1)
    out = [plan(days, "europe", int(gb), price, "USD", url)
           for gb, days, price in re.findall(r"(\d+) GB (\d+) Days \$ ([\d.]+) USD", sec)]
    out += [plan(days, "europe", UNLIMITED, price, "USD", url, perks="ללא הגבלה (מהירות 5G, בכפוף לשימוש הוגן)")
            for days, price in re.findall(r"Unlimited (\d+) Day \$ ([\d.]+) USD", sec)]
    return out


# ------------------------------------------------------- Harel Multi-Travel
def harel():
    url = "https://harel-group.multi-travel.com/"
    t = text(render(url))
    return [plan(days, "europe", float(gb), price, "USD", url, perks="מחיר אחרי מבצע של 20%")
            for gb, days, price in re.findall(r"אירופה (\d+(?:\.\d+)?) GB Data (\d+) days \$[\d.]+ \$([\d.]+)", t)]


# Provider name (as in providers.json) -> scraper. Shops without one keep their last known prices.
SCRAPERS = {"Voye Global": voye, "Yesim": yesim, "WeSIM": wesim, "eSIM.io": esimio, "AirHub": airhub,
            "Harel Multi-Travel": harel}
