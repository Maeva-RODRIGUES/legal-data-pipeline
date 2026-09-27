import io
import json
from contextlib import contextmanager

import httpx
import pytest

from src.collector.adlc_opendata import ingest, run
from src.collector.adlc_opendata.ingest import download, external_id, iter_decisions

# URL stable de data.gouv.fr (ADLC_OPENDATA_URL) : 302 vers le fichier horodaté.
STABLE_URL = "https://www.data.gouv.fr/api/1/datasets/r/be23f793-a37b-4613-8a80-c6b4116058fb"
FILE_URL = (
    "https://static.data.gouv.fr/resources/"
    "decisions-publiees-par-lautorite-de-la-concurrence-depuis-1988/"
    "20260927-100049/adlc-texte-complet-publications.json"
)

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


@pytest.fixture
def data_gouv(monkeypatch):
    """httpx.stream servi par un MockTransport, avec les options passées par download."""
    requested = []
    body = json.dumps(SAMPLE, ensure_ascii=False).encode("utf-8")

    def handler(request):
        requested.append(str(request.url))
        if str(request.url) == STABLE_URL:
            return httpx.Response(302, headers={"Location": FILE_URL})
        if str(request.url) == FILE_URL:
            return httpx.Response(200, content=body)
        return httpx.Response(404)

    @contextmanager
    def stream(method, url, **kwargs):
        with httpx.Client(transport=httpx.MockTransport(handler)) as client:
            with client.stream(method, url, **kwargs) as response:
                yield response

    monkeypatch.setattr(ingest.httpx, "stream", stream)
    return requested, body


def test_telechargement_suit_la_redirection_de_l_url_stable(data_gouv, tmp_path):
    requested, body = data_gouv
    dest = tmp_path / "raw" / "adlc.json"
    assert download(STABLE_URL, dest) == dest
    assert requested == [STABLE_URL, FILE_URL]
    assert dest.read_bytes() == body
    assert not dest.with_suffix(".json.part").exists()


def test_redirection_vers_un_fichier_absent_echoue_sans_ecraser(data_gouv, tmp_path):
    requested, _ = data_gouv
    dest = tmp_path / "adlc.json"
    dest.write_bytes(b"ancien fichier")
    with pytest.raises(httpx.HTTPStatusError):
        download("https://www.data.gouv.fr/api/1/datasets/r/absent", dest)
    assert dest.read_bytes() == b"ancien fichier"
