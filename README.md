# Index Stocks Compass

**日経225・TOPIX Core30・S&P 500・NASDAQ-100・NYダウの構成銘柄と株価を毎日自動更新する静的サイト。**

- Public site: https://musclelove-777.github.io/index-stocks-compass/
- Data: Yahoo Finance (via `yfinance`) + Wikipedia (constituent lists)
- Hosting: GitHub Pages
- Automation: GitHub Actions (daily at JST 07:00)

## Architecture

```
├── index.html              # Top page (auto-generated)
├── {index}/index.html      # Per-index page (auto-generated)
├── data/{index}.json       # Latest snapshot per index
├── assets/style.css        # Styling (hand-written)
├── scripts/update.py       # Fetch + render (single entry point)
├── requirements.txt
├── sitemap.xml             # Auto-regenerated
├── robots.txt
└── .github/workflows/
    └── daily-update.yml    # Runs update.py at JST 07:00 and pushes changes
```

## Data flow (one-shot)

1. `scripts/update.py` reads `INDICES` dict (5 indices defined)
2. For each index:
   - `pandas.read_html()` scrapes constituent list from Wikipedia
   - `yfinance.download()` fetches 5-day history for all tickers in one batch
   - `yfinance.Ticker.fast_info` fills market cap and currency per ticker
3. Snapshot saved to `data/{slug}.json`
4. HTML templates rendered into `/` and `/{slug}/`
5. `sitemap.xml` regenerated with today's date

## Automation (GitHub Actions)

The workflow runs once a day (UTC 22:00 = JST 07:00), runs `update.py`, and pushes the resulting diff. If nothing changed (e.g. weekends / holidays), no commit is made. Manual runs are possible via the workflow dispatch UI.

Weekly constituent changes (semi-annual re-balances) are captured automatically because Wikipedia is re-scraped every run — a new ticker will simply appear in the next push.

## Local run

```bash
pip install -r requirements.txt
python scripts/update.py
# Open index.html in a browser
```

## Notes

- Not financial advice. Data accuracy depends on upstream sources (Yahoo Finance / Wikipedia).
- Tickers are normalized: JP uses `<code>.T`, US uses `AAPL`-style (dots converted to `-` for `yfinance`, e.g. `BRK-B`).
- Constituent tables on Wikipedia occasionally break when editors change column headings. `update.py` picks the best-matching table heuristically but may need adjustment.
