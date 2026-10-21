# eSIM price explorer (esim-compare)

Static site: `public/index.html` reads `public/data.json` and filters it in the browser. No backend.

## Data (the only files you edit)
- `providers.json`: one entry per shop: `url`, `referralUrl` (your affiliate link, used for the Buy button when set), `coupon`, `couponNote`, `note`.
- `plans.csv`: one row per plan. `provider` must match a key in `providers.json`. `region` is a region id or an ISO country code from `destinations.json` (e.g. `europe`, `asia`, `global`, `US`, `TH`). Optional `url` deep-links the Buy button when the shop has no referral link. Currencies: EUR, USD, ILS. Use `999` in `gb` for unlimited data, and `Unlimited` in `days` for no-expiry plans.
- `public/data.json` is generated (not committed): `python3 scripts/build.py` (also stamps the "updated" date). Conversion rates live in `RATES_TO_EUR` in that script.

## Adding a shop
1. Add an entry to `providers.json`.
2. Add its rows to `plans.csv`.
3. Commit/push. Cloudflare Pages runs the build and redeploys.

## Preview locally
`python3 scripts/build.py && python3 -m http.server 8000 -d public`, then open http://localhost:8000

## Deploy
Cloudflare (Workers static assets), project `esim-compare`, live at https://esim-compare.tomer-ben-arye.workers.dev
- Build command: `python3 scripts/build.py`
- Deploy command: `npx wrangler deploy` (reads `wrangler.jsonc`)
- Only `public/` is served. Never point the assets directory at the repo root: that would publish `.git/` and the source files.

## Weekly price check
`.github/workflows/price-check.yml` runs every Monday (06:00 UTC) and can be started by hand from the repo's Actions tab. It runs `scripts/check_prices.py`, which looks for each plan's price on the provider's page. If something is missing or a page can't be read, it opens (or comments on) a GitHub issue labelled `price-check`. It never edits `plans.csv`: update the prices yourself and push. Prices that shops render with JavaScript (e.g. Airalo, AirHub) can't be read this way and are reported as "check by hand".
