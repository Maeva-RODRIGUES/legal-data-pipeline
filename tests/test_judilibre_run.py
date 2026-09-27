from datetime import date, timedelta

import pytest

from src.collector.judilibre.run import DEFAULT_WINDOW_DAYS, build_parser, compute_window

TODAY = date(2026, 9, 27)
LAST_END = date(2026, 9, 20)


def test_lookback_14_reprend_14_jours_avant_la_fin_du_dernier_run():
    assert compute_window(LAST_END, TODAY, 14) == (date(2026, 9, 7), TODAY)


def test_lookback_0_reprend_juste_apres_le_dernier_run():
    assert compute_window(LAST_END, TODAY, 0) == (date(2026, 9, 21), TODAY)


def test_lookback_negatif_refuse_par_la_fonction():
    with pytest.raises(ValueError, match="positif ou nul"):
        compute_window(LAST_END, TODAY, -1)


def test_lookback_negatif_refuse_par_la_ligne_de_commande(capsys):
    with pytest.raises(SystemExit):
        build_parser().parse_args(["--lookback-days", "-1"])
    assert "doit être positif ou nul" in capsys.readouterr().err


def test_lookback_absent_de_la_ligne_de_commande_vaut_none():
    assert build_parser().parse_args([]).lookback_days is None


def test_start_explicite_l_emporte_sur_le_lookback():
    start = date(2026, 9, 1)
    end = date(2026, 9, 7)
    assert compute_window(LAST_END, TODAY, 14, start=start, end=end) == (start, end)


def test_sans_run_precedent_fenetre_par_defaut():
    expected_start = TODAY - timedelta(days=DEFAULT_WINDOW_DAYS)
    assert compute_window(None, TODAY, 14) == (expected_start, TODAY)


def test_start_apres_end_n_est_pas_ramene_a_end():
    # dernier run terminé aujourd'hui, sans recouvrement : rien à collecter
    start, end = compute_window(TODAY, TODAY, 0)
    assert start == date(2026, 9, 28)
    assert start > end
