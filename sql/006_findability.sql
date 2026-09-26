CREATE SCHEMA IF NOT EXISTS search;

-- One row per evaluation run, mode and title boost (title_boost NULL for the number mode).
CREATE TABLE IF NOT EXISTS search.findability_runs (
    eval_id      BIGSERIAL    PRIMARY KEY,
    run_id       BIGINT       NOT NULL REFERENCES bronze.collection_runs(run_id),
    index_name   TEXT         NOT NULL,  -- concrete index behind the alias
    mode         TEXT         NOT NULL CHECK (mode IN ('number', 'title')),
    title_boost  NUMERIC(5,2),           -- NULL for number
    sample_size  INT          NOT NULL,
    hit_at_1     NUMERIC(5,4),           -- NULL if sample_size = 0
    hit_at_10    NUMERIC(5,4),
    mrr          NUMERIC(5,4),
    created_at   TIMESTAMPTZ  NOT NULL DEFAULT now(),
    UNIQUE NULLS NOT DISTINCT (run_id, mode, title_boost),
    CHECK ((mode = 'number') = (title_boost IS NULL))
);

-- One row per searched decision; run_id, mode and title_boost repeated for readable queries.
CREATE TABLE IF NOT EXISTS search.findability_results (
    result_id         BIGSERIAL    PRIMARY KEY,
    eval_id           BIGINT       NOT NULL REFERENCES search.findability_runs(eval_id),
    run_id            BIGINT       NOT NULL REFERENCES bronze.collection_runs(run_id),
    mode              TEXT         NOT NULL,
    title_boost       NUMERIC(5,2),
    doc_id            TEXT         NOT NULL,  -- source|external_id
    has_text          BOOLEAN      NOT NULL,
    ambiguous_title   BOOLEAN      NOT NULL,
    ambiguous_number  BOOLEAN      NOT NULL,
    rank              INT          CHECK (rank BETWEEN 1 AND 10),  -- NULL if not in the top 10
    total_hits        INT          NOT NULL
);
