# Task: Elasticsearch index of Silver decisions (`src/search/`)

## Goal
Make Silver decisions searchable: a full rebuild of an Elasticsearch index at every run, switched atomically behind an alias, with index statistics stored in PostgreSQL for quality checks.

## Division of work
- **Maintainer (me)**: the index mapping in `src/search/mapping.json` (fields, analyzers). **Never modify it**; if it looks wrong or Elasticsearch rejects it, report it.
- **Agent**: the Elasticsearch service, the indexer, the migration, the tests and the README section.

## Elasticsearch service (`docker-compose.yml`)
- Single-node Elasticsearch, pinned to a recent stable 8.x version (report which one and why).
- `discovery.type=single-node`, `xpack.security.enabled=false` (local use only), `ES_JAVA_OPTS=-Xms512m -Xmx512m`.
- Port 9200 bound to `127.0.0.1` only; data in a named volume.
- Add `ELASTICSEARCH_URL=http://127.0.0.1:9200` to `.env.example` (`127.0.0.1`, not `localhost`: see the README note on Windows).
- Add the official `elasticsearch` Python client to `requirements.txt`, with the same major version as the server.

## Documents
One document per Silver row (the 6 common columns and more), built by a **pure function** `to_document(row) -> (doc_id, document)`:
- `doc_id` = `f"{source}|{external_id}"`;
- fields exactly as declared in `mapping.json`: `source`, `external_id`, `decision_number`, `issuer`, `decision_type`, `decision_date`, `title`, `text`, `has_text`, `sectors`, `url`, `attributes`, `indexed_at`;
- `has_text` = the text is not NULL and not empty after trimming;
- `NULL` values stay absent or `null`, never replaced by a guessed value.

## Full rebuild with alias switch
1. Create a new index `decisions_<YYYYMMDD_HHMMSS>` with `mapping.json`.
2. Read `silver.decisions` in batches (server-side cursor) and send documents with the bulk API.
3. Refresh the index, then count documents per source and compare with Silver.
4. **Only if every count matches and no document was rejected**, move the `decisions` alias to the new index in a single atomic operation.
5. Keep the previous index (for rollback) and delete older ones.
6. If anything fails before the switch, delete the new index and leave the alias on the previous one: search never sees a half-built index.

## Index statistics
Migration `sql/005_search.sql`: schema `search`, table `index_stats`:
- `run_id` (reference to `bronze.collection_runs`), `index_name`, `source`,
- `silver_count`, `indexed_count`, `rejected_count`, `alias_switched` (boolean), `created_at`.

One row per source and run, written even when the switch did not happen. Document in the README how to apply it by hand, like `003` and `004`.

## Run script
- `python -m src.search.run`: logged in `bronze.collection_runs` (source `search`, `date_type` = `rebuild`).
- Print, per source, the Silver count, the indexed count and the rejected count, then whether the alias was switched.
- Exit code 1 if the alias was not switched, 0 otherwise.

## Tests (no Elasticsearch, no database, no network)
- `to_document`: document id, `has_text` (text, empty string, spaces only, NULL), NULL values kept as absent or null.
- The rebuild logic with a fake Elasticsearch client: alias switched when counts match; not switched and new index deleted when a count differs or a document is rejected; older indexes cleaned up, previous one kept.
- `mapping.json` loads and declares every field produced by `to_document` (and no other).

## Acceptance criteria
- `pytest` and `pre-commit run --all-files` pass.
- A real run indexes every Silver decision (6707 on the current database: 6683 ADLC, 24 Judilibre), counts match, and the alias points to the new index.
- A second run creates a new index, switches the alias and keeps exactly one previous index.

## Deliverable
A `feat/search-index` branch with separate commits. Do not merge it, do not push it.
