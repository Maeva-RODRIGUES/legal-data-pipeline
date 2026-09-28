from src.pipeline.lock import LOCK_KEY, LOCK_TTL, PipelineLock


class FakeRedis:
    """Les trois commandes utilisées par le verrou, en mémoire."""

    def __init__(self):
        self.data = {}
        self.ttls = {}

    def set(self, key, value, nx=False, ex=None):
        if nx and key in self.data:
            return None
        self.data[key] = value
        self.ttls[key] = ex
        return True

    def get(self, key):
        return self.data.get(key)

    def delete(self, key):
        self.data.pop(key, None)
        self.ttls.pop(key, None)


def test_acquisition_avec_expiration():
    client = FakeRedis()
    assert PipelineLock(client).acquire("12")
    assert client.data == {LOCK_KEY: "12"}
    assert client.ttls == {LOCK_KEY: LOCK_TTL}
    assert LOCK_TTL == 6 * 3600


def test_refus_si_deja_pris():
    lock = PipelineLock(FakeRedis())
    assert lock.acquire("12")
    assert not lock.acquire("13")
    assert lock.holder() == "12"


def test_liberation_par_le_detenteur():
    lock = PipelineLock(FakeRedis())
    lock.acquire("12")
    lock.release("12")
    assert lock.holder() is None
    assert lock.acquire("13")


def test_liberation_sans_effet_avec_un_autre_jeton():
    # Verrou du run 12 expiré puis repris par le run 13 : le run 12 ne doit pas le libérer.
    lock = PipelineLock(FakeRedis())
    lock.acquire("13")
    lock.release("12")
    assert lock.holder() == "13"
