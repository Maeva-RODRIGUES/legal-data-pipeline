from datetime import date

import pytest

from src.api.display import display_title, french_date

JUDILIBRE_ID = "6a6c3834d6da041962933bac"


def test_titre_de_la_source_garde_tel_quel():
    title = "concernant l’effacement de consommation dans le secteur de l’électricité"
    assert (
        display_title(title, "Autorité de la concurrence", date(2012, 7, 26), "12-A-19", "x")
        == title
    )


def test_citation_judilibre():
    assert (
        display_title(None, "Cour de cassation", date(2026, 7, 29), "26-83.146", JUDILIBRE_ID)
        == "Cour de cassation, 29 juillet 2026, n° 26-83.146"
    )


def test_titre_vide_remplace_par_la_citation():
    assert (
        display_title("  ", "Cour de cassation", date(2026, 7, 29), "26-83.146", JUDILIBRE_ID)
        == "Cour de cassation, 29 juillet 2026, n° 26-83.146"
    )


def test_premier_du_mois():
    assert (
        display_title(None, "Cour de cassation", date(2026, 10, 1), "26-12.345", JUDILIBRE_ID)
        == "Cour de cassation, 1er octobre 2026, n° 26-12.345"
    )


@pytest.mark.parametrize(
    ("issuer", "decision_date", "number", "expected"),
    [
        ("Cour de cassation", None, "26-83.146", "Cour de cassation, n° 26-83.146"),
        (None, date(2026, 7, 29), "26-83.146", "29 juillet 2026, n° 26-83.146"),
        ("Cour de cassation", date(2026, 7, 29), None, "Cour de cassation, 29 juillet 2026"),
        (None, None, None, f"Décision {JUDILIBRE_ID}"),
    ],
)
def test_segments_manquants_omis(issuer, decision_date, number, expected):
    assert display_title(None, issuer, decision_date, number, JUDILIBRE_ID) == expected


def test_mois_en_francais_avec_accents():
    assert french_date(date(2026, 2, 3)) == "3 février 2026"
    assert french_date(date(2026, 8, 15)) == "15 août 2026"
    assert french_date(date(2026, 12, 31)) == "31 décembre 2026"
