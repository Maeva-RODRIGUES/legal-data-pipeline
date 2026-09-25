CREATE SCHEMA IF NOT EXISTS search;

-- One row per source and rebuild run, written even when the alias was not switched.
CREATE TABLE IF NOT EXISTS search.index_stats (
    stat_id         BIGSERIAL   PRIMARY KEY,
    run_id          BIGINT      NOT NULL REFERENCES bronze.collection_runs(run_id),
    index_name      TEXT        NOT NULL,  -- e.g. decisions_20260925_143000
    source          TEXT        NOT NULL,
    silver_count    INT,                   -- NULL if Silver could not be counted
    indexed_count   INT,                   -- NULL if the index could not be counted
    rejected_count  INT         NOT NULL DEFAULT 0,
    alias_switched  BOOLEAN     NOT NULL,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);
