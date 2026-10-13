"""Stock-code autocomplete: /api/symbols/suggest + suggest_symbols()."""
from fastapi.testclient import TestClient

from app.main import create_app
from app.universe import UNIVERSE, suggest_symbols


PW = "secret-pass-1"


def test_suggest_prefix_and_name():
    r = suggest_symbols("AAP")
    assert any(x["symbol"] == "AAPL" for x in r)

    r = suggest_symbols("NVDA")
    assert r and r[0]["symbol"] == "NVDA"

    r = suggest_symbols("蘋果")
    assert any(x["symbol"] == "AAPL" for x in r)

    r = suggest_symbols("nvidia")
    assert any(x["symbol"] == "NVDA" for x in r)

    # HK codes no longer in universe
    assert suggest_symbols("0700") == []
    assert suggest_symbols("騰訊") == []
    assert suggest_symbols("") == []
    assert suggest_symbols("   ") == []
    assert len(suggest_symbols("A", limit=5)) <= 5
    assert len(UNIVERSE) >= 40
    assert all(not u["symbol"].endswith(".HK") for u in UNIVERSE)


def test_suggest_api_requires_auth_and_returns_matches(feed):
    app = create_app(db_path=":memory:", feed=feed, pending_interval=0)
    c = TestClient(app, follow_redirects=False)
    assert c.get("/api/symbols/suggest", params={"q": "AAP"}).status_code == 401

    c.post("/api/auth/register", json={"username": "alice", "password": PW, "password_confirm": PW,
                                       "email": "alice@example.com"})
    r = c.get("/api/symbols/suggest", params={"q": "AAP", "limit": 10})
    assert r.status_code == 200
    body = r.json()
    assert body["query"] == "AAP"
    syms = [x["symbol"] for x in body["results"]]
    assert "AAPL" in syms
    row = next(x for x in body["results"] if x["symbol"] == "AAPL")
    assert row["market"] == "US" and "name_en" in row

    r = c.get("/api/symbols/suggest", params={"q": "NVDA"})
    assert any(x["symbol"] == "NVDA" for x in r.json()["results"])

    q = c.get("/api/quote", params={"symbol": "AAPL"})
    assert q.status_code == 200 and q.json()["symbol"] == "AAPL"

    # HK rejected
    bad = c.get("/api/quote", params={"symbol": "0700.HK"})
    assert bad.status_code == 400
