"""Stock-code autocomplete: /api/symbols/suggest + suggest_symbols()."""
from fastapi.testclient import TestClient

from app.main import create_app
from app.universe import UNIVERSE, suggest_symbols


PW = "secret-pass-1"


def test_suggest_prefix_and_name():
    r = suggest_symbols("07")
    syms = [x["symbol"] for x in r]
    assert "0700.HK" in syms and "0762.HK" in syms
    assert all(s.startswith("07") for s in syms)

    r = suggest_symbols("700")
    assert r and r[0]["symbol"] == "0700.HK"
    assert r[0]["name_zh"] == "騰訊控股"

    r = suggest_symbols("AAP")
    assert any(x["symbol"] == "AAPL" for x in r)

    r = suggest_symbols("騰訊")
    assert r[0]["symbol"] == "0700.HK"

    r = suggest_symbols("tencent")
    assert any(x["symbol"] == "0700.HK" for x in r)

    assert suggest_symbols("") == []
    assert suggest_symbols("   ") == []
    assert len(suggest_symbols("0", limit=5)) <= 5
    assert len(UNIVERSE) >= 80


def test_suggest_api_requires_auth_and_returns_matches(feed):
    app = create_app(db_path=":memory:", feed=feed, pending_interval=0)
    c = TestClient(app, follow_redirects=False)
    assert c.get("/api/symbols/suggest", params={"q": "07"}).status_code == 401

    c.post("/api/auth/register", json={"username": "alice", "password": PW, "password_confirm": PW,
                                       "email": "alice@example.com"})
    r = c.get("/api/symbols/suggest", params={"q": "07", "limit": 10})
    assert r.status_code == 200
    body = r.json()
    assert body["query"] == "07"
    syms = [x["symbol"] for x in body["results"]]
    assert "0700.HK" in syms
    row = next(x for x in body["results"] if x["symbol"] == "0700.HK")
    assert row["name"] == "騰訊控股" and row["market"] == "HK" and "name_en" in row

    r = c.get("/api/symbols/suggest", params={"q": "AAP"})
    assert any(x["symbol"] == "AAPL" for x in r.json()["results"])

    # exact-code lookup still works alongside suggest
    q = c.get("/api/quote", params={"symbol": "0700.HK"})
    assert q.status_code == 200 and q.json()["symbol"] == "0700.HK"
