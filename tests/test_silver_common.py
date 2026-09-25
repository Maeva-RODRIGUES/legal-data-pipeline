from datetime import date

import pytest

from src.silver.common import (
    dedupe,
    parse_iso_date,
    parse_python_list,
    parse_str_list,
    strip_or_none,
)


def test_strip_or_none():
    assert strip_or_none("  C2007/14 ") == "C2007/14"
    assert strip_or_none("   ") is None
    assert strip_or_none(None) is None
    assert strip_or_none(12) is None


@pytest.mark.parametrize(
    "value, expected",
    [
        ("2026-08-04", date(2026, 8, 4)),
        ("2026-08-04T00:00:00", date(2026, 8, 4)),
        ("04 août 2026", None),
        ("2026-02-30", None),
        ("", None),
        (None, None),
    ],
)
def test_parse_iso_date(value, expected):
    assert parse_iso_date(value) == expected


@pytest.mark.parametrize(
    "value, expected",
    [
        ("['BTP']", ["BTP"]),
        ("[' Énergie ', 'Transport']", ["Énergie", "Transport"]),
        ("[]", []),
        ("['BTP', '', '  ']", ["BTP"]),
    ],
)
def test_parse_python_list(value, expected):
    assert parse_python_list(value) == expected


@pytest.mark.parametrize("value", ["['BTP'", "BTP", "[1, 2]", "{'a': 1}", None, ["BTP"]])
def test_parse_python_list_mal_formee(value):
    assert parse_python_list(value) is None


@pytest.mark.parametrize(
    "value, expected",
    [
        ([" BTP ", "", "Énergie"], ["BTP", "Énergie"]),
        ([], []),
        ("['BTP']", ["BTP"]),
        (["BTP", 1], None),
        (12, None),
        (None, None),
    ],
)
def test_parse_str_list(value, expected):
    assert parse_str_list(value) == expected


def test_dedupe_garde_l_ordre():
    assert dedupe(["b", "a", "b", "c", "a"]) == ["b", "a", "c"]
