import httpx
import pytest

from src.collector.judilibre.client import JudilibreClient, JudilibreError


def make_client(handler, max_retries=3):
    return JudilibreClient(
        "fake-key",
        transport=httpx.MockTransport(handler),
        max_retries=max_retries,
        sleep=lambda s: None,
    )


def test_scan_suit_le_curseur_jusqu_a_la_derniere_page():
    def handler(request):
        assert request.headers["KeyId"] == "fake-key"
        cursor = request.url.params.get("searchAfter")
        if cursor is None:
            return httpx.Response(
                200,
                json={
                    "results": [{"id": "a"}, {"id": "b"}],
                    "next_batch": "date_start=2026-09-15&date_end=2026-09-16"
                    "&batch_size=2&searchAfter=0%26123%26b",
                },
            )
        assert cursor == "0&123&b"  # le curseur est renvoyé décodé, tel que fourni
        return httpx.Response(200, json={"results": [{"id": "c"}], "next_batch": None})

    ids = [d["id"] for d in make_client(handler).scan("2026-09-15", "2026-09-16", batch_size=2)]
    assert ids == ["a", "b", "c"]


def test_scan_conserve_les_filtres_absents_de_next_batch():
    seen = []

    def handler(request):
        seen.append(request.url.params.get("jurisdiction"))
        if "searchAfter" not in request.url.params:
            return httpx.Response(
                200, json={"results": [{"id": "a"}], "next_batch": "searchAfter=0%261%26a"}
            )
        return httpx.Response(200, json={"results": [], "next_batch": None})

    list(make_client(handler).scan("2026-09-15", "2026-09-16", jurisdiction="cc"))
    assert seen == ["cc", "cc"]


def test_reessaie_apres_429_puis_reussit():
    calls = {"n": 0}

    def handler(request):
        calls["n"] += 1
        if calls["n"] == 1:
            return httpx.Response(429, headers={"Retry-After": "1"})
        return httpx.Response(200, json={"results": [{"id": "a"}], "next_batch": None})

    assert [d["id"] for d in make_client(handler).scan("2026-09-15", "2026-09-16")] == ["a"]
    assert calls["n"] == 2


def test_erreur_definitive_sans_reessai():
    def handler(request):
        return httpx.Response(401, text="clé invalide")

    with pytest.raises(JudilibreError, match="401"):
        list(make_client(handler).scan("2026-09-15", "2026-09-16"))


def test_abandonne_apres_trop_d_echecs():
    def handler(request):
        return httpx.Response(503)

    with pytest.raises(JudilibreError, match="3 tentatives"):
        list(make_client(handler, max_retries=3).scan("2026-09-15", "2026-09-16"))
