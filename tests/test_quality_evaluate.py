from decimal import Decimal

import psycopg
import pytest

from src.quality.checks import Check, Expectation
from src.quality.evaluate import (
    FAIL,
    NO_DATA,
    PASS,
    QUERY_ERROR,
    UNCHECKED,
    CheckResult,
    QueryResultError,
    evaluate,
    run_check,
    run_failed,
    validate_rows,
)

COLUMNS = ["source", "value"]


def make_check(expect, severity="error"):
    return Check(
        name="c",
        dimension="completeness",
        severity=severity,
        description="d",
        sql="SELECT 1",
        expect={source: Expectation(op, Decimal(value)) for source, (op, value) in expect.items()},
    )


def statuses(results):
    return {r.source: r.status for r in results}


@pytest.mark.parametrize(
    ("op", "bound", "value", "holds"),
    [
        ("==", 0, 0, True),
        ("==", 0, 1, False),
        ("<=", 30, 30, True),
        ("<=", 30, 31, False),
        (">=", 5, 5, True),
        (">=", 5, 4, False),
        ("<", 5, 4, True),
        ("<", 5, 5, False),
        (">", 5, 6, True),
        (">", 5, 5, False),
    ],
)
def test_operateurs_et_bornes(op, bound, value, holds):
    assert Expectation(op, Decimal(bound)).holds(value) is holds


def test_comparaison_decimal_et_entier():
    assert Expectation("==", Decimal(100)).holds(Decimal("100.00"))
    assert not Expectation("==", Decimal(100)).holds(Decimal("99.99"))


def test_texte_de_l_attente():
    assert str(Expectation("==", Decimal(0))) == "== 0"
    assert str(Expectation("<=", Decimal(30))) == "<= 30"


def test_l_attente_propre_a_la_source_l_emporte_sur_default():
    check = make_check({"default": ("==", 0), "judilibre": ("==", 100)})
    results = evaluate(check, {"judilibre": Decimal("100.00"), "adlc-opendata": Decimal("0.00")})
    assert statuses(results) == {"adlc-opendata": PASS, "judilibre": PASS}
    assert {r.source: r.expected for r in results} == {
        "adlc-opendata": "== 0",
        "judilibre": "== 100",
    }
    assert statuses(evaluate(check, {"adlc-opendata": 100})) == {
        "adlc-opendata": FAIL,
        "judilibre": NO_DATA,
    }


def test_sans_default_source_declaree_absente_et_source_non_declaree():
    check = make_check({"judilibre": ("==", 0), "adlc-opendata": ("==", 0)})
    results = evaluate(check, {"judilibre": 0, "silver": 7})
    by_source = {r.source: r for r in results}
    assert statuses(results) == {"judilibre": PASS, "silver": UNCHECKED, "adlc-opendata": NO_DATA}
    assert by_source["silver"].expected is None
    assert by_source["silver"].value == 7
    assert by_source["adlc-opendata"].value is None
    assert by_source["adlc-opendata"].expected == "== 0"


@pytest.mark.parametrize(
    ("columns", "rows", "message"),
    [
        (["source", "n"], [("a", 1)], r"expected columns \(source, value\)"),
        (["source", "value", "x"], [("a", 1, 2)], r"expected columns"),
        (COLUMNS, [("", 1)], "invalid source"),
        (COLUMNS, [(None, 1)], "invalid source"),
        (COLUMNS, [("a", None)], "source a: non-numeric value None"),
        (COLUMNS, [("a", "1")], "non-numeric value"),
        (COLUMNS, [("a", 1), ("a", 2)], "source a: returned more than once"),
    ],
)
def test_resultat_mal_forme(columns, rows, message):
    with pytest.raises(QueryResultError, match=message):
        validate_rows(columns, rows)


def test_resultat_valide():
    assert validate_rows(COLUMNS, [("a", 1), ("b", Decimal("2.5")), ("c", 0.5)]) == {
        "a": 1,
        "b": Decimal("2.5"),
        "c": Decimal("0.5"),
    }


def test_run_check_query_error_sur_erreur_de_la_base():
    def fetch(sql):
        raise psycopg.errors.UndefinedTable('relation "silver.nope" does not exist')

    [result] = run_check(make_check({"default": ("==", 0)}), fetch)
    assert result.status == QUERY_ERROR
    assert result.source is None and result.value is None and result.expected is None
    assert result.error == 'relation "silver.nope" does not exist'


def test_run_check_query_error_sur_resultat_mal_forme():
    [result] = run_check(make_check({"default": ("==", 0)}), lambda sql: (["n"], [(1,)]))
    assert result.status == QUERY_ERROR
    assert "expected columns" in result.error


def test_run_check_propage_les_autres_exceptions():
    def fetch(sql):
        raise KeyError("bug")

    with pytest.raises(KeyError):
        run_check(make_check({"default": ("==", 0)}), fetch)


def test_run_check_evalue_les_lignes():
    results = run_check(make_check({"default": ("==", 0)}), lambda sql: (COLUMNS, [("a", 0)]))
    assert statuses(results) == {"a": PASS}


def one(severity, status):
    return CheckResult("c", "completeness", severity, "a", None, None, status)


@pytest.mark.parametrize("status", [FAIL, NO_DATA, QUERY_ERROR])
def test_echec_du_run_seulement_pour_la_severite_error(status):
    assert run_failed([one("warning", PASS), one("error", status)])
    assert not run_failed([one("warning", status)])


@pytest.mark.parametrize("status", [PASS, UNCHECKED])
def test_pas_d_echec_sans_resultat_bloquant(status):
    assert not run_failed([one("error", status), one("warning", FAIL)])
