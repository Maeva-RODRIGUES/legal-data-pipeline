from datetime import UTC, datetime

import pytest

from src.pipeline.app import app
from src.pipeline.schedule import next_run


def test_fuseau_explicite():
    assert app.conf.timezone == "Europe/Paris"
    assert app.conf.enable_utc


def test_run_nocturne_a_03_33():
    entry = app.conf.beat_schedule["nightly-pipeline"]
    assert entry["task"] == "src.pipeline.tasks.start_pipeline"
    assert entry["kwargs"] == {"trigger": "nightly"}
    assert entry["schedule"].hour == {3}
    assert entry["schedule"].minute == {33}


@pytest.mark.parametrize(
    ("now", "expected_utc"),
    [
        # hiver (UTC+1) et été (UTC+2)
        (datetime(2026, 12, 1, 12, 0, tzinfo=UTC), datetime(2026, 12, 2, 2, 33, tzinfo=UTC)),
        (datetime(2026, 7, 1, 12, 0, tzinfo=UTC), datetime(2026, 7, 2, 1, 33, tzinfo=UTC)),
        # avant 03:33 le jour même
        (datetime(2026, 7, 1, 1, 0, tzinfo=UTC), datetime(2026, 7, 1, 1, 33, tzinfo=UTC)),
        # veille des changements d'heure : passage à l'heure d'été puis d'hiver dans la nuit
        (datetime(2026, 3, 28, 12, 0, tzinfo=UTC), datetime(2026, 3, 29, 1, 33, tzinfo=UTC)),
        (datetime(2026, 10, 24, 12, 0, tzinfo=UTC), datetime(2026, 10, 25, 2, 33, tzinfo=UTC)),
    ],
)
def test_prochaine_execution_a_03_33_heure_de_paris(now, expected_utc):
    run = next_run(app, now)
    assert run == expected_utc
    assert (run.hour, run.minute) == (3, 33)
    assert run.tzinfo is not None and str(run.tzinfo) == "Europe/Paris"
