# eSIM price explorer (esim-compare)

Static site: `index.html` reads `data.json` and filters it in the browser. No backend.

## Data (the only files you edit)
- `providers.json`: one entry per shop: `url`, `referralUrl` (your affiliate link, used for the Buy button when set), `coupon`, `couponNote`, `note`.
- `plans.csv`: one row per plan. `provider` must match a key in `providers.json`. Currencies: EUR, USD, ILS. Use `999` in `gb` for unlimited data, and `Unlimited` in `days` for no-expiry plans.
- `data.json` is generated: `python3 scripts/build.py` (also stamps the "updated" date). Conversion rates live in `RATES_TO_EUR` in that script.

## Adding a shop
1. Add an entry to `providers.json`.
2. Add its rows to `plans.csv`.
3. Commit/push. Cloudflare Pages runs the build and redeploys.

## Preview locally
`python3 scripts/build.py && python3 -m http.server 8000`, then open http://localhost:8000

## Deploy
Cloudflare Pages, project `esim-compare`. Git-connected settings: build command `python3 scripts/build.py`, output directory `/`.
Manual deploy: `python3 scripts/build.py && npx wrangler pages deploy . --project-name esim-compare`
