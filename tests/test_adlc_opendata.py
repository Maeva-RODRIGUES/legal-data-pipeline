import io
import json

from src.collector.adlc_opendata import external_id, iter_decisions

SAMPLE = [
    {
        "id_decision": "17-A-05",
        "url_site": "https://example.fr/fr/avis/a",
        "date_decision": "04 août 2026",
        "montant": 1.5,
    },
    {"id_decision": "17-A-05", "url_site": "https://example.fr/fr/avis/a-0"},
    {"id_decision": "C2007/14 ", "url_site": "   "},
]


def test_iter_decisions_lit_toutes_les_decisions_en_flux():
    f = io.BytesIO(json.dumps(SAMPLE, ensure_ascii=False).encode("utf-8"))
    items = list(iter_decisions(f))
    assert len(items) == 3
    assert items[0]["date_decision"] == "04 août 2026"
    assert isinstance(items[0]["montant"], float)  # no decimal, serial on JSON


def test_external_id_distingue_les_identifiants_en_double():
    ids = [external_id(d) for d in SAMPLE]
    assert ids[0] != ids[1]  # same id_decision
    assert ids[2] is None  # empty url: decision without id
