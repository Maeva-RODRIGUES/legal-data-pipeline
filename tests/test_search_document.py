from datetime import UTC, date, datetime

import pytest

from src.search.document import FIELDS, has_text, to_document

INDEXED_AT = datetime(2026, 9, 25, 14, 30, tzinfo=UTC)


def silver_row(**overrides):
    row = {
        "source": "adlc-opendata",
        "external_id": "https://www.autoritedelaconcurrence.fr/fr/decision/09-d-36",
        "decision_number": "09-D-36",
        "issuer": "Autorité de la concurrence",
        "decision_type": "decision",
        "decision_date": date(2009, 12, 9),
        "title": "Décision 09-D-36",
        "text": "L'Autorité de la concurrence...",
        "sectors": ["Énergie", "Transport"],
        "url": "https://www.autoritedelaconcurrence.fr/fr/decision/09-d-36",
        "attributes": {"procedure": "contentieux"},
        "built_at": datetime(2026, 9, 24, 9, 0, tzinfo=UTC),
        "indexed_at": INDEXED_AT,
    }
    return row | overrides


def test_identifiant_source_et_external_id():
    doc_id, _ = to_document(silver_row())
    assert doc_id == "adlc-opendata|https://www.autoritedelaconcurrence.fr/fr/decision/09-d-36"
    doc_id, _ = to_document(silver_row(source="judilibre", external_id="abc:12/3"))
    assert doc_id == "judilibre|abc:12/3"


@pytest.mark.parametrize(
    "text, expected",
    [("Texte", True), (" x ", True), ("", False), ("   \n\t", False), (None, False)],
)
def test_has_text(text, expected):
    assert has_text(text) is expected
    assert to_document(silver_row(text=text))[1]["has_text"] is expected


def test_document_complet_et_serialise():
    _, doc = to_document(silver_row())
    assert list(doc) == list(FIELDS)
    assert doc["decision_date"] == "2009-12-09"
    assert doc["indexed_at"] == "2026-09-25T14:30:00+00:00"
    assert doc["sectors"] == ["Énergie", "Transport"]
    assert doc["attributes"] == {"procedure": "contentieux"}
    assert doc["text"] == "L'Autorité de la concurrence..."
    assert "built_at" not in doc


def test_null_conserves_jamais_devines():
    nullable = ("decision_number", "issuer", "decision_type", "decision_date", "title", "text")
    _, doc = to_document(silver_row(url=None, **dict.fromkeys(nullable)))
    assert list(doc) == list(FIELDS)
    for field in (*nullable, "url"):
        assert doc[field] is None
    assert doc["has_text"] is False


def test_texte_vide_reste_vide():
    _, doc = to_document(silver_row(text=""))
    assert doc["text"] == ""
    assert doc["has_text"] is False
