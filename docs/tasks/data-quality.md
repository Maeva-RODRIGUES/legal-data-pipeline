# Task: data quality checks (`src/quality/`)

## Goal
Measure the quality of the pipeline with declarative checks: each check is a SQL query with an expectation.
Results are stored at every run, so that quality can be followed over time.
Known, documented gaps must not raise alerts; new gaps must stand out.

## Division of work
- **Maintainer (me)**: the checks catalog in `src/quality/checks.yml`, including every SQL query and expectation.
- **Agent**: the engine (loading, execution, evaluation, storage, report), the migration, the tests and the README section.
- **Never modify the SQL or the expectations in `checks.yml`.** If a query looks wrong or returns an unexpected result, report it.

## Check format (`src/quality/checks.yml`)
```yaml
- name: bronze_rows_missing_from_silver
  dimension: completeness      # completeness | validity | uniqueness | consistency | freshness
  severity: error              # error | warning
  description: Bronze decisions absent from Silver, per source.
  sql: |
    SELECT b.source, count(*) FILTER (WHERE s.external_id IS NULL) AS value
    FROM bronze.raw_documents b
    LEFT JOIN silver.decisions s
      ON s.source = b.source AND s.external_id = b.external_id
    WHERE b.source IN ('judilibre', 'adlc-opendata')
    GROUP BY b.source;
  expect:
    judilibre: {op: "==", value: 0}
    adlc-opendata: {op: "==", value: 0}
```
- Every query returns exactly two columns: `source` (text) and `value` (number), one row per source.
- `expect` contains an optional `default` entry and/or source-specific entries; at least one entry is required.
- `expect.default` applies to every source returned by the query; a source-specific entry overrides it (e.g. `judilibre: {op: "==", value: 100}` for a known, accepted gap).
- Declaring a source explicitly means it must be present in the result (see `no_data`).
- Allowed operators: `==`, `<=`, `>=`, `<`, `>`.
- `description` may be written on several lines (YAML `>-`).

## Evaluation
- For each row: `pass` if the value meets the applicable expectation, otherwise `fail`.
- A source listed explicitly in `expect` but absent from the result: status `no_data`.
- A row whose source has no applicable expectation (no specific entry and no `default`): status `unchecked`, reported but never a failure.
- A query that raises an error: status `query_error`; the run continues with the other checks.
- A `fail`, `no_data` or `query_error` on a check with severity `error` makes the run fail.

## Storage
Migration `sql/004_quality.sql`: schema `quality`, table `check_results`:
- `run_id` (reference to `bronze.collection_runs`), `check_name`, `dimension`, `source`,
- `value` (numeric, nullable), `expected` (text, e.g. `== 0`, nullable for `unchecked`), `severity`, `status`,
- `checked_at` (timestamptz, default `now()`).

Document in the README how to apply it by hand on an existing database, like `003`.

## Run script
- `python -m src.quality.run`: logged in `bronze.collection_runs` (source `quality`, `date_type` = `checks`, date of the day).
- Check queries run in a read-only transaction; results are stored afterwards.
- A failing query must not prevent the other checks from running (e.g. use a savepoint per check).
- Print a report grouped by status (failures first), with check name, source, value and expectation.
- Exit code 1 if the run fails (see Evaluation), 0 otherwise: this will later let Celery or CI stop the pipeline.

## Dependencies
- Add `pyyaml` to `requirements.txt`.

## Tests (no database, no network)
- Every operator, including boundaries.
- Source-specific expectation overriding the default.
- A check without `default`: a declared source missing from the result gives `no_data`; an undeclared source gives `unchecked`.
- `query_error` status.
- Run failure only for `error` severity.
- Loading `checks.yml`: missing `sql`, empty `expect`, unknown operator or unknown severity are rejected with a clear message.
- The real `src/quality/checks.yml` loads without error.

## Acceptance criteria
- `pytest` and `pre-commit run --all-files` pass.
- A real run stores one result per check and source, and prints the report.
- With the current data, every check passes: the known gaps are covered by the expectations.

## Deliverable
A `feat/data-quality` branch with separate commits. Do not merge it, do not push it.

## Checks catalog (queries written by the maintainer in `checks.yml`)
| Check | Dimension | Severity | Expectation |
|---|---|---|---|
| `bronze_rows_missing_from_silver` | completeness | error | 0 for each source |
| `missing_decision_date` | completeness | error | 0 |
| `missing_decision_type_pct` | completeness | warning | Judilibre: 100 % (known); ADLC: 0 % |
| `empty_text` | completeness | warning | ADLC: ≤ 30 (known as of 25/09/2026); Judilibre: 0 |
| `impossible_decision_date` | validity | error | 0 |
| `duplicate_decision_number` | uniqueness | warning | ADLC: ≤ 5 (known); Judilibre: 0 |
| `number_year_mismatch` | consistency | warning | ADLC: ≤ 3 (known); a one-year gap is normal |
| `hours_since_last_success` | freshness | warning | ≤ 168 hours for each step |
| `site_decisions_missing_from_opendata` | freshness | warning | 0 |
