import io
import json

from src.collector.adlc_opendata import run
from src.collector.adlc_opendata.ingest import external_id, iter_decisions

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


class FakeConnection:
    def commit(self):
        pass

    def rollback(self):
        pass


class FakeStore:
    def __init__(self, dsn):
        self.conn = FakeConnection()
        self.saved = []
        self.finished = None
        FakeStore.last = self

    def start_run(self, source, date_start, date_end, date_type):
        return 1

    def save(self, source, ext_id, payload, run_id):
        self.saved.append(ext_id)
        return "new"

    def finish_run(self, run_id, status, counts, error=None):
        self.finished = (status, counts)

    def close(self):
        pass


def test_main_lit_argv_et_non_sys_argv(monkeypatch, tmp_path):
    path = tmp_path / "opendata.json"
    path.write_text(json.dumps(SAMPLE, ensure_ascii=False), encoding="utf-8")
    monkeypatch.setattr("sys.argv", ["celery", "worker", "--concurrency=1"])
    monkeypatch.setattr(run, "load_dotenv", lambda: None)
    monkeypatch.setattr(run, "BronzeStore", FakeStore)
    monkeypatch.setenv("DATABASE_URL", "postgresql://test")
    run.main(argv=["--file", str(path)])
    status, counts = FakeStore.last.finished
    assert status == "success"
    assert counts["fetched"] == 3
    assert counts["missing_id"] == 1
    assert FakeStore.last.saved == [
        "https://example.fr/fr/avis/a",
        "https://example.fr/fr/avis/a-0",
    ]
