from datetime import date

import pytest

from src.pipeline.runlog import (
    finish_pipeline_run,
    non_blocking_note,
    skip_pipeline_run,
    start_pipeline_run,
)

ZEROS = {"fetched": 0, "new": 0, "changed": 0}


class FakeStore:
    def __init__(self):
        self.calls = []
        self.closed = False

    def start_run(self, source, date_start, date_end, date_type):
        self.calls.append(("start", source, date_start, date_end, date_type))
        return 42

    def finish_run(self, run_id, status, counts, error=None):
        self.calls.append(("finish", run_id, status, counts, error))

    def close(self):
        self.closed = True


@pytest.fixture
def store():
    return FakeStore()


def test_debut_du_run_pipeline(store):
    day = date(2026, 9, 27)
    assert start_pipeline_run("nightly", day, lambda: store) == 42
    assert store.calls == [("start", "pipeline", day, day, "nightly")]
    assert store.closed


def test_fin_en_echec_avec_le_nom_de_l_etape(store):
    finish_pipeline_run(42, "failed", "silver", lambda: store)
    assert store.calls == [("finish", 42, "failed", ZEROS, "silver")]
    assert store.closed


def test_run_ignore(store):
    skip_pipeline_run(43, "42", lambda: store)
    assert store.calls == [("finish", 43, "skipped", ZEROS, "lock held by pipeline run 42")]


def test_connexion_fermee_meme_en_cas_d_erreur(store):
    def finish_run(*args, **kwargs):
        raise RuntimeError("base indisponible")

    store.finish_run = finish_run
    with pytest.raises(RuntimeError):
        finish_pipeline_run(42, "success", None, lambda: store)
    assert store.closed


def test_note_des_etapes_non_bloquantes():
    assert non_blocking_note([]) is None
    assert non_blocking_note(["adlc-scraper"]) == "non-blocking step failed: adlc-scraper"
    assert (
        non_blocking_note(["adlc-opendata", "adlc-scraper"])
        == "non-blocking steps failed: adlc-opendata, adlc-scraper"
    )
