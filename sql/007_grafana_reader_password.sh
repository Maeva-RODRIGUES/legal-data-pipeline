#!/usr/bin/env bash
# Sets the password of the grafana_reader role (created by 007_grafana_reader.sql)
# from GRAFANA_DB_PASSWORD, read in the postgres container environment.
# Run by the image entrypoint when the volume is created, or by hand on an existing
# database (see the README). The password is a psql variable: never echoed or logged.
# No `exit` and no global `set -u`: the entrypoint may source this file.

if [ -z "${GRAFANA_DB_PASSWORD:-}" ]; then
    echo "007_grafana_reader_password.sh: GRAFANA_DB_PASSWORD is empty, password not set" >&2
    false
else
    psql -v ON_ERROR_STOP=1 -q --username "${POSTGRES_USER:-legal}" --dbname "${POSTGRES_DB:-legal}" \
        -v pw="$GRAFANA_DB_PASSWORD" <<'SQL'
ALTER ROLE grafana_reader PASSWORD :'pw';
SQL
    echo "007_grafana_reader_password.sh: grafana_reader password set"
fi
