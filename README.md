# price-compare

A small Python tool that compares listing prices between two public catalogue
sources and reports the items with the largest price gap. Reference prices come
from a free daily CSV snapshot; listings are read from a public storefront.

For full design notes, configuration, and the data-delivery convention, see
[`CLAUDE.md`](CLAUDE.md).

## Setup

```bash
pip install -r requirements.txt
playwright install chromium   # only needed for the live listing fetch
cp .env.example .env          # adjust variables (all optional, defaults shown)
```

The core (price load, matching, ranking, report) runs with `requests` + stdlib.
`playwright`, `selectolax`, `rapidfuzz` and `gspread` are optional at runtime.

## Usage

```bash
# Continuous loop (partial results flushed ~hourly):
python -m comc_scanner run --era recent

# Single pass (one chunk), resuming the saved cursor:
python -m comc_scanner once --era vintage

# Chunk the work so a run stays within a time budget:
python -m comc_scanner once --era vintage --max-sets-per-chunk 2 --max-pages 3

# Refresh the reference price snapshot:
python -m comc_scanner refresh-prices --era all

# Offline dry-run against bundled fixtures (no network):
python -m comc_scanner dry-run --era vintage --listings tests/fixtures/listings_sample.json
```

Run `python -m comc_scanner --help` for the full flag list.

## Tests

```bash
python -m pytest tests/
```

All tests under `tests/` are offline (no network): normalization, matching,
reference-price selection, era grouping, and the chunk cursor. They run without a
browser, so CI can stay green without installing one.

## Notes

- The live fetch reads a public storefront that sits behind a Cloudflare
  challenge, so a real browser (Playwright/Chromium) is used for that step; the
  rest is plain `requests`. Respect the target site's robots.txt and Terms of Use,
  keep request volume low, and treat this as a personal-use tool.
- Each result row carries an explicit match `confidence`; low-confidence rows are
  flagged for manual review rather than dropped.
- Prices are in USD; there is no currency conversion.
