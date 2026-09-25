# Task: Autorité de la concurrence freshness scraper (`src/collector/adlc_scraper/`)

## Context
The full history already comes from the open data dataset (source `adlc-opendata` in Bronze, identifier = decision URL).
The listing page parser exists and is tested (`parsers.py`). Read `docs/sources/autorite-concurrence.md` before starting.

## To build
1. `client.py`: a polite HTTP client
   - checks robots.txt with `protego` (the `Disallow: /*?` rule must block any URL with query parameters);
   - User-Agent: `legal-data-pipeline (+https://github.com/Maeva-RODRIGUES/legal-data-pipeline)`;
   - at least 2 seconds between requests; retries on 429 and 5xx, following `judilibre/client.py`.
2. `run.py`: a single request, to the first page of `/fr/liste-des-decisions-et-avis`.
   - Store each decision in Bronze (source `adlc-scraper`, identifier = URL) with the run log.
   - Print the decisions listed on the website but missing from the `adlc-opendata` source.
3. Tests: robots.txt (URL with `?` rejected, listing page allowed), delay, retries, all without network.

## Constraints
- Never follow pagination or sector links; do not visit decision detail pages.

## Acceptance criteria
- `pytest` and `pre-commit` pass; two consecutive runs are idempotent.

## Deliverable
- A `feat/adlc-freshness-scraper` branch with separate commits. Do not merge it.
