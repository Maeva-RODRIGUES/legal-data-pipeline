from datetime import date

import pytest

from src.silver.judilibre import SOURCE, transform


def make_payload(**overrides):
    payload = {
        "id": "abc123",
        "jurisdiction": "cc",
        "number": "19-24.00820-15.12319-24.008",
        "numbers": ["19-24.008", "20-15.123", "19-24.008"],
        "decision_date": "2026-09-15",
        "update_date": "2026-09-16",
        "type": "other",
        "text": "La Cour...",
        "summary": "",
        "ecli": "ECLI:FR:CCASS:2026:C100001",
        "chamber": "civ1",
        "formation": "f",
        "solution": "rejet",
        "publication": ["b"],
        "themes": ["contrat"],
    }
    payload.update(overrides)
    return payload


def test_decision_complete_sans_anomalie():
    row, anomalies = transform("abc123", make_payload())
    assert anomalies == []
    assert row.source == SOURCE
    assert row.external_id == "abc123"
    assert row.issuer == "Cour de cassation"
    assert row.decision_date == date(2026, 9, 15)
    assert row.text == "La Cour..."
    assert row.title is None
    assert row.sectors == []
    assert row.url == "https://www.courdecassation.fr/decision/abc123"


def test_number_corrompu_ignore_et_numbers_dedoublonne():
    row, _ = transform("abc123", make_payload())
    assert row.decision_number == "19-24.008"
    assert row.attributes["numbers"] == ["19-24.008", "20-15.123"]
    assert "number" not in row.attributes


@pytest.mark.parametrize("numbers", [["19-24.00820"], [], None])
def test_numero_invalide_donne_null(numbers):
    row, anomalies = transform("abc123", make_payload(numbers=numbers))
    assert row.decision_number is None
    assert anomalies == ["invalid_decision_number"]


@pytest.mark.parametrize(
    "code, issuer",
    [("cc", "Cour de cassation"), ("ca", "Cour d'appel"), ("tj", "Tribunal judiciaire")],
)
def test_juridictions_connues(code, issuer):
    row, anomalies = transform("abc123", make_payload(jurisdiction=code))
    assert row.issuer == issuer
    assert anomalies == []


def test_juridiction_inconnue_donne_null():
    row, anomalies = transform("abc123", make_payload(jurisdiction="ta"))
    assert row.issuer is None
    assert anomalies == ["unknown_jurisdiction"]


def test_date_invalide_donne_null():
    row, anomalies = transform("abc123", make_payload(decision_date="15/09/2026"))
    assert row.decision_date is None
    assert anomalies == ["invalid_decision_date"]


def test_type_other_garde_dans_les_attributs():
    row, _ = transform("abc123", make_payload())
    assert row.decision_type is None
    assert row.attributes["judilibre_type"] == "other"


def test_summary_vide_omis_et_non_vide_garde():
    row, _ = transform("abc123", make_payload(summary="  "))
    assert "summary" not in row.attributes
    row, _ = transform("abc123", make_payload(summary="Résumé"))
    assert row.attributes["summary"] == "Résumé"


def test_attributs_attendus():
    row, _ = transform("abc123", make_payload())
    assert set(row.attributes) == {
        "ecli",
        "numbers",
        "chamber",
        "formation",
        "solution",
        "publication",
        "themes",
        "update_date",
        "judilibre_type",
    }


def test_ligne_sans_identifiant_sautee():
    row, anomalies = transform("  ", make_payload())
    assert row is None
    assert anomalies == ["missing_external_id"]
