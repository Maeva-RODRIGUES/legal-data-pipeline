import json
import re
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).parent.parent
DASHBOARDS = sorted((ROOT / "grafana" / "dashboards").glob("*.json"))
DATASOURCES = ROOT / "grafana" / "provisioning" / "datasources" / "postgres.yml"

EXPECTED_UIDS = {"pipeline-health", "collection", "quality", "search"}
WRITE_KEYWORDS = (
    "INSERT", "UPDATE", "DELETE", "MERGE", "UPSERT", "TRUNCATE", "DROP", "ALTER", "CREATE",
    "GRANT", "REVOKE", "COPY", "CALL", "DO", "SET", "RESET", "LOCK", "VACUUM", "REFRESH",
    "COMMENT", "EXECUTE", "PREPARE", "BEGIN", "COMMIT", "ROLLBACK",
)  # fmt: skip


def load_json(path: Path) -> dict:
    with path.open(encoding="utf-8") as f:
        return json.load(f)


def provisioned_datasource() -> dict:
    with DATASOURCES.open(encoding="utf-8") as f:
        (source,) = yaml.safe_load(f)["datasources"]
    return {"type": source["type"], "uid": source["uid"]}


def all_panels(panels: list[dict]):
    """Panneaux, y compris ceux d'une ligne repliée."""
    for panel in panels:
        yield panel
        yield from all_panels(panel.get("panels", []))


def queries(dashboard: dict) -> list[str]:
    found = [t["rawSql"] for p in all_panels(dashboard["panels"]) for t in p.get("targets", [])]
    found += [
        v["query"] if isinstance(v["query"], str) else v["query"]["rawSql"]
        for v in dashboard.get("templating", {}).get("list", [])
        if v.get("type") == "query"
    ]
    return found


def read_only_violation(sql: str) -> str | None:
    """Motif du refus d'une requête, None si elle est en lecture seule."""
    code = re.sub(r"--[^\n]*|/\*.*?\*/", " ", sql, flags=re.S)
    code = re.sub(r"'(?:[^']|'')*'", "''", code)  # un mot-clé dans une chaîne ne compte pas
    code = code.strip().rstrip(";").strip()
    if not re.match(r"(?i)(SELECT|WITH)\b", code):
        return "does not start with SELECT or WITH"
    if ";" in code:
        return "contains several statements"
    for word in WRITE_KEYWORDS:
        if re.search(rf"(?i)\b{word}\b", code):
            return f"contains {word}"
    return None


@pytest.fixture(params=DASHBOARDS, ids=lambda p: p.name)
def dashboard(request) -> dict:
    return load_json(request.param)


def test_expected_dashboards_are_present():
    uids = [load_json(path)["uid"] for path in DASHBOARDS]
    assert len(uids) == len(set(uids))
    assert set(uids) == EXPECTED_UIDS


def test_dashboard_has_title_and_no_fixed_id(dashboard):
    assert dashboard["title"]
    assert dashboard["id"] is None


def test_dashboard_time_zone_is_paris(dashboard):
    assert dashboard["timezone"] == "Europe/Paris"


def test_every_panel_and_query_uses_provisioned_datasource(dashboard):
    expected = provisioned_datasource()
    for panel in all_panels(dashboard["panels"]):
        if panel["type"] in ("row", "text"):
            continue
        assert panel["datasource"] == expected, panel["title"]
        assert panel.get("targets"), f"{panel['title']}: data panel without query"
        for t in panel["targets"]:
            assert t["datasource"] == expected, panel["title"]
    for var in dashboard.get("templating", {}).get("list", []):
        if var.get("type") == "query":
            assert var["datasource"] == expected, var["name"]


def test_no_import_placeholder(dashboard):
    assert "${DS_" not in json.dumps(dashboard)


def test_every_query_is_read_only(dashboard):
    found = queries(dashboard)
    assert found
    for sql in found:
        assert read_only_violation(sql) is None, sql


@pytest.mark.parametrize(
    "sql",
    [
        "SELECT 1",
        "select status from bronze.collection_runs;",
        "WITH r AS (SELECT 1) SELECT * FROM r",
        "SELECT updated_at, created_at FROM t WHERE $__timeFilter(created_at)",
        "SELECT 'delete; drop' AS label -- UPDATE in a comment",
    ],
)
def test_read_only_check_accepts(sql):
    assert read_only_violation(sql) is None


@pytest.mark.parametrize(
    "sql",
    [
        "INSERT INTO bronze.collection_runs (source) VALUES ('x')",
        "SELECT 1; DELETE FROM quality.check_results",
        "WITH d AS (DELETE FROM search.index_stats RETURNING *) SELECT * FROM d",
        "SELECT set_config('x', 'y', false); SET ROLE legal",
        "UPDATE quality.check_results SET value = 0",
        "/* SELECT */ DROP TABLE bronze.collection_runs",
    ],
)
def test_read_only_check_refuses(sql):
    assert read_only_violation(sql) is not None
