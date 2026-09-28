# Task: nightly pipeline with Celery (`src/pipeline/`)

## Goal
Run the whole pipeline automatically every night, in order, stopping at the first blocking failure, with every run logged. Existing scripts are reused as they are: no business logic is rewritten.

## Division of work
- **Maintainer (me)**: this spec (order, schedule, blocking rules, retries), the review of the plan, the real runs.
- **Agent**: the Celery application, tasks, chain, schedule, lock, Dockerfile, Compose services, tests and README section.
- Never modify `src/quality/checks.yml` or `src/search/mapping.json`.

## Architecture
- Celery with **Redis** as broker (and result backend if needed).
- The **worker** and **Beat** run in containers (the Celery worker is not supported on Windows), next to PostgreSQL and Elasticsearch.
- New `Dockerfile` for the application (Python 3.12 slim, non-root user, `requirements.txt` only).
- New Compose services: `redis`, `worker` (concurrency 1: the steps are heavy and sequential), `beat`.
- Inside Compose, services reach each other by name: `postgres:5432`, `elasticsearch:9200`, `redis:6379`. The worker gets its own `DATABASE_URL`, `ELASTICSEARCH_URL` and `CELERY_BROKER_URL`; `JUDILIBRE_API_KEY` comes from `.env`. Scripts run from Windows keep `127.0.0.1`.
- `data/` is mounted in the worker, for the open data file.
- No new port exposed on the host for Redis.

## Schedule
- Every night at **03:33, Europe/Paris** (Celery timezone set explicitly, so daylight saving time is handled).
- **On Sundays**, the chain starts with the open data ingestion.

## Chain (sequential)
1. Sundays only: open data ingestion (`src.collector.adlc_opendata.run`).
2. Judilibre collection (`src.collector.judilibre.run`, default lookback window).
3. ADLC scraper (`src.collector.adlc_scraper.run`) — **non-blocking**: a failure is logged, the chain continues.
4. Silver rebuild (`src.silver.run`).
5. Index rebuild (`src.search.run`).
6. Findability evaluation (`src.search.evaluate`).
7. Quality checks (`src.quality.run`).

Each task calls the existing script's entry point. A non-zero exit code or an exception fails the task; every step except the scraper stops the chain. A failed quality verdict (exit code 1) fails the pipeline run.

## Retries
- Only for network steps (Judilibre collection, scraper, open data download): automatic retries on connection and timeout errors, 3 at most, with exponential backoff.
- No retry for data steps (Silver, index, evaluation, quality): a failure there must be examined, not repeated.

## Lock
- A Redis lock prevents two pipeline runs at the same time. If a run is already in progress, the new one is skipped and logged. The lock expires after a safety timeout (for a crashed worker).

## Pipeline run log
- Each pipeline run is logged in `bronze.collection_runs` (source `pipeline`, `date_type` = `nightly` or `manual`): status `success` or `failed`, and in `error` the name of the failing step. No new table.
- A skipped run (lock held) is logged too, with status `skipped` if the column allows it, otherwise report how you log it.

## Manual trigger
- A command to start the full chain now, without waiting for 03:33, from Windows (e.g. `python -m src.pipeline.trigger`, or a documented `podman exec` command).

## Tests (no broker, no database, no network)
- Chain composition: order, Sunday step present only on Sundays, scraper non-blocking.
- Failure of a blocking step stops the chain; failure of the scraper does not.
- Lock held: the run is skipped.
- Schedule: 03:33 Europe/Paris.
- Retry policy: only the network steps retry.

## Acceptance criteria
- `pytest` and `pre-commit run --all-files` pass.
- `podman compose up -d` starts Redis, the worker and Beat; the worker connects to the broker.
- A manual trigger runs the whole chain; every step's run appears in `bronze.collection_runs`, and the pipeline run is logged with its status.
- A second trigger while the first is running is skipped.
- Beat shows the next run at 03:33 Paris time.

## README
A "Planification" section (architecture, schedule, chain, blocking rules, manual trigger, how to read the pipeline runs), the new services in "Lancer le projet", and the new files in "Structure du projet". Do not touch "En bref", "Avancement" or "Pièges des sources".

## Deliverable
A `feat/celery-pipeline` branch with separate commits. Do not merge it, do not push it.
