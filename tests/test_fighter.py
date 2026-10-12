"""Tests for 理財戰士: market-value-weighted ATK/DEF/SPD + API."""
import pytest
from fastapi.testclient import TestClient

from app.fighter import affinity_of, ai_stats, compute_fighter_stats
from app.main import create_app

PW = "secret-pass-1"


def client(app):
    return TestClient(app, follow_redirects=False)


def register(c, name, pw=PW, email=None):
    return c.post("/api/auth/register", json={
        "username": name, "password": pw, "password_confirm": pw,
        "email": email or f"{name}@example.com",
    })


@pytest.fixture
def app(feed):
    return create_app(db_path=":memory:", feed=feed, pending_interval=0)


def test_affinity_themes():
    assert affinity_of("0700.HK")[0] == "atk"
    assert affinity_of("0005.HK")[0] == "def"
    assert affinity_of("SPY")[0] == "spd"
    assert affinity_of("0388.HK")[0] == "spd"
    assert affinity_of("NVDA")[0] == "atk"
    assert affinity_of("JNJ")[0] == "def"
    # unknown still returns a primary
    assert affinity_of("ZZZZ.HK")[0] in ("atk", "def", "spd")


def test_stats_weight_by_market_value_not_shares(eng, feed):
    """Larger market value in ATK names → higher ATK even with fewer shares."""
    # Buy lots of DEF (0005.HK @ 100) vs fewer but similar $ of ATK (0700.HK @ 400)
    # 400 shares of 0005 = 40,000 HKD DEF
    eng.place_order("alice", "0005.HK", "BUY", "MARKET", 400)
    # 100 shares of 0700 = 40,000 HKD ATK
    eng.place_order("alice", "0700.HK", "BUY", "MARKET", 100)
    pf = eng.portfolio("alice")
    s = compute_fighter_stats(pf)
    # Equal MV → both boosted; ATK and DEF should both be well above base-ish
    assert s["atk"] > 50
    assert s["def"] > 50
    # Now add huge ATK position: 500 * 400 = 200,000 HKD ATK
    eng.place_order("alice", "0700.HK", "BUY", "MARKET", 500)
    s2 = compute_fighter_stats(eng.portfolio("alice"))
    assert s2["atk"] > s["atk"]
    assert s2["atk"] > s2["def"]
    # breakdown weights sum roughly to invested/equity
    assert any(b["symbol"] == "0700.HK" and b["affinity"] == "atk" for b in s2["breakdown"])
    for b in s2["breakdown"]:
        assert "market_value_base" in b and b["weight"] > 0


def test_cash_heavy_near_base(eng):
    s = compute_fighter_stats(eng.portfolio("alice"))
    # no positions → near base, cash penalty pulls slightly down
    assert 30 <= s["atk"] <= 55
    assert 30 <= s["def"] <= 55
    assert 30 <= s["spd"] <= 55
    assert s["cash_fraction"] > 0.9


def test_spd_etf_boosts_speed(eng):
    # Need a US SPD name in feed — add SPY price via feed
    eng.feed.prices["SPY"] = 500.0
    eng.place_order("alice", "SPY", "BUY", "MARKET", 100)  # 50k USD
    s = compute_fighter_stats(eng.portfolio("alice"))
    assert s["spd"] >= s["atk"]
    assert s["spd"] > 50


def test_ai_stats_mirror():
    mirror = {"atk": 70, "def": 60, "spd": 55, "dominant": "atk"}
    easy = ai_stats("easy", mirror=mirror)
    assert easy["is_ai"] and easy["atk"] < mirror["atk"]
    hard = ai_stats("hard", mirror=mirror)
    assert hard["atk"] >= mirror["atk"]


def test_fighter_api_auth_and_stats(app):
    c = client(app)
    assert c.get("/api/fighter/stats").status_code == 401
    assert c.get("/fighter").status_code == 303
    register(c, "alice")
    r = c.get("/api/fighter/stats")
    assert r.status_code == 200
    body = r.json()
    assert set(body) >= {"atk", "def", "spd", "breakdown", "display_name", "username"}
    assert 30 <= body["atk"] <= 99
    assert c.get("/fighter").status_code == 200
    assert "理財戰士" in c.get("/fighter").text


def test_fighter_match_and_result(app, feed):
    c = client(app)
    register(c, "alice")
    c2 = client(app)
    assert register(c2, "bob").status_code == 200
    # give alice ATK holdings, bob DEF
    assert c.post("/api/me/orders", json={"symbol": "0700.HK", "side": "BUY", "type": "MARKET", "qty": 200}).status_code == 200
    assert c2.post("/api/me/orders", json={"symbol": "0005.HK", "side": "BUY", "type": "MARKET", "qty": 800}).status_code == 200

    bad = c.post("/api/fighter/match", json={"opponent_username": "alice"})
    assert bad.status_code == 400
    ghost = c.post("/api/fighter/match", json={"opponent_username": "nobody"})
    assert ghost.status_code == 400

    m = c.post("/api/fighter/match", json={"opponent_username": "bob"})
    assert m.status_code == 200
    data = m.json()
    assert data["player"]["username"] == "alice"
    assert data["opponent"]["username"] == "bob"
    assert data["player"]["atk"] > data["opponent"]["atk"]
    assert data["opponent"]["def"] > data["player"]["def"]

    ai = c.get("/api/fighter/ai?difficulty=easy&mirror=1")
    assert ai.status_code == 200 and ai.json()["is_ai"] is True

    res = c.post("/api/fighter/result", json={
        "mode": "classmate", "opponent_username": "bob", "winner": "player",
        "player_kos": 2, "opponent_kos": 1,
        "player_stats": {"atk": data["player"]["atk"], "def": data["player"]["def"], "spd": data["player"]["spd"]},
        "opponent_stats": {"atk": data["opponent"]["atk"], "def": data["opponent"]["def"], "spd": data["opponent"]["spd"]},
    })
    assert res.status_code == 200 and res.json()["ok"] is True
    hist = c.get("/api/fighter/history").json()
    assert len(hist["rows"]) >= 1
    assert hist["rows"][0]["winner"] == "player"
