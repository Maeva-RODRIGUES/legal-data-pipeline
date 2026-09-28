#!/usr/bin/env bash
# Sets the password of the grafana_reader role (created by 007_grafana_reader.sql)
# from GRAFANA_DB_PASSWORD, read in the postgres container environment.
# Run by the image entrypoint when the volume is created (after 007), or by hand on an
# existing database (see the README).
# The password never reaches a log: it is a psql variable (not echoed), the role is
# checked before the ALTER ROLE can fail, and log_min_error_statement = panic keeps the
# server from logging the statement if it fails anyway.
# No `exit` and no global `set -u`: the entrypoint may source this file.

if [ -z "${GRAFANA_DB_PASSWORD:-}" ]; then
    echo "008_grafana_reader_password.sh: GRAFANA_DB_PASSWORD is empty, password not set" >&2
    false
elif [ "$(psql -tA --username "${POSTGRES_USER:-legal}" --dbname "${POSTGRES_DB:-legal}" \
        -c "SELECT 1 FROM pg_roles WHERE rolname = 'grafana_reader'")" != "1" ]; then
    echo "008_grafana_reader_password.sh: role grafana_reader missing, apply 007_grafana_reader.sql first" >&2
    false
elif psql -v ON_ERROR_STOP=1 -q --username "${POSTGRES_USER:-legal}" --dbname "${POSTGRES_DB:-legal}" \
        -v pw="$GRAFANA_DB_PASSWORD" <<'SQL'
SET log_min_error_statement = panic;
SET log_statement = 'none';
ALTER ROLE grafana_reader PASSWORD :'pw';
SQL
then
    echo "008_grafana_reader_password.sh: grafana_reader password set"
else
    echo "008_grafana_reader_password.sh: failed to set the grafana_reader password" >&2
    false
fi
