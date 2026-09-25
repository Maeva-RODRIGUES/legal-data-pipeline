from datetime import UTC, date, datetime

from src.search.document import FIELDS, load_mapping, to_document

ROW = {
    "source": "judilibre",
    "external_id": "abc",
    "decision_number": None,
    "issuer": None,
    "decision_type": None,
    "decision_date": date(2024, 1, 31),
    "title": None,
    "text": None,
    "sectors": [],
    "url": None,
    "attributes": {},
    "indexed_at": datetime(2026, 9, 25, tzinfo=UTC),
}


def test_mapping_strict():
    assert load_mapping()["mappings"]["dynamic"] == "strict"


def test_mapping_declare_exactement_les_champs_du_document():
    properties = load_mapping()["mappings"]["properties"]
    _, doc = to_document(ROW)
    assert set(properties) == set(doc) == set(FIELDS)
    assert list(properties) == list(FIELDS)
