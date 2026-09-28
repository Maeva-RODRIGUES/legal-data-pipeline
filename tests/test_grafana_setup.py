import re
from pathlib import Path

ROOT = Path(__file__).parent.parent
MIGRATION = ROOT / "sql" / "007_grafana_reader.sql"
PASSWORD_SCRIPT = ROOT / "sql" / "007_grafana_reader_password.sh"
ENV_EXAMPLE = ROOT / ".env.example"

DASHBOARD_TABLES = {
    "bronze.collection_runs",
    "quality.check_results",
    "search.index_stats",
    "search.findability_runs",
    "search.findability_results",
}


def read(path: Path) -> str:
    with path.open(encoding="utf-8") as f:
        return f.read()


def sql_without_comments(path: Path) -> str:
    return re.sub(r"--[^\n]*", "", read(path))


def grants(sql: str) -> list[tuple[str, str]]:
    """(privilèges, objets) de chaque GRANT ... ON ... TO."""
    return [
        (m.group(1).strip().upper(), m.group(2))
        for m in re.finditer(r"GRANT\s+(.+?)\s+ON\s+(.+?)\s+TO\s+grafana_reader", sql, re.I | re.S)
    ]


def test_migration_has_no_password():
    assert "password" not in sql_without_comments(MIGRATION).lower()


def test_migration_grants_select_on_dashboard_tables_only():
    select = [
        objects
        for privileges, objects in grants(sql_without_comments(MIGRATION))
        if privileges == "SELECT"
    ]
    assert len(select) == 1
    tables = {t.strip() for t in select[0].split(",")}
    assert tables == DASHBOARD_TABLES


def test_migration_grants_schema_usage_and_nothing_else():
    found = grants(sql_without_comments(MIGRATION))
    assert {privileges for privileges, _ in found} == {"SELECT", "USAGE"}
    usage = next(objects for privileges, objects in found if privileges == "USAGE")
    schemas = {s.strip() for s in re.sub(r"(?i)^schema\s+", "", usage).split(",")}
    assert schemas == {t.split(".")[0] for t in DASHBOARD_TABLES}


def test_migration_makes_role_read_only():
    assert re.search(r"SET\s+default_transaction_read_only\s*=\s*on", read(MIGRATION), re.I)


def test_password_script_reads_env_and_uses_psql_variable():
    script = read(PASSWORD_SCRIPT)
    assert '-v pw="$GRAFANA_DB_PASSWORD"' in script
    assert "PASSWORD :'pw'" in script
    # Sourcé par l'entrypoint : un exit arrêterait l'initialisation de la base.
    assert not re.search(r"^\s*exit\b", script, re.M)


def test_password_script_has_lf_line_endings():
    with PASSWORD_SCRIPT.open("rb") as f:
        assert b"\r\n" not in f.read()


def test_env_example_declares_grafana_password_without_value():
    lines = read(ENV_EXAMPLE).splitlines()
    assert "GRAFANA_DB_PASSWORD=" in lines
