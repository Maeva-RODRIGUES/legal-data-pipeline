import httpx
import pytest

from src.collector.adlc_scraper.client import USER_AGENT, AdlcClient, AdlcError

LISTING = "/fr/liste-des-decisions-et-avis"
ROBOTS = "User-agent: *\nDisallow: /*?\n"


class FakeTime:
    """Horloge factice : sleep() fait avancer le temps sans attendre."""

    def __init__(self):
        self.now = 1000.0
        self.sleeps = []

    def clock(self):
        return self.now

    def sleep(self, seconds):
        self.sleeps.append(seconds)
        self.now += seconds


def make_client(pages, robots=ROBOTS, max_retries=3):
    """pages : chemin -> liste de réponses servies dans l'ordre (la dernière est répétée)."""
    time_ = FakeTime()
    requests = []

    def handler(request):
        requests.append(request)
        if request.url.path == "/robots.txt":
            return httpx.Response(200, text=robots)
        responses = pages[request.url.raw_path.decode()]
        return responses.pop(0) if len(responses) > 1 else responses[0]

    client = AdlcClient(
        transport=httpx.MockTransport(handler),
        max_retries=max_retries,
        sleep=time_.sleep,
        clock=time_.clock,
    )
    return client, requests, time_


def test_robots_interdit_les_url_avec_parametres():
    client, requests, _ = make_client({})
    assert not client.can_fetch(LISTING + "?page=1")
    with pytest.raises(AdlcError, match="robots.txt"):
        client.get_html(LISTING + "?page=1")
    assert [r.url.path for r in requests] == ["/robots.txt"]  # page jamais demandée


def test_robots_autorise_la_page_de_liste():
    client, requests, _ = make_client({LISTING: [httpx.Response(200, text="<html>é</html>")]})
    assert client.can_fetch(LISTING)
    assert client.get_html(LISTING) == "<html>é</html>"
    assert [r.url.path for r in requests] == ["/robots.txt", LISTING]
    assert all(r.headers["User-Agent"] == USER_AGENT for r in requests)


def test_robots_absent_tout_est_autorise():
    time_ = FakeTime()

    def handler(request):
        if request.url.path == "/robots.txt":
            return httpx.Response(404)
        return httpx.Response(200, text="ok")

    client = AdlcClient(
        transport=httpx.MockTransport(handler), sleep=time_.sleep, clock=time_.clock
    )
    assert client.get_html(LISTING) == "ok"


def test_attend_au_moins_2_secondes_entre_deux_requetes():
    client, _, time_ = make_client({LISTING: [httpx.Response(200, text="ok")]})
    client.get_html(LISTING)  # robots.txt, puis la page
    assert time_.sleeps == [2.0]


def test_n_attend_pas_si_le_delai_est_deja_ecoule():
    client, _, time_ = make_client({LISTING: [httpx.Response(200, text="ok")]})
    client.can_fetch(LISTING)
    time_.now += 10
    client.get_html(LISTING)
    assert time_.sleeps == []


def test_respecte_un_crawl_delay_plus_long():
    client, _, time_ = make_client(
        {LISTING: [httpx.Response(200, text="ok")]}, robots=ROBOTS + "Crawl-delay: 5\n"
    )
    client.get_html(LISTING)
    assert time_.sleeps == [5.0]


def test_reessaie_sur_erreur_5xx():
    client, requests, _ = make_client(
        {LISTING: [httpx.Response(503), httpx.Response(200, text="ok")]}
    )
    assert client.get_html(LISTING) == "ok"
    assert len(requests) == 3  # robots.txt + 2 tentatives


def test_reessaie_sur_429_en_respectant_retry_after():
    client, _, time_ = make_client(
        {LISTING: [httpx.Response(429, headers={"Retry-After": "7"}), httpx.Response(200)]}
    )
    client.get_html(LISTING)
    assert 7 in time_.sleeps


def test_reessaie_sur_erreur_reseau():
    time_ = FakeTime()
    calls = []

    def handler(request):
        calls.append(request.url.path)
        if request.url.path == "/robots.txt":
            return httpx.Response(200, text=ROBOTS)
        if calls.count(LISTING) == 1:
            raise httpx.ConnectTimeout("timeout")
        return httpx.Response(200, text="ok")

    client = AdlcClient(
        transport=httpx.MockTransport(handler), sleep=time_.sleep, clock=time_.clock
    )
    assert client.get_html(LISTING) == "ok"


def test_abandonne_apres_trop_d_echecs():
    client, requests, _ = make_client({LISTING: [httpx.Response(500)]}, max_retries=3)
    with pytest.raises(AdlcError, match="3 tentatives"):
        client.get_html(LISTING)
    assert len(requests) == 1 + 3


def test_ne_reessaie_pas_une_erreur_permanente():
    client, requests, _ = make_client({LISTING: [httpx.Response(404)]})
    with pytest.raises(AdlcError, match="HTTP 404"):
        client.get_html(LISTING)
    assert len(requests) == 2


def test_ne_suit_pas_les_redirections():
    client, requests, _ = make_client(
        {LISTING: [httpx.Response(301, headers={"Location": LISTING + "?page=0"})]}
    )
    with pytest.raises(AdlcError, match="HTTP 301"):
        client.get_html(LISTING)
    assert [r.url.path for r in requests] == ["/robots.txt", LISTING]
