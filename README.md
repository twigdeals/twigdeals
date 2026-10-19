# Twig Deals

Hockey stick price tracker: twigdeals.com

- `collector/collect.py` reads public Shopify `/products.json` feeds (Bauer.com, Pro Hockey Life, Source for Sports, HockeyStickMan, Just Hockey, Discount Hockey, TheHockeyShop.com, HockeyTron, Sports Excellence). It checks robots.txt, waits 3 s between requests, matches products to `data/seed_sticks.csv` (with sub-tiers), and appends per-variant prices to `data/prices.db` (SQLite).
- `build.py` generates the static site into `dist/`: homepage drops, stick pages, curve + flex pages, sale guide. CAD is converted to USD at the Bank of Canada rate.
- `.github/workflows/collect-and-deploy.yml` runs twice daily: collect, commit `prices.db`, build, and deploy to Cloudflare Pages. The deploy step is skipped until the `CLOUDFLARE_API_TOKEN` and `CLOUDFLARE_ACCOUNT_ID` secrets exist.
- Affiliate link templates: `data/affiliates.json`. Newsletter embed: search `NEWSLETTER_EMBED` in `build.py`.

Local: `python3 collector/collect.py && python3 build.py && python3 -m http.server -d dist`
