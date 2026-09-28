from types import SimpleNamespace

import pytest

from src.pipeline import trigger


@pytest.fixture
def sent(monkeypatch):
    calls = []

    def delay(**kwargs):
        calls.append(kwargs)
        return SimpleNamespace(id="task-1")

    monkeypatch.setattr(trigger.start_pipeline, "delay", delay)
    return calls


def test_declenchement_manuel_sans_open_data_par_defaut(sent, capsys):
    trigger.main([])
    assert sent == [{"trigger": "manual", "with_opendata": False}]
    assert "(sans open data), tâche task-1" in capsys.readouterr().out


def test_open_data_forcee(sent):
    trigger.main(["--with-opendata"])
    assert sent == [{"trigger": "manual", "with_opendata": True}]


def test_prochaine_execution_sans_rien_lancer(sent, capsys):
    trigger.main(["--next-run"])
    out = capsys.readouterr().out
    assert sent == []
    assert "03:33 (Europe/Paris)" in out
