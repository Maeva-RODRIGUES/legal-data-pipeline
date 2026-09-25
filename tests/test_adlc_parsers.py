from pathlib import Path

import pytest

from src.collector.adlc_scraper.parsers import ParseError, parse_listing

FIXTURE = Path(__file__).parent / "fixtures" / "adlc_listing.html"


@pytest.fixture(scope="module")
def items():
    return parse_listing(FIXTURE.read_text(encoding="utf-8"))


def by_id(items, id_decision):
    return next(i for i in items if i.id_decision == id_decision)


def test_extrait_les_20_decisions_de_la_page(items):
    assert len(items) == 20


def test_extrait_les_champs_d_une_decision(items):
    avis = by_id(items, "26-A-05")
    assert avis.url == (
        "https://www.autoritedelaconcurrence.fr/fr/avis/"
        "relatif-au-fonctionnement-concurrentiel-du-secteur-des-agents-dintelligence-artificielle"
    )
    assert avis.title.startswith("relatif au fonctionnement concurrentiel")
    assert avis.decision_type == "Avis"
    assert str(avis.decision_date) == "2026-07-17"
    assert avis.sectors == ["Numérique"]


def test_gere_les_deux_structures_de_secteurs(items):
    assert by_id(items, "26-D-05").sectors == ["Distribution", "Grande consommation"]


def test_titre_identique_mais_decisions_distinctes(items):
    d06, d07 = by_id(items, "26-D-06"), by_id(items, "26-D-07")
    assert d06.title == d07.title
    assert d06.url != d07.url
    assert d07.url.endswith("-0")


def test_aucune_url_de_detail_avec_parametres(items):
    assert all("?" not in i.url for i in items)


def test_echoue_si_la_structure_a_change():
    with pytest.raises(ParseError):
        parse_listing("<html><body><p>Site en maintenance</p></body></html>")
