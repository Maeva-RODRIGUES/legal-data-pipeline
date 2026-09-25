CREATE SCHEMA IF NOT EXISTS silver;

-- Common schema for decisions, rebuilt from Bronze on every run.
CREATE TABLE IF NOT EXISTS silver.decisions (
    source           TEXT        NOT NULL,
    external_id      TEXT        NOT NULL,  -- same identifier as Bronze
    decision_number  TEXT,
    issuer           TEXT,                  -- court or authority
    decision_type    TEXT,                  -- short controlled vocabulary
    decision_date    DATE,
    title            TEXT,
    text             TEXT,
    sectors          TEXT[]      NOT NULL DEFAULT '{}',
    url              TEXT,
    attributes       JSONB       NOT NULL DEFAULT '{}',  -- source-specific fields
    built_at         TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (source, external_id)
);
