CREATE SCHEMA IF NOT EXISTS bronze;

-- Collect journal
CREATE TABLE IF NOT EXISTS bronze.collection_runs (
    run_id       BIGSERIAL PRIMARY KEY,
    source       TEXT        NOT NULL,
    date_start   DATE        NOT NULL,
    date_end     DATE        NOT NULL,
    started_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
    finished_at  TIMESTAMPTZ,
    status       TEXT        NOT NULL DEFAULT 'running',  -- running | success | failed
    nb_fetched   INT         NOT NULL DEFAULT 0,
    nb_new       INT         NOT NULL DEFAULT 0,
    nb_changed   INT         NOT NULL DEFAULT 0,
    error        TEXT
);

-- Raw documents
CREATE TABLE IF NOT EXISTS bronze.raw_documents (
    source          TEXT        NOT NULL,
    external_id     TEXT        NOT NULL,
    payload         JSONB       NOT NULL,
    payload_hash    TEXT        NOT NULL,
    first_seen_run  BIGINT      NOT NULL REFERENCES bronze.collection_runs(run_id),
    last_seen_run   BIGINT      NOT NULL REFERENCES bronze.collection_runs(run_id),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (source, external_id)
);
