import importlib
import sys
import types

import httpx
import psycopg
import pytest

from src.collector.judilibre.client import JudilibreError
from src.pipeline.steps import (
    STEPS,
    Step,
    StepFailed,
    is_network_error,
    run_entry_point,
    step_argv,
    step_names,
)

URL = "https://www.data.gouv.fr/fr/datasets/r/abc"
DAILY = ["judilibre", "adlc-scraper", "silver", "search", "search-eval", "quality"]


def test_ordre_des_etapes_sans_open_data():
    assert step_names(with_opendata=False) == DAILY


def test_open_data_en_tete_quand_demandee():
    assert step_names(with_opendata=True) == ["adlc-opendata", *DAILY]


def test_seuls_l_open_data_et_le_scraper_sont_non_bloquants():
    assert {name for name, step in STEPS.items() if not step.blocking} == {
        "adlc-opendata",
        "adlc-scraper",
    }


def test_seules_les_etapes_reseau_peuvent_etre_reessayees():
    assert {name for name, step in STEPS.items() if step.network} == {
        "adlc-opendata",
        "judilibre",
        "adlc-scraper",
    }


def test_chaque_etape_pointe_vers_un_main_existant():
    for step in STEPS.values():
        assert callable(importlib.import_module(step.module).main)


def test_argv_de_l_open_data_contient_l_url():
    assert step_argv(STEPS["adlc-opendata"], {"ADLC_OPENDATA_URL": URL}) == ["--url", URL]


@pytest.mark.parametrize("env", [{}, {"ADLC_OPENDATA_URL": "  "}])
def test_url_de_l_open_data_manquante_fait_echouer_l_etape(env):
    with pytest.raises(StepFailed, match="ADLC_OPENDATA_URL manquante"):
        step_argv(STEPS["adlc-opendata"], env)


def test_argv_vide_pour_les_autres_etapes():
    assert step_argv(STEPS["judilibre"], {}) == []


@pytest.fixture
def fake_module(monkeypatch):
    """Module factice dont main renvoie ou lève ce qu'on lui donne, et note ses appels."""
    module = types.ModuleType("fake_step")
    module.calls = []
    module.outcome = None

    def main(**kwargs):
        module.calls.append(kwargs)
        if isinstance(module.outcome, BaseException):
            raise module.outcome
        return module.outcome

    module.main = main
    monkeypatch.setitem(sys.modules, "fake_step", module)
    return module


def fake_step(takes_argv=True):
    return Step("fake", "fake_step", True, False, takes_argv)


@pytest.mark.parametrize("outcome", [None, 0])
def test_retour_nul_ou_zero_reussit(fake_module, outcome):
    fake_module.outcome = outcome
    run_entry_point(fake_step())
    assert fake_module.calls == [{"argv": []}]


def test_main_sans_argv_appele_sans_argument(fake_module):
    run_entry_point(fake_step(takes_argv=False))
    assert fake_module.calls == [{}]


@pytest.mark.parametrize("outcome", [1, SystemExit(2)])
def test_code_de_sortie_non_nul_fait_echouer(fake_module, outcome):
    fake_module.outcome = outcome
    with pytest.raises(StepFailed, match="code de sortie"):
        run_entry_point(fake_step())


def test_exception_du_script_propagee(fake_module):
    fake_module.outcome = ValueError("boom")
    with pytest.raises(ValueError, match="boom"):
        run_entry_point(fake_step())


def wrapped(cause):
    """Comme JudilibreClient._get : l'erreur finale a l'erreur d'origine pour cause."""
    try:
        raise JudilibreError("Échec après 5 tentatives sur /scan") from cause
    except JudilibreError as exc:
        return exc


def test_erreurs_reseau_reconnues():
    request = httpx.Request("GET", "https://example.fr")
    assert is_network_error(httpx.ConnectError("refused", request=request))
    assert is_network_error(httpx.ReadTimeout("timeout", request=request))
    assert is_network_error(wrapped(httpx.ConnectTimeout("timeout", request=request)))


def test_autres_erreurs_non_reessayees():
    request = httpx.Request("GET", "https://example.fr")
    response = httpx.Response(503, request=request)
    assert not is_network_error(JudilibreError("HTTP 401 sur /scan"))
    assert not is_network_error(wrapped(JudilibreError("HTTP 503 sur /scan")))
    assert not is_network_error(httpx.HTTPStatusError("503", request=request, response=response))
    assert not is_network_error(psycopg.OperationalError("connection refused"))
    assert not is_network_error(ValueError("boom"))
    assert not is_network_error(StepFailed("quality : code de sortie 1"))


def test_chaine_de_causes_cyclique():
    first, second = ValueError("a"), ValueError("b")
    first.__cause__, second.__cause__ = second, first
    assert not is_network_error(first)
