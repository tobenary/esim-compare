# eSIM price explorer (esim-compare)

Static site: `public/index.html` reads `public/data.json` and filters it in the browser. No backend.

## Data: updated automatically every day
Prices are no longer edited by hand. `.github/workflows/daily-update.yml` runs every day at 04:30 UTC (or on demand from the Actions tab):
1. `scripts/update_data.py` reads each shop's website with the scrapers in `scripts/scrapers.py` (static pages via curl, JavaScript pages via headless Chrome) and rewrites `data/plans.json`. Exchange rates come from the ECB (frankfurter.dev) the same way.
2. If `data/plans.json` changed, the workflow commits it. The push makes Cloudflare rebuild and redeploy the site.
3. If a shop's scraper fails or finds far fewer plans than before, its previous prices are kept (marked "not updated automatically" on the site) and the workflow opens/updates a GitHub issue labelled `data-update`.

Shops with a scraper: Voye Global, Yesim, WeSIM, eSIM.io, AirHub, Harel Multi-Travel. Shops without one (BNESIM, Airalo, GigSky, World8) keep their last known prices and are tagged on the site until a scraper is written.

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
