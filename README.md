# eSIM price explorer (esim-compare)

Static site: `public/index.html` reads `public/data.json` and filters it in the browser. No backend.

## Data: updated automatically every day
Prices are no longer edited by hand. `.github/workflows/daily-update.yml` runs every day at 04:30 UTC (or on demand from the Actions tab):
1. `scripts/update_data.py` reads each shop's website with the scrapers in `scripts/scrapers.py` (static pages via curl, JavaScript pages via headless Chrome) and rewrites `data/plans.json`. Exchange rates come from the ECB (frankfurter.dev) the same way.
2. If `data/plans.json` changed, the workflow commits it. The push makes Cloudflare rebuild and redeploy the site.
3. If a shop's scraper fails or finds far fewer plans than before, its previous prices are kept (marked "not updated automatically" on the site) and the workflow opens/updates a GitHub issue labelled `data-update`.

Every shop has a scraper (`scripts/scrapers.py`): GigSky and BNESIM read the JSON APIs their websites use (all destinations); Voye Global, Yesim, WeSIM and eSIM.io are parsed from page text; Maya reads its partner JSON feed (`affiliates.maya.net`, exact country coverage per plan, mapped with `data/iso3.json`); AirHub and Harel are rendered in headless Chrome; Airalo is driven with Playwright (needs `pip install playwright`, it uses the installed Chrome) for about 40 regions/countries; World8 is a text parse of its price page. A shop without a scraper would keep its last known prices and be tagged on the site.

Files you can still edit:
- `providers.json`: one entry per shop: `url`, `referralUrl` (your affiliate link, used for the Buy button when set), `coupon`, `couponNote`, `note`, and optional `popup` (coupon dialog before visiting).
- `destinations.json`: regions and the countries each region covers (used by the destination picker).
- `data/plans.json` is generated; don't edit it by hand, the next run overwrites it for shops with a scraper. `public/data.json` is built from it by `python3 scripts/build.py`.

## Adding a shop
1. Add an entry to `providers.json`.
2. Write a scraper function in `scripts/scrapers.py` that returns plan dicts, and register it in `SCRAPERS`.
3. Run `python3 scripts/update_data.py`, check `report.md`, commit and push.

## Preview locally
`python3 scripts/build.py && python3 -m http.server 8000 -d public`, then open http://localhost:8000

## Deploy
Cloudflare (Workers static assets), project `esim-compare`, live at https://esim-compare.tomer-ben-arye.workers.dev
- Build command: `python3 scripts/build.py` (reads `data/plans.json`)
- Deploy command: `npx wrangler deploy` (reads `wrangler.jsonc`)
- Only `public/` is served. Never point the assets directory at the repo root: that would publish `.git/` and the source files.

## Saved versions (optionA)
The site as it looks today (Hebrew RTL, Europe-first destination picker, coupon popups, Geneva/ski banners, all 10 shops scraped) is saved as git tag **`optionA`** and branch **`option-a`** (same commit). A redesign can be tried freely on another branch; these stay untouched.

Recreate it exactly:
```
git clone https://github.com/tobenary/esim-compare.git && cd esim-compare
git checkout optionA            # the tag (or: git checkout option-a)
python3 scripts/build.py        # builds public/data.json from data/plans.json
python3 -m http.server 8000 -d public   # open http://localhost:8000
```
Put it back live (replace main with optionA, keeps history):
```
git checkout main
git revert --no-commit optionA..main && git commit -m "Restore optionA design"
git push
```
Cloudflare redeploys main automatically. The daily data update runs only on `main`; `option-a` keeps its data snapshot from the day it was saved (rebuild with fresh data: `git checkout main -- data/plans.json` then build).
