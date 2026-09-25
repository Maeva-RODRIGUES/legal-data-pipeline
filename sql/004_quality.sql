CREATE SCHEMA IF NOT EXISTS quality;

-- One row per check and source, for every quality run.
CREATE TABLE IF NOT EXISTS quality.check_results (
    result_id   BIGSERIAL   PRIMARY KEY,
    run_id      BIGINT      NOT NULL REFERENCES bronze.collection_runs(run_id),
    check_name  TEXT        NOT NULL,
    dimension   TEXT        NOT NULL,  -- completeness | validity | uniqueness | consistency | freshness
    source      TEXT,                  -- NULL for query_error (no row returned)
    value       NUMERIC,               -- NULL for no_data and query_error
    expected    TEXT,                  -- e.g. '== 0'; NULL for unchecked and query_error
    severity    TEXT        NOT NULL,  -- error | warning
    status      TEXT        NOT NULL,  -- pass | fail | no_data | unchecked | query_error
    error       TEXT,                  -- query or result error message, for query_error only
    checked_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);
