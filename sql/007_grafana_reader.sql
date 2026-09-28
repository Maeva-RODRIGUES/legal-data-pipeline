-- Read-only role for Grafana: SELECT on the tables of the dashboards, nothing else.
-- No password here: it is set from GRAFANA_DB_PASSWORD by 008_grafana_reader_password.sh.
-- Without a password the role cannot log in.
DO $$
BEGIN
    IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'grafana_reader') THEN
        CREATE ROLE grafana_reader LOGIN;
    END IF;
END
$$;

ALTER ROLE grafana_reader CONNECTION LIMIT 5;
-- Second barrier if a write privilege were ever granted by mistake.
ALTER ROLE grafana_reader SET default_transaction_read_only = on;
-- A slow panel query must not hold the pipeline tables.
ALTER ROLE grafana_reader SET statement_timeout = '10s';

GRANT USAGE ON SCHEMA bronze, quality, search TO grafana_reader;
GRANT SELECT ON
    bronze.collection_runs,
    quality.check_results,
    search.index_stats,
    search.findability_runs,
    search.findability_results
TO grafana_reader;
