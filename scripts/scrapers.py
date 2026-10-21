"""Per-shop scrapers. Each returns a list of plan dicts for one provider.

A plan dict has: days (str: "30", "Unlimited" or free text), region (a region id or ISO country code from
destinations.json), gb (number, 999 = unlimited data), price (float), currency, perks, notes, url.

Static pages are fetched with curl; pages that build their prices with JavaScript are rendered in headless
Chrome (set CHROME_BIN to override the binary). Parsers work on the visible page text, so a layout change
shows up as "no plans found" and update_data.py keeps the previous prices instead of publishing garbage.
"""
import html
import json
import os
import re
import shutil
import subprocess
from concurrent.futures import ThreadPoolExecutor
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


# --------------------------------------------------------------------- GigSky
# GigSky's website loads its prices from a public JSON API: one feed lists every destination, then one
# call per destination returns its plans (list price plus the site-wide discount shown on the page).
GIGSKY_FEED = ("https://cdn-prod.gigsky.com/planBundle/includeSponsorPlans=false&simType=ACME_GSMA_ESIM_V2"
               "&includePlanVariants=false&lang=en&version=2-plan-bundle-ext.json")
GIGSKY_PLANS = "https://services.gigsky.com/cams/api/v4/planBundles/{id}?startIndex=0&count=100&includeFreePlan=false&currency=USD"
GIGSKY_REGIONS = {"Europe": "europe", "Asia Pacific": "asia", "North America": "north-america",
                  "Middle East": "middle-east", "Africa": "africa", "World Plan": "global"}


def _gigsky_bundle(item):
    bundle, region = item
    url = "https://www.gigsky.com/region/esim-in-europe" if region == "europe" else "https://www.gigsky.com/"
    d = json.loads(fetch(GIGSKY_PLANS.format(id=bundle["planBundleId"]), timeout=30))
    out = []
    for p in d.get("plans", []):
        if p.get("freePlan") or not p.get("price"):
            continue
        pct = (p.get("discount") or {}).get("percentage") or 0
        price = round(p["price"] * (1 - pct / 100), 2)
        notes = f"כולל מבצע {pct}%" if pct else ""
        if p.get("chargingType") == "UNLIMITED":
            if p.get("isDayPlan"):  # priced per day; the site lets you pick the number of days
                out.append(plan(1, region, UNLIMITED, price, "USD", url, perks="ללא הגבלה, מחיר ליום (אפשר לבחור כמה ימים)", notes=notes))
            continue
        out.append(plan(p["validityPeriodInDays"], region, round(p["dataLimitInKB"] / 1048576, 3), price, "USD", url, notes=notes))
    return out


def gigsky():
    feed = json.loads(fetch(GIGSKY_FEED, timeout=60))["list"]
    todo = []
    for b in feed:
        if b["planBundleType"] == "COUNTRY" and len(b.get("countryCodes", [])) == 1:
            todo.append((b, b["countryCodes"][0]))
        elif b["planBundleName"] in GIGSKY_REGIONS:
            todo.append((b, GIGSKY_REGIONS[b["planBundleName"]]))
    out = []
    with ThreadPoolExecutor(max_workers=8) as pool:
        for rows in pool.map(_gigsky_bundle, todo):
            out += rows
    return out


# --------------------------------------------------------------------- BNESIM
# BNESIM's shop is a JS app on top of a public API; this is the call it makes for its full price list (EUR).
BNESIM_REGIONS = {"Europe 7": "europe", "Asia": "asia", "Middle East": "middle-east", "North America": "north-america",
                  "South America": "south-america", "Africa": "africa", "Oceania": "oceania",
                  "Global": "global", "Mini Global": "global"}


def bnesim():
    out = subprocess.run(["curl", "-sS", "--max-time", "90", "-A", UA, "-e", "https://shop.bnesim.com/", "-F", "a=SITE",
                          "-F", "lang=en-US", "-F", "one_time_products=0",
                          "https://api.bnesim.com/v0.1/sim_card_landing_pricing/"], capture_output=True, timeout=120)
    if out.returncode != 0:
        raise RuntimeError(f"BNESIM API call failed: {out.stderr.decode()[:150]}")
    products = json.loads(out.stdout.decode("utf-8", "ignore"))["products"]
    rows = []
    for p in products:
        if p["regional"]:
            region = BNESIM_REGIONS.get(p["region"])
            perks = f"{p['region'].replace(' 7', '')} ({len(p['coverages'])} מדינות)" if region else ""
        elif len(p["coverages"]) == 1:
            region, perks = p["coverages"][0], ""
        else:
            continue
        if not region:
            continue
        amount = float(p["amount"]) if p["unit"] == "GB" else float(p["amount"]) / 1024
        days = "30" if p["duration"] == 30 else "Unlimited"  # duration -1 = no expiry date
        rows.append(plan(days, region, round(amount, 3), p["price"], p["currency"], "https://shop.bnesim.com/", perks=perks))
    return rows


# ---------------------------------------------------------------------- Airalo
# Airalo draws its package lists in the browser and only shows fixed-data plans after clicking a tab, so this
# one needs Playwright (pip install playwright; it drives the installed Chrome). The page shows prices in a
# currency chosen from the visitor's location, so the currency is read from the page and converted later.
AIRALO_PAGES = [("europe", "europe-esim"), ("asia", "asia-esim"), ("middle-east", "middle-east-esim"),
                ("north-america", "north-america-esim"), ("south-america", "south-america-esim"),
                ("africa", "africa-esim"), ("oceania", "oceania-esim")] + [(iso, f"{slug}-esim") for iso, slug in {
    "US": "united-states", "FR": "france", "IT": "italy", "ES": "spain", "DE": "germany", "GB": "united-kingdom",
    "GR": "greece", "TR": "turkey", "PT": "portugal", "NL": "netherlands", "CH": "switzerland", "AT": "austria",
    "HR": "croatia", "CY": "cyprus", "CZ": "czech-republic", "HU": "hungary", "PL": "poland", "TH": "thailand",
    "JP": "japan", "KR": "south-korea", "CN": "china", "IN": "india", "VN": "vietnam", "ID": "indonesia",
    "SG": "singapore", "MY": "malaysia", "AE": "united-arab-emirates", "EG": "egypt", "MA": "morocco",
    "MX": "mexico", "CA": "canada", "BR": "brazil", "AR": "argentina", "AU": "australia", "NZ": "new-zealand"}.items()]
AIRALO_ROW = re.compile(r"(\d+) days?\s+(Unlimited|[\d.]+)\s+GB\s+([\d.]+)\s+([A-Z]{3})")


def airalo():
    from playwright.sync_api import sync_playwright  # imported here so other shops work without Playwright
    out, pages = [], 0
    with sync_playwright() as p:
        browser = p.chromium.launch(channel="chrome", headless=True)
        page = browser.new_context(locale="en-US", viewport={"width": 1300, "height": 900}).new_page()
        for region, slug in AIRALO_PAGES:
            url = f"https://www.airalo.com/{slug}"
            try:
                page.goto(url, wait_until="networkidle", timeout=60000)
                page.wait_for_timeout(1000)
                rows = AIRALO_ROW.findall(page.inner_text("body"))  # first tab: unlimited-data packages
                page.get_by_text("Fixed data", exact=True).first.click(timeout=5000)
                page.wait_for_timeout(1000)
                rows += AIRALO_ROW.findall(page.inner_text("body"))
            except Exception:  # noqa: BLE001 - a missing or slow page is skipped, not fatal
                continue
            seen, got = set(), []
            for days, data, price, cur in rows:
                if (days, data) in seen:
                    continue
                seen.add((days, data))
                unl = data == "Unlimited"
                got.append(plan(days, region, UNLIMITED if unl else float(data), price, cur, url,
                                perks="ללא הגבלה" if unl else ""))
            pages += bool(got)
            out += got
        browser.close()
    if pages < 5:
        raise RuntimeError(f"only {pages} Airalo pages had packages: layout changed or blocked?")
    return out


# ----------------------------------------------------------------------- World8
def world8():
    url = "https://world8.co.il/" + quote("מחירון") + "/"
    t = text(fetch(url))
    m = re.search(r"(\d+) דקות / \d+ סמס / 1GB גלישה = (\d+) ₪ תקף ל- 4 שנים", t)
    if not m:
        raise RuntimeError("World8 4-year plan price not found")
    minutes, price = m.groups()
    add = re.search(r"10GB גלישה = (\d+) ₪ ל- 30 יום", t)
    notes = "לא שווה" + (f"; תוספת 10GB לאירופה/ארה״ב: {add.group(1)} ₪ ל-30 יום" if add else "")
    return [plan("4 שנים", "global", 1, price, "ILS", url, perks=f"{minutes} דקות שיחה + {minutes} SMS, תקף ל-4 שנים", notes=notes)]


# Provider name (as in providers.json) -> scraper. Shops without one keep their last known prices.
SCRAPERS = {"World8": world8, "Airalo": airalo, "GigSky": gigsky, "BNESIM": bnesim, "Voye Global": voye, "Yesim": yesim, "WeSIM": wesim, "eSIM.io": esimio, "AirHub": airhub,
            "Harel Multi-Travel": harel}
