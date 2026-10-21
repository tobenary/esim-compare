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
import unicodedata
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor
from urllib.parse import quote

UA = "Mozilla/5.0 (compatible; esim-compare-bot)"
UNLIMITED = 999
ROOT = Path(__file__).resolve().parent.parent

# Shops name countries in their own way ("czech-republic", "UAE", "U.K."): map any of them to an ISO code using the
# English names in destinations.json plus these aliases.
ALIASES = {"usa": "US", "unitedstatesofamerica": "US", "uk": "GB", "greatbritain": "GB", "england": "GB", "uae": "AE",
           "czechrepublic": "CZ", "turkey": "TR", "hongkong": "HK", "macau": "MO", "macao": "MO", "myanmar": "MM",
           "burma": "MM", "macedonia": "MK", "swaziland": "SZ", "capeverde": "CV", "russianfederation": "RU",
           "southkorea": "KR", "korea": "KR", "vietnam": "VN", "ivorycoast": "CI", "palestine": "PS", "holland": "NL"}
_NAME_INDEX = {}


def _norm(name):
    name = unicodedata.normalize("NFKD", name.replace("&", " and ")).encode("ascii", "ignore").decode().lower()
    return re.sub(r"[^a-z0-9]", "", name)


def iso_from_name(name):
    """ISO code for a country name or URL slug as shops write it, or None if it isn't a country we list."""
    if not _NAME_INDEX:
        for code, n in json.loads((ROOT / "destinations.json").read_text(encoding="utf-8"))["names"].items():
            _NAME_INDEX[_norm(n)] = code
            _NAME_INDEX[_norm(n).replace("and", "")] = code
            _NAME_INDEX[_norm(re.sub(r"\bsar china\b|\(.*?\)", "", n, flags=re.I))] = code
    key = _norm(name)
    return ALIASES.get(key) or _NAME_INDEX.get(key) or _NAME_INDEX.get(key.replace("and", ""))


def fetch_many(urls, workers=8):
    """Fetch several pages in parallel; pages that fail (404, timeout) come back as None."""
    def one(u):
        try:
            return fetch(u)
        except Exception:  # noqa: BLE001
            return None
    with ThreadPoolExecutor(max_workers=workers) as pool:
        return list(pool.map(one, urls))


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
# voyeglobal.com/esim/<slug>/ exists for ~60 regions and countries; the shop's category sitemap lists them all.
VOYE_REGIONS = {"europe": "europe", "asia": "asia", "global": "global", "north-america": "north-america",
                "middle-east": "middle-east"}
VOYE_UNL_NOTE = "{} GB ליום במהירות גבוהה, אחר כך מואט"


def _voye_parse(t, region, url):
    out = [plan(days, region, int(gb), price, "USD", url)
           for gb, days, price in re.findall(r"Data (\d+)GB Valid for (\d+) Days More info USD\s*([\d.]+)", t)]
    out += [plan(days, region, UNLIMITED, price, "USD", url, perks=VOYE_UNL_NOTE.format(per))
            for per, days, price in re.findall(r"Unlimited Data Data (\d+)GB/Day Valid for (\d+) Days More info USD\s*([\d.]+)", t)]
    return out


def voye():
    sitemap = fetch("https://voyeglobal.com/en-category-sitemap.xml")
    slugs = {"europe"} | set(re.findall(r"https://voyeglobal\.com/esim/([a-z0-9-]+)/</loc>", sitemap))
    todo = [(slug, VOYE_REGIONS.get(slug) or iso_from_name(slug)) for slug in sorted(slugs)]
    todo = [(slug, region) for slug, region in todo if region]
    urls = [f"https://voyeglobal.com/esim/{slug}/" for slug, _ in todo]
    out = []
    for (slug, region), url, html_ in zip(todo, urls, fetch_many(urls)):
        if html_:
            out += _voye_parse(text(html_), region, url)
    if len(out) < 20:
        raise RuntimeError(f"only {len(out)} Voye plans found: layout changed?")
    return out


# ---------------------------------------------------------------------- Yesim
# The home page links every country page (yesim.tech/country/<slug>/); /regions links the region pages.
YESIM_REGIONS = {"europe-esim": ("europe", "אירופה + בריטניה (33 מדינות), דאטה בלבד", ""),
                 "asia-pacific-esim": ("asia", "אסיה-פסיפיק (15 מדינות), דאטה בלבד", "רשימת המדינות באתר Yesim, ודאו שהיעד כלול"),
                 "north-america-esim": ("north-america", "צפון אמריקה (3 מדינות), דאטה בלבד", "רשימת המדינות באתר Yesim, ודאו שהיעד כלול"),
                 "middle-east-esim": ("middle-east", "המזרח התיכון (9 מדינות), דאטה בלבד", "רשימת המדינות באתר Yesim, ודאו שהיעד כלול"),
                 "africa-esim": ("africa", "אפריקה (15 מדינות), דאטה בלבד", "רשימת המדינות באתר Yesim, ודאו שהיעד כלול"),
                 "south-america-esim": ("south-america", "דרום אמריקה (12 מדינות), דאטה בלבד", "רשימת המדינות באתר Yesim, ודאו שהיעד כלול")}
YESIM_ROW = re.compile(r"(\d+) GB • (\d+) days \$[\d.]+ / GB \$([\d.]+)(?: \$([\d.]+))?")


def yesim():
    slugs = sorted(set(re.findall(r'href="(?:https://yesim\.tech)?/country/([a-z0-9-]+)/"', fetch("https://yesim.tech/"))))
    todo = [(region, f"https://yesim.tech/regions/{slug}/", perks, note) for slug, (region, perks, note) in YESIM_REGIONS.items()]
    todo += [(iso, f"https://yesim.tech/country/{slug}/", "דאטה בלבד", "") for slug in slugs if (iso := iso_from_name(slug))]
    out, pages = [], 0
    for (region, url, perks, note), html_ in zip(todo, fetch_many([t[1] for t in todo])):
        if not html_:
            continue
        rows = YESIM_ROW.findall(text(html_))
        pages += bool(rows)
        for gb, days, price, orig in rows:
            n = "; ".join(x for x in (_sale(orig), note) if x)
            out.append(plan(days, region, int(gb), price, "USD", url, perks, n))
    if pages < 20:
        raise RuntimeError(f"only {pages} Yesim pages had plans: layout changed?")
    return out


# ---------------------------------------------------------------------- WeSIM
WESIM_BASE = "https://wesim.co.il/product-category/"
WESIM_LOCAL = "https://wesim.co.il/" + quote("סים-מקומי-local-sim") + "/"
WESIM_GLOBAL = "https://wesim.co.il/" + quote("סים-גלובלי-global-sim") + "/"
WESIM_EUROPE = WESIM_BASE + quote("esim-לאירופה") + "/"
WESIM_ROW = re.compile(r"GB\s+(\d+(?:\.\d+)?)\s+.+?\s+(\d+)\s+ימים\s+\$\s*([\d.]+)")


def wesim():
    slugs = set(re.findall(r'href="https://wesim\.co\.il/product-category/([a-z0-9-]+)/"', fetch(WESIM_LOCAL)))
    todo = [("europe", WESIM_EUROPE), ("global", WESIM_GLOBAL)]
    todo += [(iso, f"{WESIM_BASE}{slug}/") for slug in sorted(slugs) if (iso := iso_from_name(slug))]
    out, pages = [], 0
    for (region, url), html_ in zip(todo, fetch_many([u for _, u in todo])):
        if not html_:
            continue  # a country page that no longer exists is not an error
        rows = {(gb, days): price for gb, days, price in WESIM_ROW.findall(text(html_))}
        pages += bool(rows)
        perks = "מעל 200 מדינות" if region == "global" else ""
        out += [plan(days, region, float(gb), price, "USD", url, perks) for (gb, days), price in rows.items()]
    if pages < 20:
        raise RuntimeError(f"only {pages} WeSIM pages had plans: layout changed?")
    return out


# --------------------------------------------------------------------- eSIM.io
ESIMIO_REGIONS = [("europe", "regions/esim-europe"), ("asia", "regions/esim-asia-pacific"), ("global", "global/esim-global"),
                  ("middle-east", "regions/esim-middle-east"), ("north-america", "regions/esim-north-america"),
                  ("south-america", "regions/esim-south-america"), ("africa", "regions/esim-africa"),
                  ("oceania", "regions/esim-oceania")]  # pages that don't exist are skipped
UNL_NOTE = "ללא הגבלת נפח (שימוש הוגן), בדקו תנאים אצל הספק"


def esimio():
    slugs = sorted(set(re.findall(r'href="/destinations/(esim-[a-z0-9-]+)"', fetch("https://esim.io/destinations"))))
    todo = list(ESIMIO_REGIONS) + [(iso, f"destinations/{slug}") for slug in slugs
                                   if (iso := iso_from_name(slug.removeprefix("esim-")))]
    out, pages = [], 0
    for (region, path), html_ in zip(todo, fetch_many([f"https://esim.io/{path}" for _, path in todo])):
        if not html_:
            continue
        url = f"https://esim.io/{path}"
        m = re.search(r"30 Day Plans (.*?)(?: Unlimited Plans (.*?))? Select a Plan", text(html_))
        if not m:
            continue
        fixed, unl = m.group(1), m.group(2) or ""
        rows = [plan(30, region, int(gb), price, "USD", url) for gb, price in
                re.findall(r"(\d+) GB ([\d.]+) USD [\d.]+ USD / GB", fixed)]
        rows += [plan(days, region, UNLIMITED, price, "USD", url, perks=UNL_NOTE) for days, price in
                 re.findall(r"(\d+) Days ([\d.]+) USD", unl)]
        pages += bool(rows)
        out += rows
    if pages < 20:
        raise RuntimeError(f"only {pages} eSIM.io pages had plans: layout changed?")
    return out


# ---------------------------------------------------------------------- AirHub
# airhubapp.com loads its plans from airhub-node.airhubapp.com: one call lists destinations, one call per destination
# returns its plans (USD).
AIRHUB_API = "https://airhub-node.airhubapp.com/api/"
AIRHUB_REGIONS = {"Europe": "europe", "North America": "north-america", "Middle east": "middle-east", "Global": "global",
                  "Asia Pacific": "asia", "Africa": "africa", "South Latin America": "south-america"}


def _airhub_plans(item):
    name, region = item
    query = json.dumps({"countryName": {"$regex": f"^{re.escape(name)}$", "$options": "i"}, "planClass": "DATA_ALL"}, separators=(",", ":"))
    url = (f"{AIRHUB_API}plan/planByCountry?filter=CHEAPEST&query={quote(query, safe=':,')}"
           f"&projection=%7B%7D&options=%7B%22limit%22:0,%22skip%22:0%7D")
    try:
        plans = json.loads(fetch(url, timeout=40)).get("plans", [])
    except Exception:  # noqa: BLE001 - one destination failing is not fatal
        return []
    page = "https://www.airhubapp.com/esim/" + re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")
    if region != "europe" and not _url_ok(page):  # unknown page address: fall back to the home page
        page = "https://www.airhubapp.com/"
    out = []
    for p in plans:
        if p.get("planClass") != "data":  # skip the plans that bundle calls and texts
            continue
        m = re.match(r"(\d+) Days?", p.get("validity", ""))
        if not m or not float(p["sellingCost"] or 0):
            continue
        unlimited = not p.get("dataAllowance")
        gb = UNLIMITED if unlimited else float(p["dataAllowance"]) * (1 if p["dataAllowanceType"] == "GB" else 0.001)
        out.append(plan(m.group(1), region, gb, p["sellingCost"], "USD", page,
                        perks="ללא הגבלה (מהירות 5G, בכפוף לשימוש הוגן)" if unlimited else ""))
    return out


def airhub():
    listing = json.loads(fetch(AIRHUB_API + "countryRegion/countryRegion", timeout=40))["countryRegion"]
    todo = []
    for d in listing:
        region = AIRHUB_REGIONS.get(d["Name"]) if d["Type"] == "2" else iso_from_name(d["Name"])
        if region:
            todo.append((d["Name"], region))
    out = []
    with ThreadPoolExecutor(max_workers=8) as pool:
        for rows in pool.map(_airhub_plans, todo):
            out += rows
    if len(out) < 100:
        raise RuntimeError(f"only {len(out)} AirHub plans found: API changed?")
    return out


# ------------------------------------------------------- Harel Multi-Travel
# One app page lists every package ("-20% France 3 GB Data 30 days $10.0 $8.0"): list price, then the sale price.
HAREL_ROW = re.compile(r"-\d+% (.+?) (\d+(?:\.\d+)?) GB Data (\d+) days \$[\d.]+ \$([\d.]+)")


def harel():
    url = "https://harel-group.multi-travel.com/"
    out = []
    for name, gb, days, price in HAREL_ROW.findall(text(render(url))):
        region = "europe" if name == "אירופה" else iso_from_name(name)
        if region:
            out.append(plan(days, region, float(gb), price, "USD", url, perks="מחיר אחרי מבצע של 20%"))
    return out


# --------------------------------------------------------------------- GigSky
# GigSky's website loads its prices from a public JSON API: one feed lists every destination, then one
# call per destination returns its plans (list price plus the site-wide discount shown on the page).
GIGSKY_FEED = ("https://cdn-prod.gigsky.com/planBundle/includeSponsorPlans=false&simType=ACME_GSMA_ESIM_V2"
               "&includePlanVariants=false&lang=en&version=2-plan-bundle-ext.json")
GIGSKY_PLANS = "https://services.gigsky.com/cams/api/v4/planBundles/{id}?startIndex=0&count=100&includeFreePlan=false&currency=USD"
GIGSKY_REGIONS = {"Europe": "europe", "Asia Pacific": "asia", "North America": "north-america",
                  "Middle East": "middle-east", "Africa": "africa", "World Plan": "global"}
GIGSKY_HOME = "https://www.gigsky.com/all-countries"


def _gigsky_page(bundle, region):
    """The page for this destination on gigsky.com (regions: /region/esim-in-<name>, countries: /country/esim-in-<name>)."""
    slug = re.sub(r"[^a-z0-9]+", "-", bundle["planBundleName"].lower()).strip("-")
    if bundle["planBundleType"] == "COUNTRY":
        return f"https://www.gigsky.com/country/esim-in-{slug}"
    if region == "global":
        return GIGSKY_HOME
    return f"https://www.gigsky.com/region/esim-in-{slug}"


def _url_ok(url):
    try:
        out = subprocess.run(["curl", "-sSL", "-o", "/dev/null", "--max-time", "20", "-A", UA, "-w", "%{http_code}", url],
                             capture_output=True, timeout=30)
        return out.stdout.decode().startswith("2")
    except Exception:  # noqa: BLE001
        return False


def _gigsky_bundle(item):
    bundle, region = item
    url = _gigsky_page(bundle, region)
    if not _url_ok(url):  # a wrong guess would send people to a 404: fall back to the country list
        url = GIGSKY_HOME
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
# Page on shop.bnesim.com for each region product (plans/<slug>/); countries use plans/<iso2 lower>/.
BNESIM_PAGES = {"Europe 7": "europe", "Asia": "asia", "Middle East": "middle-east", "North America": "north-america",
                "South America": "south-america", "Africa": "africa", "Oceania": "oceania", "Global": "global",
                "Mini Global": "mini-global"}


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
            page = BNESIM_PAGES.get(p["region"], "")
        elif len(p["coverages"]) == 1:
            region, perks = p["coverages"][0], ""
            page = region.lower()
        else:
            continue
        if not region:
            continue
        amount = float(p["amount"]) if p["unit"] == "GB" else float(p["amount"]) / 1024
        days = "30" if p["duration"] == 30 else "Unlimited"  # duration -1 = no expiry date
        rows.append(plan(days, region, round(amount, 3), p["price"], p["currency"], f"https://shop.bnesim.com/plans/{page}/", perks=perks))
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
    "MX": "mexico", "CA": "canada", "BR": "brazil", "AR": "argentina", "AU": "australia", "NZ": "new-zealand",
    "SE": "sweden", "NO": "norway", "DK": "denmark", "FI": "finland", "IE": "ireland", "BE": "belgium", "IS": "iceland",
    "BG": "bulgaria", "RO": "romania", "SK": "slovakia", "SI": "slovenia", "EE": "estonia", "LV": "latvia",
    "LT": "lithuania", "MT": "malta", "AL": "albania", "RS": "serbia", "ME": "montenegro", "GE": "georgia",
    "PH": "philippines", "LK": "sri-lanka", "KH": "cambodia", "HK": "hong-kong", "TW": "taiwan", "QA": "qatar",
    "SA": "saudi-arabia", "JO": "jordan", "IL": "israel", "ZA": "south-africa", "KE": "kenya", "TZ": "tanzania",
    "PE": "peru", "CL": "chile", "CO": "colombia", "CR": "costa-rica", "DO": "dominican-republic"}.items()]  # missing pages are skipped
# Two layouts exist depending on the visitor: "3 days\nUnlimited\nGB\n10.00\nCHF" (tabs for fixed / unlimited
# data) and "3 days 1 GB $4.00 USD" (one flat list). One pattern covers both.
AIRALO_ROW = re.compile(r"(\d+) days?\s+(Unlimited|[\d.]+)(?:\s+GB)?\s+(?:[$€£]\s*)?([\d.]+)\s+([A-Z]{3})")


def airalo():
    from playwright.sync_api import sync_playwright  # imported here so other shops work without Playwright
    out, pages, last_error = [], 0, ""
    with sync_playwright() as p:
        browser = p.chromium.launch(channel="chrome", headless=True)
        page = browser.new_context(locale="en-US", viewport={"width": 1300, "height": 900}).new_page()
        for region, slug in AIRALO_PAGES:
            url = f"https://www.airalo.com/{slug}"
            rows = []
            try:
                page.goto(url, wait_until="networkidle", timeout=60000)
                page.wait_for_timeout(1000)
                rows = AIRALO_ROW.findall(page.inner_text("body"))  # first tab: unlimited-data packages
                tab = page.get_by_text("Fixed data", exact=True)
                if tab.count():  # the tabbed layout; the flat layout already listed everything above
                    try:
                        tab.first.click(timeout=4000)
                    except Exception:  # noqa: BLE001 - an overlay (cookie banner) can swallow the click
                        tab.first.dispatch_event("click", timeout=4000)
                    page.wait_for_timeout(1000)
                    rows += AIRALO_ROW.findall(page.inner_text("body"))
            except Exception as e:  # noqa: BLE001 - a missing or slow page is skipped, not fatal
                body = ""
                try:
                    full = re.sub(r"\s+", " ", page.inner_text("body"))
                    i = max(full.find("Choose your package"), 0)
                    body = full[i:i + 250]
                except Exception:  # noqa: BLE001
                    pass
                last_error = f"{slug}: {str(e).splitlines()[0][:100]} | rows before failure: {len(rows)} | page text: {body}"
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
        raise RuntimeError(f"only {pages} Airalo pages had packages: layout changed or blocked? last error: {last_error}")
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
