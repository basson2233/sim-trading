"""GET /api/symbols/hot — dollar-volume ranking for quick-pick chips."""
from fastapi.testclient import TestClient

from app.main import DEFAULT_HOT_SYMBOLS, create_app
from tests.conftest import FakeFeed


PW = "secret-pass-1"


def _client(feed):
    app = create_app(db_path=":memory:", feed=feed, pending_interval=0)
    c = TestClient(app, follow_redirects=False)
    c.post("/api/auth/register", json={
        "password": PW, "password_confirm": PW,
        "email": "alice@example.com",
    })
    return c


def test_hot_requires_auth(feed):
    app = create_app(db_path=":memory:", feed=feed, pending_interval=0)
    c = TestClient(app, follow_redirects=False)
    assert c.get("/api/symbols/hot").status_code == 401


def test_hot_sorts_by_dollar_volume_desc():
    # dollarVolume: NVDA 150*2e8=30B, AAPL 200*5e7=10B, TSLA 300*1e7=3B, MSFT no volume → last
    feed = FakeFeed(
        prices={"AAPL": 200.0, "TSLA": 300.0, "NVDA": 150.0, "MSFT": 400.0, "JPM": 100.0},
        volumes={"AAPL": 50_000_000, "TSLA": 10_000_000, "NVDA": 200_000_000},
        # MSFT intentionally missing volume
    )
    c = _client(feed)
    r = c.get("/api/symbols/hot", params={"symbols": "AAPL,TSLA,NVDA,MSFT"})
    assert r.status_code == 200
    body = r.json()
    syms = [x["symbol"] for x in body["symbols"]]
    assert syms == ["NVDA", "AAPL", "TSLA", "MSFT"]
    assert body["symbols"][0]["dollarVolume"] == 150.0 * 200_000_000
    assert body["symbols"][0]["volume"] == 200_000_000
    assert body["symbols"][-1]["volume"] is None
    assert body["symbols"][-1]["dollarVolume"] is None


def test_hot_default_list_is_quick_set():
    feed = FakeFeed(
        prices={s: 100.0 for s in DEFAULT_HOT_SYMBOLS},
        volumes={s: float(i + 1) * 1_000_000 for i, s in enumerate(DEFAULT_HOT_SYMBOLS)},
    )
    c = _client(feed)
    r = c.get("/api/symbols/hot")
    assert r.status_code == 200
    got = [x["symbol"] for x in r.json()["symbols"]]
    # all defaults present; sorted by volume ascending index → reverse dollar vol
    assert set(got) == set(DEFAULT_HOT_SYMBOLS)
    assert got[0] == DEFAULT_HOT_SYMBOLS[-1]  # highest volume index
    assert got[-1] == DEFAULT_HOT_SYMBOLS[0]


def test_quote_includes_volume_and_dollar_volume():
    feed = FakeFeed(prices={"AAPL": 200.0}, volumes={"AAPL": 1_000_000})
    c = _client(feed)
    q = c.get("/api/quote", params={"symbol": "AAPL"})
    assert q.status_code == 200
    body = q.json()
    assert body["volume"] == 1_000_000
    assert body["dollarVolume"] == 200.0 * 1_000_000
