import json
from datetime import date
from pathlib import Path

import pytest

from src.silver.adlc_opendata import ISSUER, SOURCE, transform

URL = "https://www.autoritedelaconcurrence.fr/fr/avis/a"
FIXTURE = Path(__file__).parent / "fixtures" / "adlc_opendata_decisions.json"


def make_payload(**overrides):
    payload = {
        "id_decision": "26-A-05",
        "type_decision": "Avis",
        "date_decision": "04 août 2026",
        "date_decision_datetime": "2026-08-04",
        "titre_decision": " Avis relatif au secteur du BTP ",
        "texte_complet_decision": "L'Autorité...",
        "secteur_activite": ["BTP"],
        "entreprises_concernees": ["Société A", "Société B"],
        "url_site": URL,
        "date_decision_year": 2026,
    }
    payload.update(overrides)
    return payload


def test_decision_complete_sans_anomalie():
    row, anomalies = transform(URL, make_payload())
    assert anomalies == []
    assert row.source == SOURCE
    assert row.external_id == URL
    assert row.decision_number == "26-A-05"
    assert row.issuer == ISSUER
    assert row.decision_type == "avis"
    assert row.decision_date == date(2026, 8, 4)
    assert row.title == "Avis relatif au secteur du BTP"
    assert row.text == "L'Autorité..."
    assert row.sectors == ["BTP"]
    assert row.url == URL


@pytest.mark.parametrize(
    "raw, decision_type, subtypes",
    [
        ("DCC", "concentration", []),
        ("Décision", "decision", []),
        ("Avis", "avis", []),
        (["Décision", "MC"], "decision", ["MC"]),
        (["DCC", "DEX"], "concentration", ["DEX"]),
        (["Avis", "SOA"], "avis", ["SOA"]),
        ("Lettre du minsitre de l'économie", "lettre_ministre", []),
    ],
)
def test_sept_valeurs_connues_de_type_decision(raw, decision_type, subtypes):
    row, anomalies = transform(URL, make_payload(type_decision=raw))
    assert row.decision_type == decision_type
    assert row.attributes["subtypes"] == subtypes
    assert anomalies == []


@pytest.mark.parametrize(
    "raw",
    ["Lettre du ministre de l'économie", "Arrêt", ["Arrêt", "MC"], "", None, 12],
)
def test_type_inconnu_donne_null(raw):
    row, anomalies = transform(URL, make_payload(type_decision=raw))
    assert row.decision_type is None
    assert anomalies == ["unknown_decision_type"]


def test_type_liste_en_texte_lue_en_secours():
    row, anomalies = transform(URL, make_payload(type_decision='["Avis", "SOA"]'))
    assert row.decision_type == "avis"
    assert row.attributes["subtypes"] == ["SOA"]
    assert anomalies == []


@pytest.mark.parametrize("raw", ['["Avis", "SOA"', "[]", "[1, 2]", [], [1, 2]])
def test_type_json_mal_forme(raw):
    row, anomalies = transform(URL, make_payload(type_decision=raw))
    assert row.decision_type is None
    assert row.attributes["subtypes"] == []
    assert anomalies == ["malformed_type_decision"]


@pytest.mark.parametrize(
    "raw, sectors",
    [
        ([" BTP ", "Énergie"], ["BTP", "Énergie"]),
        ([], []),
        (["BTP", ""], ["BTP"]),
        ("['BTP']", ["BTP"]),  # secours : liste encodée en texte
    ],
)
def test_secteurs(raw, sectors):
    row, anomalies = transform(URL, make_payload(secteur_activite=raw))
    assert row.sectors == sectors
    assert anomalies == []


@pytest.mark.parametrize("raw", ["['BTP'", 12, {"BTP": 1}, ["BTP", 1]])
def test_secteurs_mal_formes_donnent_liste_vide(raw):
    row, anomalies = transform(URL, make_payload(secteur_activite=raw))
    assert row.sectors == []
    assert anomalies == ["malformed_sectors"]


def test_entreprises_converties_en_liste():
    row, _ = transform(URL, make_payload(entreprises_concernees=[" Société A", ""]))
    assert row.attributes["entreprises_concernees"] == ["Société A"]


def test_entreprises_en_texte_lues_en_secours():
    row, anomalies = transform(URL, make_payload(entreprises_concernees="['Société A']"))
    assert row.attributes["entreprises_concernees"] == ["Société A"]
    assert anomalies == []


@pytest.mark.parametrize("raw", ["Société A", 12, ["Société A", None]])
def test_entreprises_mal_formees(raw):
    row, anomalies = transform(URL, make_payload(entreprises_concernees=raw))
    assert row.attributes["entreprises_concernees"] == []
    assert anomalies == ["malformed_entreprises"]


@pytest.mark.parametrize("raw, expected", [("Oui", True), ("Non", False)])
def test_decision_simplifiee(raw, expected):
    row, anomalies = transform(URL, make_payload(type_decision="DCC", decision_simplifiee=raw))
    assert row.attributes["decision_simplifiee"] is expected
    assert anomalies == []


def test_decision_simplifiee_absente_sans_anomalie():
    row, anomalies = transform(URL, make_payload())
    assert "decision_simplifiee" not in row.attributes
    assert anomalies == []


def test_decision_simplifiee_invalide():
    row, anomalies = transform(URL, make_payload(decision_simplifiee="Peut-être"))
    assert row.attributes["decision_simplifiee"] is None
    assert anomalies == ["invalid_decision_simplifiee"]


def test_espaces_retires_de_id_decision():
    row, _ = transform(URL, make_payload(id_decision="C2007/14 "))
    assert row.decision_number == "C2007/14"


def test_date_invalide_donne_null():
    row, anomalies = transform(URL, make_payload(date_decision_datetime="04 août 2026"))
    assert row.decision_date is None
    assert anomalies == ["invalid_decision_date"]


def test_attributs_hors_colonnes_et_nettoyes():
    row, _ = transform(URL, make_payload(date_decision=" 04 août 2026 "))
    assert row.attributes == {
        "date_decision": "04 août 2026",
        "entreprises_concernees": ["Société A", "Société B"],
        "date_decision_year": 2026,
        "subtypes": [],
    }


def test_ligne_sans_identifiant_sautee():
    row, anomalies = transform("", make_payload())
    assert row is None
    assert anomalies == ["missing_external_id"]


@pytest.fixture(scope="module")
def real_rows():
    """Trois décisions réelles extraites du Bronze : avis, concentration, décision MC."""
    records = json.loads(FIXTURE.read_text(encoding="utf-8"))
    return {r["payload"]["id_decision"]: transform(r["external_id"], r["payload"]) for r in records}


def test_decisions_reelles_sans_anomalie(real_rows):
    assert {id_: anomalies for id_, (_, anomalies) in real_rows.items()} == {
        "02-A-06": [],
        "24-DCC-101": [],
        "01-MC-05": [],
    }


def test_avis_reel(real_rows):
    row, _ = real_rows["02-A-06"]
    assert row.decision_type == "avis"
    assert row.attributes["subtypes"] == []
    assert row.decision_date == date(2002, 5, 4)
    assert row.sectors == ["Energie / Environnement"]
    assert row.attributes["entreprises_concernees"] == ["Opérateurs du secteur électrique"]
    assert "decision_simplifiee" not in row.attributes


def test_decision_mc_reelle(real_rows):
    row, _ = real_rows["01-MC-05"]
    assert row.decision_type == "decision"
    assert row.attributes["subtypes"] == ["MC"]
    assert row.decision_date == date(2001, 8, 27)
    assert row.sectors == ["Agriculture / Agro-alimentaire", "Grande consommation"]


def test_concentration_reelle(real_rows):
    row, _ = real_rows["24-DCC-101"]
    assert row.decision_type == "concentration"
    assert row.decision_date == date(2024, 5, 24)
    assert row.sectors == ["Transports"]
    assert row.attributes["entreprises_concernees"] == ["groupe Transarc", "Infranity"]
    assert row.attributes["decision_simplifiee"] is True
