from decimal import Decimal

import pytest

from src.quality.checks import CheckConfigError, Expectation, load_checks

VALID = """\
- name: empty_text
  dimension: completeness
  severity: warning
  description: >-
    Decisions without full text,
    on several lines.
  sql: |
    SELECT source, 0 AS value FROM silver.decisions GROUP BY source;
  expect:
    default: {op: "==", value: 0}
    adlc-opendata: {op: "<=", value: 30}
"""


def write(tmp_path, content):
    path = tmp_path / "checks.yml"
    path.write_text(content, encoding="utf-8")
    return path


def test_charge_un_controle_valide(tmp_path):
    [check] = load_checks(write(tmp_path, VALID))
    assert check.name == "empty_text"
    assert check.description == "Decisions without full text, on several lines."
    assert check.expect == {
        "default": Expectation("==", Decimal(0)),
        "adlc-opendata": Expectation("<=", Decimal(30)),
    }
    assert check.declared_sources == ["adlc-opendata"]


def test_le_vrai_catalogue_se_charge():
    checks = load_checks()
    assert [c.name for c in checks] == [
        "bronze_rows_missing_from_silver",
        "missing_decision_date",
        "missing_decision_type_pct",
        "empty_text",
        "impossible_decision_date",
        "duplicate_decision_number",
        "number_year_mismatch",
        "hours_since_last_success",
        "site_decisions_missing_from_opendata",
    ]


@pytest.mark.parametrize(
    ("old", "new", "message"),
    [
        (
            "  sql: |\n    SELECT source, 0 AS value FROM silver.decisions GROUP BY source;\n",
            "",
            r"check empty_text: missing or empty 'sql'",
        ),
        (
            '  expect:\n    default: {op: "==", value: 0}\n'
            '    adlc-opendata: {op: "<=", value: 30}\n',
            "  expect: {}\n",
            r"check empty_text: 'expect' must contain at least one entry",
        ),
        (
            'default: {op: "==", value: 0}',
            'default: {op: "!=", value: 0}',
            r"check empty_text: expect\.default: unknown operator '!='",
        ),
        (
            "severity: warning",
            "severity: critical",
            r"check empty_text: unknown severity 'critical'",
        ),
        (
            "dimension: completeness",
            "dimension: accuracy",
            r"check empty_text: unknown dimension 'accuracy'",
        ),
        (
            'default: {op: "==", value: 0}',
            'default: {op: "==", value: "zero"}',
            r"check empty_text: expect\.default: value must be a number",
        ),
        (
            'default: {op: "==", value: 0}',
            'default: {op: "==", value: true}',
            r"check empty_text: expect\.default: value must be a number",
        ),
        (
            'default: {op: "==", value: 0}',
            'default: {op: "=="}',
            r"check empty_text: expect\.default: expected \{op, value\}",
        ),
        (
            "- name: empty_text\n",
            "- name: ''\n",
            r"check #1: missing or empty 'name'",
        ),
    ],
)
def test_rejette_un_controle_invalide_avec_un_message_clair(tmp_path, old, new, message):
    assert old in VALID
    with pytest.raises(CheckConfigError, match=message):
        load_checks(write(tmp_path, VALID.replace(old, new)))


def test_rejette_un_nom_en_double(tmp_path):
    with pytest.raises(CheckConfigError, match="check empty_text: duplicate name"):
        load_checks(write(tmp_path, VALID + VALID))


@pytest.mark.parametrize("content", ["", "name: x\n", "- just a string\n"])
def test_rejette_un_fichier_mal_forme(tmp_path, content):
    with pytest.raises(CheckConfigError):
        load_checks(write(tmp_path, content))
