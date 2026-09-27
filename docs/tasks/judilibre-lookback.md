# Task: overlapping window for the Judilibre collector

## Why
Judilibre publishes decisions several days after their stated update date: the update window 15–16/09/2026 returned 16 decisions on 23/09 and 127 on 27/09 (124 rendered in September 2026). The incremental collection resumes strictly after the last successful run, so it would miss these late decisions, without any error.

## Goal
When no `--start` is given, the collector resumes **N days before** the end of the last successful run of the same date type, instead of right after it. Already known decisions are simply counted as unchanged, thanks to the content hash (the collector is idempotent).

## Behaviour
- New option `--lookback-days` (integer, default **14**, 0 allowed, negative refused).
- Without `--start`: `start = last successful end date + 1 day - lookback_days`, never after `end`.
- With `--start`: unchanged, `--lookback-days` is ignored (and the run says so in its output).
- No previous successful run: unchanged behaviour.
- The computed window is logged in `bronze.collection_runs` as today (`date_start`, `date_end`), so the overlap is visible in the run history.

## Implementation constraints
- The window computation is a **pure function** (last end date, today, lookback, explicit start and end) tested without database or network.
- No change to the collection itself, the hash logic or the Bronze storage.

## Tests (no database, no network)
- lookback 14, 0; negative value refused with a clear message;
- explicit `--start` wins over the lookback;
- no previous run;
- a start that would be after the end is clamped.

## Acceptance criteria
- `pytest` and `pre-commit run --all-files` pass.
- A real run without `--start` covers the last 14 days before the last successful run; running it twice in a row gives 0 new decisions on the second run.

## README
Document the option in "Lancer le projet" (collector options), and why it exists (one sentence, pointing to the Judilibre open question).

## Deliverable
A `feat/judilibre-lookback` branch with separate commits. Do not merge it, do not push it.
