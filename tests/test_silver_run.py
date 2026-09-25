from collections import Counter

from psycopg.types.json import Jsonb

from src.silver import adlc_opendata, judilibre
from src.silver.run import TRANSFORMS, build_rows, to_params

RECORDS = [
    ("a", {"jurisdiction": "cc", "numbers": ["19-24.008"], "decision_date": "2026-09-15"}),
    ("b", {"jurisdiction": "xx", "numbers": [], "decision_date": "2026-09-15"}),
    ("  ", {"jurisdiction": "cc"}),
]


def test_sources_de_silver():
    assert TRANSFORMS == {
        judilibre.SOURCE: judilibre.transform,
        adlc_opendata.SOURCE: adlc_opendata.transform,
    }
    assert "adlc-scraper" not in TRANSFORMS


def test_build_rows_saute_les_lignes_sans_identifiant_et_compte():
    counts, anomalies = Counter(), Counter()
    rows = list(build_rows(RECORDS, judilibre.transform, counts, anomalies))
    assert [row.external_id for row in rows] == ["a", "b"]
    assert counts == Counter(read=3, written=2, skipped=1)
    assert anomalies == Counter(
        invalid_decision_number=1, unknown_jurisdiction=1, missing_external_id=1
    )


def test_to_params_encapsule_les_attributs_en_jsonb():
    counts, anomalies = Counter(), Counter()
    row = next(build_rows(RECORDS, judilibre.transform, counts, anomalies))
    params = to_params(row)
    assert params[:2] == ("judilibre", "a")
    assert params[8] == []
    assert isinstance(params[10], Jsonb)
