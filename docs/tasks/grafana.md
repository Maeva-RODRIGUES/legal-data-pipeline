# Task: pipeline supervision with Grafana (`grafana/`)

## Goal
Make visible, over time, what the pipeline already records: runs, collection volumes, quality checks and search. Grafana adds no data: it reads existing tables, read-only.

## Division of work
- **Maintainer (me)**: this spec, the plan review, and the check of every panel against figures I know.
- **Agent**: the Grafana service, the read-only database role, the provisioning, the dashboards and their SQL queries, the tests and the README section.
- Never modify `src/quality/checks.yml` or `src/search/mapping.json`.

## Service
- `grafana` service in `docker-compose.yml`: official OSS image, pinned to a recent stable version (report which one), port bound to `127.0.0.1:3000` only, data in a named volume.
- Admin password from `.env` (`GRAFANA_ADMIN_PASSWORD`, documented in `.env.example` without a real value). No anonymous access.
- Default time zone `Europe/Paris`.

## Read-only database access
- A dedicated PostgreSQL role for Grafana, with `SELECT` only, and only on the tables the dashboards need: `bronze.collection_runs`, `quality.check_results`, `search.index_stats`, `search.findability_runs`, `search.findability_results`.
- Created by a new migration (`sql/007_...`). **No password committed**: propose how the password is set from `.env`, both for a new volume and for an existing database (documented by hand, like `003` to `006`).

## Provisioning (dashboards as code)
- Data source and dashboards provisioned from files in `grafana/provisioning/`, loaded at startup: whoever clones the project gets the same dashboards.
- Dashboards stored as JSON in the repository; a change made in the UI must be exported back to the file to persist (document it).

## Dashboards
1. **Pipeline health**: status of the last pipeline run; history of pipeline runs with status and duration; hours since the last successful run of each step.
2. **Collection**: fetched, new and changed decisions per run and per source, over time.
3. **Quality**: state of each check over runs (state timeline: pass / fail / no_data / query_error); values of key checks over time with their expectation drawn as a threshold (empty text, duplicate numbers, number/year mismatch).
4. **Search**: indexed decisions per source at each rebuild; findability over time (hit@1, hit@10, MRR, by mode).

## SQL queries
- Written by the agent, one per panel, `SELECT` only.
- Each query is **run against the real local database** before being put in a panel; report, for each panel, what it shows today, so that I can check it against known figures.

## Out of scope
- No alerting (local project, no real recipient): mention it as a possible next step.

## Tests (no Grafana, no database, no network)
- Every dashboard file is valid JSON and uses the provisioned data source.
- Every panel query is read-only (`SELECT` or `WITH` only).
- The dashboards' time zone is `Europe/Paris`.

## Acceptance criteria
- `pytest` and `pre-commit run --all-files` pass.
- `podman compose up -d` starts Grafana; the four dashboards appear, with data, without any manual setup.
- The Grafana database role cannot write (checked with an `INSERT` refused).
- Memory use stays reasonable within the 4 GB WSL limit (report `podman stats`).

## README
A "Supervision" section (service, read-only access, dashboards, how to open them, how to persist a change), the new service in "Lancer le projet", the new files in "Structure du projet". Do not touch "En bref", "Avancement" or "Pièges des sources".

## Deliverable
A `feat/grafana` branch with separate commits. Do not merge it, do not push it.
