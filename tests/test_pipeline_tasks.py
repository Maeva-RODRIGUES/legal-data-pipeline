from datetime import date
from types import SimpleNamespace

import httpx
import pytest

from src.collector.judilibre.client import JudilibreError
from src.pipeline import tasks
from src.pipeline.app import app
from src.pipeline.lock import PipelineLock
from src.pipeline.steps import STEPS, StepFailed, run_entry_point
from tests.test_pipeline_lock import FakeRedis

SUNDAY = date(2026, 9, 27)
MONDAY = date(2026, 9, 28)
TUESDAY = date(2026, 9, 29)
DAILY = ["judilibre", "adlc-scraper", "silver", "search", "search-eval", "quality"]
REQUEST = httpx.Request("GET", "https://example.fr")
REAL_BUILD_CHAIN = tasks.build_chain


def network_error():
    try:
        raise JudilibreError("Échec après 5 tentatives sur /scan") from httpx.ConnectError(
            "refused", request=REQUEST
        )
    except JudilibreError as exc:
        return exc


class Pipeline:
    """Doubles du journal, du verrou et des scripts ; aucune base, aucun broker."""

    def __init__(self):
        self.runs = {}  # run_id -> (date_type, status, error)
        self.lock = PipelineLock(FakeRedis())
        self.outcomes = {}  # nom d'étape -> exception levée par le script
        self.executed = []
        self.today = TUESDAY
        self.sent = []  # chaînes publiées sur le broker

    def start_run(self, trigger, day):
        run_id = len(self.runs) + 1
        self.runs[run_id] = (trigger, "running", None)
        return run_id

    def finish_run(self, run_id, status, error=None):
        self.runs[run_id] = (self.runs[run_id][0], status, error)

    def skip_run(self, run_id, holder):
        self.finish_run(run_id, "skipped", f"lock held by pipeline run {holder}")

    def run_entry_point(self, step):
        self.executed.append(step.name)
        if step.name in self.outcomes:
            raise self.outcomes[step.name]

    def build_chain(self, run_id, names):
        # Publier la chaîne ne l'exécute pas : le worker la traitera ensuite (voir start).
        self.sent.append(REAL_BUILD_CHAIN(run_id, names))
        return SimpleNamespace(apply_async=lambda: None)


@pytest.fixture
def pipeline(monkeypatch):
    fake = Pipeline()
    monkeypatch.setattr(tasks, "start_pipeline_run", fake.start_run)
    monkeypatch.setattr(tasks, "finish_pipeline_run", fake.finish_run)
    monkeypatch.setattr(tasks, "skip_pipeline_run", fake.skip_run)
    monkeypatch.setattr(tasks, "pipeline_lock", lambda: fake.lock)
    monkeypatch.setattr(tasks, "run_entry_point", fake.run_entry_point)
    monkeypatch.setattr(tasks, "paris_today", lambda: fake.today)
    monkeypatch.setattr(tasks, "build_chain", fake.build_chain)
    # Exécution locale : l'exception d'une tâche est relevée et arrête la chaîne.
    monkeypatch.setitem(app.conf, "task_eager_propagates", True)
    return fake


def start(pipeline, trigger="nightly"):
    """Déclenchement, puis exécution de la chaîne publiée, comme par le worker."""
    tasks.start_pipeline.apply(kwargs={"trigger": trigger})
    for sent in pipeline.sent:
        sent.apply()


# Composition de la chaîne


def test_chaine_dans_l_ordre_avec_la_fin_du_run_en_dernier():
    signatures = tasks.build_chain(7, DAILY).tasks
    names = [sig.task.rsplit(".", 1)[1] for sig in signatures]
    assert names == ["run_step"] * len(DAILY) + ["finish_pipeline"]
    assert signatures[0].args == ([], "judilibre", 7)
    assert signatures[0].immutable
    assert [sig.args for sig in signatures[1:-1]] == [(name, 7) for name in DAILY[1:]]
    assert signatures[-1].args == (7,)


@pytest.mark.parametrize(
    ("trigger", "day", "with_opendata", "expected"),
    [
        ("nightly", MONDAY, False, True),
        # publiée le dimanche vers 10 h : pas encore disponible la nuit du dimanche
        ("nightly", SUNDAY, False, False),
        ("nightly", TUESDAY, False, False),
        ("manual", MONDAY, False, False),
        ("manual", TUESDAY, True, True),
    ],
)
def test_open_data_la_nuit_du_lundi_ou_sur_demande(trigger, day, with_opendata, expected):
    assert tasks.includes_opendata(trigger, day, with_opendata) is expected


def test_run_nocturne_du_lundi_commence_par_l_open_data(pipeline):
    pipeline.today = MONDAY
    start(pipeline, "nightly")
    assert pipeline.executed == ["adlc-opendata", *DAILY]


def test_run_manuel_sans_open_data_par_defaut(pipeline):
    pipeline.today = MONDAY
    start(pipeline, "manual")
    assert pipeline.executed == DAILY
    assert pipeline.runs == {1: ("manual", "success", None)}


# Politique de retry


@pytest.mark.parametrize("name", ["adlc-opendata", "judilibre", "adlc-scraper"])
def test_etapes_reseau_reessayees_sur_erreur_reseau(name):
    assert tasks.handle_failure(STEPS[name], network_error(), 0) == "retry"
    assert tasks.handle_failure(STEPS[name], network_error(), 2) == "retry"


@pytest.mark.parametrize("name", ["silver", "search", "search-eval", "quality"])
def test_etapes_de_donnees_jamais_reessayees(name):
    assert tasks.handle_failure(STEPS[name], network_error(), 0) == "fail"


def test_pas_de_retry_sur_une_erreur_permanente():
    assert tasks.handle_failure(STEPS["judilibre"], JudilibreError("HTTP 401"), 0) == "fail"


def test_apres_trois_retries_bloquante_echoue_non_bloquante_continue():
    assert tasks.handle_failure(STEPS["judilibre"], network_error(), 3) == "fail"
    assert tasks.handle_failure(STEPS["adlc-scraper"], network_error(), 3) == "continue"
    assert tasks.handle_failure(STEPS["adlc-opendata"], network_error(), 3) == "continue"


@pytest.mark.parametrize(("retries", "countdown"), [(0, 60), (1, 120), (2, 240)])
def test_retry_avec_attente_exponentielle(pipeline, monkeypatch, retries, countdown):
    class Retried(Exception):
        pass

    received = {}

    def retry(exc=None, countdown=None, **kwargs):
        received.update(exc=exc, countdown=countdown)
        return Retried()

    monkeypatch.setattr(tasks.run_step, "retry", retry)
    error = network_error()
    pipeline.outcomes["judilibre"] = error
    with pytest.raises(Retried):
        tasks.run_step.apply(args=([], "judilibre", 1), retries=retries)
    assert received == {"exc": error, "countdown": countdown}


# Étapes bloquantes et non bloquantes


def test_echec_d_une_etape_bloquante_arrete_la_chaine(pipeline):
    pipeline.outcomes["silver"] = RuntimeError("base indisponible")
    with pytest.raises(RuntimeError):
        start(pipeline)
    assert pipeline.executed == ["judilibre", "adlc-scraper", "silver"]
    assert pipeline.runs == {1: ("nightly", "failed", "silver")}
    assert pipeline.lock.holder() is None


def test_echec_du_scraper_n_arrete_pas_la_chaine(pipeline):
    pipeline.outcomes["adlc-scraper"] = RuntimeError("HTTP 404")
    start(pipeline)
    assert pipeline.executed == DAILY
    assert pipeline.runs == {1: ("nightly", "success", "non-blocking step failed: adlc-scraper")}
    assert pipeline.lock.holder() is None


def test_open_data_et_scraper_en_echec_notes_dans_le_run(pipeline):
    pipeline.today = MONDAY
    pipeline.outcomes["adlc-opendata"] = StepFailed("ADLC_OPENDATA_URL manquante")
    pipeline.outcomes["adlc-scraper"] = RuntimeError("HTTP 404")
    start(pipeline)
    assert pipeline.executed == ["adlc-opendata", *DAILY]
    assert pipeline.runs[1] == (
        "nightly",
        "success",
        "non-blocking steps failed: adlc-opendata, adlc-scraper",
    )


def test_verdict_qualite_en_echec_fait_echouer_le_run(pipeline, monkeypatch):
    # Vrai lanceur pour l'étape quality : main renvoie 1, comme un verdict en échec.
    monkeypatch.setattr("src.quality.run.main", lambda argv=None: 1)

    def run(step):
        pipeline.executed.append(step.name)
        if step.name == "quality":
            run_entry_point(step)

    monkeypatch.setattr(tasks, "run_entry_point", run)
    with pytest.raises(StepFailed, match="quality : code de sortie 1"):
        start(pipeline)
    assert pipeline.runs == {1: ("nightly", "failed", "quality")}


# Verrou


def test_run_ignore_si_le_verrou_est_pris(pipeline):
    pipeline.lock.acquire("99")
    start(pipeline, "manual")
    assert pipeline.sent == []
    assert pipeline.executed == []
    assert pipeline.runs == {1: ("manual", "skipped", "lock held by pipeline run 99")}
    assert pipeline.lock.holder() == "99"


def test_verrou_tenu_pendant_le_run(pipeline, monkeypatch):
    held = []
    monkeypatch.setattr(tasks, "run_entry_point", lambda step: held.append(pipeline.lock.holder()))
    start(pipeline)
    assert held == ["1"] * len(DAILY)
    assert pipeline.lock.holder() is None


def test_envoi_de_la_chaine_en_echec_libere_le_verrou(pipeline, monkeypatch):
    def broken(run_id, names):
        raise ConnectionError("broker indisponible")

    monkeypatch.setattr(tasks, "build_chain", broken)
    with pytest.raises(ConnectionError):
        start(pipeline)
    assert pipeline.runs == {1: ("nightly", "failed", "start")}
    assert pipeline.lock.holder() is None


def test_declenchement_publie_la_chaine_et_laisse_le_run_en_cours(pipeline):
    tasks.start_pipeline.apply(kwargs={"trigger": "nightly"})
    assert len(pipeline.sent) == 1
    assert pipeline.executed == []  # exécutée plus tard, par le worker
    assert pipeline.runs == {1: ("nightly", "running", None)}
    assert pipeline.lock.holder() == "1"
