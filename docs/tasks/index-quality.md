# Task: index findability evaluation (`src/search/evaluate.py`)

## Goal
Measure how well Silver decisions can be found in the Elasticsearch index, on a reproducible sample, and store the results so that quality checks can enforce thresholds and changes to search can be compared.

## Division of work
- **Maintainer (me)**: the evaluation design (this spec), the thresholds in `src/quality/checks.yml`, the choice of the title weight after measurement.
- **Agent**: the evaluation script, the migration, the tests and the README section.
- Never modify `src/search/mapping.json` or `src/quality/checks.yml`; report anything that looks wrong.

## Sample (reproducible)
- 200 ADLC decisions: `ORDER BY md5(external_id) LIMIT 200` on `silver.decisions`, source `adlc-opendata`.
- Plus every ADLC decision without text (`text IS NULL OR btrim(text) = ''`), if not already in the sample.
- Plus every Judilibre decision (number mode only: they have no title).
- A decision's title is **ambiguous** if the same title (trimmed) belongs to more than one Silver decision.

## Search modes
- `number`: exact `term` query on `decision_number` (Judilibre and ADLC decisions with a number).
- `title`: the decision's own title as query text, `multi_match` over `title^<boost>` and `text`, same query the future search API will use (ADLC decisions with a title).
- A decision is found at rank r if its document id (`source|external_id`) is the r-th hit; searched in the top 10 only.
- The query goes through the `decisions` alias.

## Metrics
For each mode (and title boost), overall and per group (`has_text` true/false; ambiguous title yes/no):
- hit@1, hit@10 (share of decisions found at rank 1, in the top 10);
- MRR (mean of 1/rank, 0 if not found in the top 10).

## Storage
Migration `sql/006_findability.sql`, schema `search`:
- `findability_runs`: `run_id` (reference to `bronze.collection_runs`), `index_name`, `mode`, `title_boost` (nullable for `number`), `sample_size`, `hit_at_1`, `hit_at_10`, `mrr`, `created_at`;
- `findability_results`: `run_id`, `mode`, `title_boost`, `doc_id`, `has_text`, `ambiguous_title`, `rank` (nullable), `total_hits`.
Document in the README how to apply it by hand.

## Run script
- `python -m src.search.evaluate [--title-boost 1 2 3]` (default `3`): evaluates `number` once and `title` once per boost.
- Logged in `bronze.collection_runs` (source `search-eval`, `date_type` = `evaluation`).
- Print a report: metrics per mode, boost and group, then the list of ADLC decisions not found in the top 10 by title (number, title, rank or "absent").
- Exit code 0 when the evaluation ran (thresholds are enforced by quality checks, not here).

## Tests (no Elasticsearch, no database, no network)
- Metrics on hand-made rankings (found at 1, at 3, absent; empty sample).
- Ambiguous title detection.
- Query building for both modes, including the title boost.
- Rank extraction from a fake search response.

## Acceptance criteria
- `pytest` and `pre-commit run --all-files` pass.
- A real run with `--title-boost 1 2 3` stores the results and prints the report.
- `number` mode finds 100% of the sample in the top 10 (otherwise, report the failures).

## Deliverable
A `feat/index-quality` branch with separate commits. Do not merge it, do not push it.
