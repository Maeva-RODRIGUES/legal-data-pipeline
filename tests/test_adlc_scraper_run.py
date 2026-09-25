import json
from pathlib import Path

import httpx
import pytest

from src.collector.adlc_scraper.client import AdlcClient
from src.collector.adlc_scraper.parsers import parse_listing
from src.collector.adlc_scraper.run import (
    LISTING_PATH,
    SOURCE,
    find_missing,
    normalize_url,
    save_items,
    to_payload,
)
from src.storage.bronze_store import payload_hash

FIXTURE = Path(__file__).parent / "fixtures" / "adlc_listing.html"


class FakeStore:
    """Même logique que BronzeStore.save, en mémoire."""

    def __init__(self):
        self.docs = {}

    def save(self, source, external_id, payload, run_id):
        key, new_hash = (source, external_id), payload_hash(payload)
        old = self.docs.get(key)
        self.docs[key] = new_hash
        if old is None:
            return "new"
        return "unchanged" if old == new_hash else "changed"


@pytest.fixture(scope="module")
def items():
    return parse_listing(FIXTURE.read_text(encoding="utf-8"))


def fetch_listing(requests):
    def handler(request):
        requests.append(request.url.raw_path.decode())
        if request.url.path == "/robots.txt":
            return httpx.Response(200, text="User-agent: *\nDisallow: /*?\n")
        return httpx.Response(200, content=FIXTURE.read_bytes())

    with AdlcClient(transport=httpx.MockTransport(handler), sleep=lambda s: None) as client:
        return parse_listing(client.get_html(LISTING_PATH))


def test_une_seule_page_demandee():
    requests = []
    assert len(fetch_listing(requests)) == 20
    assert requests == ["/robots.txt", LISTING_PATH]


def test_payload_serialisable_en_json(items):
    payload = to_payload(items[0])
    assert json.loads(json.dumps(payload)) == payload
    assert payload["decision_date"] == str(items[0].decision_date)


def test_deux_runs_consecutifs_sont_idempotents():
    store = FakeStore()
    first = save_items(store, fetch_listing([]), run_id=1)
    second = save_items(store, fetch_listing([]), run_id=2)
    assert first == {"fetched": 20, "new": 20, "changed": 0, "unchanged": 0}
    assert second == {"fetched": 20, "new": 0, "changed": 0, "unchanged": 20}
    assert all(source == SOURCE for source, _ in store.docs)


def test_identifiant_bronze_est_l_url(items):
    store = FakeStore()
    save_items(store, items, run_id=1)
    assert {ext_id for _, ext_id in store.docs} == {i.url for i in items}


def test_find_missing_liste_les_decisions_absentes_de_l_open_data(items):
    known = {normalize_url(i.url) for i in items[1:]}
    assert find_missing(items, known) == [items[0]]
    assert find_missing(items, known | {normalize_url(items[0].url)}) == []


def test_normalize_url_ignore_slash_final_et_espaces():
    assert normalize_url(" https://x.fr/fr/avis/a/ ") == "https://x.fr/fr/avis/a"
