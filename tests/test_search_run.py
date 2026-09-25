from collections import Counter

from src.search.rebuild import RebuildResult
from src.search.run import exit_code, format_report, stats_params

NEW = "decisions_20260925_143000"
PREVIOUS = "decisions_20260924_090000"
SILVER = {"adlc-opendata": 6683, "judilibre": 24}


def switched(**overrides):
    fields = {
        "index_name": NEW,
        "silver_counts": dict(SILVER),
        "indexed_counts": dict(SILVER),
        "alias_switched": True,
        "previous_index": PREVIOUS,
        "deleted_indexes": ["decisions_20260923_090000"],
    }
    return RebuildResult(**(fields | overrides))


def not_switched():
    return RebuildResult(
        NEW,
        dict(SILVER),
        {"adlc-opendata": 6682, "judilibre": 24},
        Counter({"adlc-opendata": 1}),
        reason="comptes différents (adlc-opendata : 6683 attendue(s), ...)",
    )


def test_stats_une_ligne_par_source():
    assert stats_params(7, switched()) == [
        (7, NEW, "adlc-opendata", 6683, 6683, 0, True),
        (7, NEW, "judilibre", 24, 24, 0, True),
    ]


def test_stats_index_non_compte():
    result = RebuildResult(NEW, dict(SILVER))
    assert stats_params(7, result) == [
        (7, NEW, "adlc-opendata", 6683, None, 0, False),
        (7, NEW, "judilibre", 24, None, 0, False),
    ]


def test_stats_source_absente_d_un_cote():
    result = RebuildResult(NEW, {"judilibre": 24}, {"autre": 1}, Counter({"rejet": 2}))
    assert stats_params(7, result) == [
        (7, NEW, "autre", 0, 1, 0, False),
        (7, NEW, "judilibre", 24, 0, 0, False),
        (7, NEW, "rejet", 0, 0, 2, False),
    ]


def test_rapport_alias_bascule():
    assert format_report(switched()).splitlines() == [
        f"Index {NEW}",
        "  adlc-opendata : 6683 dans Silver, 6683 indexée(s), 0 rejetée(s)",
        "  judilibre     : 24 dans Silver, 24 indexée(s), 0 rejetée(s)",
        f"Alias decisions basculé (index précédent conservé : {PREVIOUS} ; supprimé(s) : 1)",
    ]


def test_rapport_premier_run_et_avertissement():
    result = switched(previous_index=None, deleted_indexes=[], warnings=["suppression de x"])
    assert format_report(result).splitlines()[-2:] == [
        "Alias decisions basculé (index précédent conservé : aucun ; supprimé(s) : 0)",
        "Avertissement : suppression de x",
    ]


def test_rapport_alias_non_bascule():
    assert format_report(not_switched()).splitlines() == [
        f"Index {NEW}",
        "  adlc-opendata : 6683 dans Silver, 6682 indexée(s), 1 rejetée(s)",
        "  judilibre     : 24 dans Silver, 24 indexée(s), 0 rejetée(s)",
        "Alias decisions non basculé : comptes différents (adlc-opendata : 6683 attendue(s), ...)",
    ]


def test_rapport_index_non_compte():
    result = RebuildResult(NEW, {"judilibre": 24}, reason="x")
    assert "  judilibre : 24 dans Silver, index non compté, 0 rejetée(s)" in format_report(result)


def test_code_de_sortie():
    assert exit_code(switched()) == 0
    assert exit_code(switched(warnings=["nettoyage"])) == 0
    assert exit_code(not_switched()) == 1
