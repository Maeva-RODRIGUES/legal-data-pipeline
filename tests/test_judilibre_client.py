import httpx
import pytest

from src.collector.judilibre_client import JudilibreClient, JudilibreError


def make_client(handler, max_retries=3):
    return JudilibreClient(
        "fake-key",
        transport=httpx.MockTransport(handler),
        max_retries=max_retries,
        sleep=lambda s: None,
    )


def test_export_parcourt_toutes_les_pages():
    pages = {
        "0": {"results": [{"id": "a"}, {"id": "b"}], "next_batch": "/export?batch=1"},
        "1": {"results": [{"id": "c"}], "next_batch": None},
    }

    def handler(request):
        assert request.headers["KeyId"] == "fake-key"
        return httpx.Response(200, json=pages[request.url.params["batch"]])

    ids = [d["id"] for d in make_client(handler).export("2026-09-01", "2026-09-07")]
    assert ids == ["a", "b", "c"]


def test_reessaie_apres_429_puis_reussit():
    calls = {"n": 0}

    def handler(request):
        calls["n"] += 1
        if calls["n"] == 1:
            return httpx.Response(429, headers={"Retry-After": "1"})
        return httpx.Response(200, json={"results": [{"id": "a"}], "next_batch": None})

    assert [d["id"] for d in make_client(handler).export("2026-09-01", "2026-09-07")] == ["a"]
    assert calls["n"] == 2


def test_erreur_definitive_sans_reessai():
    def handler(request):
        return httpx.Response(401, text="clé invalide")

    with pytest.raises(JudilibreError, match="401"):
        list(make_client(handler).export("2026-09-01", "2026-09-07"))


def test_abandonne_apres_trop_d_echecs():
    def handler(request):
        return httpx.Response(503)

    with pytest.raises(JudilibreError, match="3 tentatives"):
        list(make_client(handler, max_retries=3).export("2026-09-01", "2026-09-07"))
