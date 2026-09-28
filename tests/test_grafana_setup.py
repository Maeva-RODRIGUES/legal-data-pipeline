import re
from pathlib import Path

import yaml

ROOT = Path(__file__).parent.parent
MIGRATION = ROOT / "sql" / "007_grafana_reader.sql"
PASSWORD_SCRIPT = ROOT / "sql" / "008_grafana_reader_password.sh"
ENV_EXAMPLE = ROOT / ".env.example"
COMPOSE = ROOT / "docker-compose.yml"
DATASOURCES = ROOT / "grafana" / "provisioning" / "datasources" / "postgres.yml"
DASHBOARD_PROVIDERS = ROOT / "grafana" / "provisioning" / "dashboards" / "dashboards.yml"

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


def load_yaml(path: Path):
    with path.open(encoding="utf-8") as f:
        return yaml.safe_load(f)


def grafana_service() -> dict:
    return load_yaml(COMPOSE)["services"]["grafana"]


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


def test_password_script_runs_after_role_migration():
    # L'entrypoint de postgres n'ordonne pas « 007_x.sql » avant « 007_x_y.sh » :
    # constaté sur un volume neuf. Un préfixe numérique plus grand le garantit.
    assert PASSWORD_SCRIPT.name.split("_")[0] > MIGRATION.name.split("_")[0]


def test_password_script_keeps_password_out_of_server_logs():
    script = read(PASSWORD_SCRIPT)
    set_logging = script.index("SET log_min_error_statement = panic;")
    assert set_logging < script.index("ALTER ROLE grafana_reader PASSWORD")
    assert "rolname = 'grafana_reader'" in script  # rôle vérifié avant l'ALTER ROLE


def test_password_script_fails_on_error():
    script = read(PASSWORD_SCRIPT)
    assert "ON_ERROR_STOP=1" in script
    assert script.count("false") == 3  # variable vide, rôle absent, échec de psql


def test_password_script_has_lf_line_endings():
    with PASSWORD_SCRIPT.open("rb") as f:
        assert b"\r\n" not in f.read()


def test_env_example_declares_grafana_password_without_value():
    lines = read(ENV_EXAMPLE).splitlines()
    assert "GRAFANA_DB_PASSWORD=" in lines
    assert "GRAFANA_ADMIN_PASSWORD=" in lines


def test_postgres_service_receives_grafana_password_from_env():
    env = load_yaml(COMPOSE)["services"]["postgres"]["environment"]
    assert env["GRAFANA_DB_PASSWORD"].startswith("${GRAFANA_DB_PASSWORD:?")


def test_grafana_image_is_official_and_pinned():
    image = grafana_service()["image"]
    name, tag = image.rsplit(":", 1)
    assert name.removeprefix("docker.io/") == "grafana/grafana"
    assert re.fullmatch(r"\d+\.\d+\.\d+", tag), f"pin an exact version, not {tag!r}"


def test_grafana_port_bound_to_localhost_only():
    assert grafana_service()["ports"] == ["127.0.0.1:3000:3000"]


def test_grafana_data_in_named_volume():
    compose = load_yaml(COMPOSE)
    volume = grafana_service()["volumes"][0].split(":")[0]
    assert grafana_service()["volumes"][0] == f"{volume}:/var/lib/grafana"
    assert volume in compose["volumes"]


def test_grafana_secrets_come_from_env():
    env = grafana_service()["environment"]
    assert env["GF_SECURITY_ADMIN_PASSWORD"].startswith("${GRAFANA_ADMIN_PASSWORD:?")
    assert env["GRAFANA_DB_PASSWORD"].startswith("${GRAFANA_DB_PASSWORD:?")


def test_grafana_no_anonymous_access_and_paris_time_zone():
    env = grafana_service()["environment"]
    assert env["GF_AUTH_ANONYMOUS_ENABLED"] == "false"
    assert env["GF_USERS_ALLOW_SIGN_UP"] == "false"
    assert env["GF_DATE_FORMATS_DEFAULT_TIMEZONE"] == "Europe/Paris"


def test_datasource_uses_read_only_role_and_env_password():
    (source,) = load_yaml(DATASOURCES)["datasources"]
    assert source["type"] == "grafana-postgresql-datasource"
    assert source["user"] == "grafana_reader"
    assert source["secureJsonData"]["password"] == "${GRAFANA_DB_PASSWORD}"
    assert source["editable"] is False


def test_dashboard_provider_reads_mounted_folder_and_blocks_ui_saves():
    (provider,) = load_yaml(DASHBOARD_PROVIDERS)["providers"]
    assert provider["allowUiUpdates"] is False
    mounts = dict(v.rsplit(":", 2)[:2] for v in grafana_service()["volumes"] if v.startswith("./"))
    assert mounts["./grafana/dashboards"] == provider["options"]["path"]
    assert mounts["./grafana/provisioning"] == "/etc/grafana/provisioning"
