from contextlib import contextmanager
from decimal import Decimal
from pathlib import Path

import psycopg

from src.quality.checks import CHECKS_PATH, Check, Expectation
from src.quality.evaluate import FAIL, NO_DATA, PASS, QUERY_ERROR, UNCHECKED, CheckResult
from src.quality.run import execute_checks, format_report, parse_args, to_params


def result(check_name, source, value, expected, status, severity="error", error=None):
    return CheckResult(check_name, "completeness", severity, source, value, expected, status, error)


# Message psycopg sur plusieurs lignes : seule la première va dans le rapport.
ERROR = "boom\nLINE 1: SELECT ..."
RESULTS = [
    result("a_check", "judilibre", 0, "== 0", PASS),
    result("b_check", "silver", 7, None, UNCHECKED, severity="warning"),
    result("c_check", None, None, None, QUERY_ERROR, severity="warning", error=ERROR),
    result("d_check", "adlc-opendata", None, "== 0", NO_DATA, severity="warning"),
    result("e_check", "judilibre", Decimal("3"), "== 0", FAIL, severity="warning"),
    result("f_check", "judilibre", Decimal("31"), "<= 30", FAIL),
]


def test_rapport_groupe_par_statut_echecs_d_abord():
    report = format_report(RESULTS).splitlines()
    groups = [line for line in report if not line.startswith("  ")]
    assert groups == [
        "FAIL (2)",
        "NO_DATA (1)",
        "QUERY_ERROR (1)",
        "UNCHECKED (1)",
        "PASS (1)",
        "Verdict : échec (1 résultat(s) bloquant(s) de sévérité error)",
    ]
    # Dans un groupe, la sévérité error passe en premier.
    assert report[1] == "  [error]   f_check / judilibre : 31 (attendu <= 30)"
    assert report[2] == "  [warning] e_check / judilibre : 3 (attendu == 0)"
    assert "  [warning] d_check / adlc-opendata : aucune ligne (attendu == 0)" in report
    assert "  [warning] c_check : boom" in report
    assert "  [warning] b_check / silver : 7 (sans attente)" in report


def test_rapport_omet_les_groupes_vides_et_verdict_succes():
    assert format_report([RESULTS[0]]).splitlines() == [
        "PASS (1)",
        "  [error]   a_check / judilibre : 0 (attendu == 0)",
        "Verdict : succès",
    ]


def test_parametres_d_insertion():
    assert to_params(42, RESULTS[2]) == (
        42,
        "c_check",
        "completeness",
        None,
        None,
        None,
        "warning",
        QUERY_ERROR,
        ERROR,
    )


def test_option_checks():
    assert parse_args([]).checks == CHECKS_PATH
    assert parse_args(["--checks", "tmp/broken.yml"]).checks == Path("tmp/broken.yml")


class FakeCursor:
    def __init__(self, rows):
        self.description = [type("Column", (), {"name": n}) for n in ("source", "value")]
        self.rows = rows

    def fetchall(self):
        return self.rows


class FakeConnection:
    """Simule les transactions psycopg : un savepoint n'est annulé que si l'erreur le traverse."""

    def __init__(self, outcomes):
        self.outcomes = outcomes
        self.read_only = False
        self.aborted = False
        self.events = []

    @contextmanager
    def transaction(self, force_rollback=False):
        self.events.append("begin read only" if self.read_only else "begin")
        try:
            yield
        except psycopg.Error:
            self.aborted = False  # ROLLBACK TO SAVEPOINT
            self.events.append("rollback to savepoint")
            raise

    def execute(self, sql):
        if self.aborted:
            raise psycopg.errors.InFailedSqlTransaction("current transaction is aborted")
        outcome = self.outcomes[sql]
        if isinstance(outcome, Exception):
            self.aborted = True
            raise outcome
        return FakeCursor(outcome)


def make_check(name):
    return Check(name, "completeness", "error", "d", name, {"default": Expectation("==", 0)})


def test_une_requete_en_erreur_n_empeche_pas_les_suivantes():
    conn = FakeConnection(
        {
            "broken": psycopg.errors.UndefinedTable('relation "nope" does not exist'),
            "ok": [("judilibre", 0)],
        }
    )
    results = execute_checks(conn, [make_check("broken"), make_check("ok")])
    assert [(r.check_name, r.status) for r in results] == [("broken", QUERY_ERROR), ("ok", PASS)]
    assert conn.events[:3] == ["begin read only", "begin read only", "rollback to savepoint"]
    assert conn.read_only is False
