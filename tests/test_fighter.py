"""Tests for 理財戰士: base 100 + 1 per USD 10k MV + API."""
import pytest
from fastapi.testclient import TestClient

from app.fighter import BASE_STAT, MV_PER_POINT, affinity_of, ai_stats, compute_fighter_stats
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
    assert affinity_of("NVDA")[0] == "atk"
    assert affinity_of("JPM")[0] == "def"
    assert affinity_of("SPY")[0] == "spd"
    assert affinity_of("JNJ")[0] == "def"
    assert affinity_of("AAPL")[0] == "atk"
    # unknown still returns a primary
    assert affinity_of("ZZZZ")[0] in ("atk", "def", "spd")


def test_stats_plus_one_per_10k_usd(eng, feed):
    """$30k NVDA (ATK) → ATK = 100+3; other stats stay 100 if no holdings."""
    # NVDA @ 150 → 200 shares = 30,000 USD ATK
    eng.place_order("alice", "NVDA", "BUY", "MARKET", 200)
    s = compute_fighter_stats(eng.portfolio("alice"))
    assert s["atk"] == pytest.approx(BASE_STAT + 30_000 / MV_PER_POINT)
    assert s["atk"] == pytest.approx(103.0)
    assert s["def"] == pytest.approx(100.0)
    assert s["spd"] == pytest.approx(100.0)
    assert "基礎每項 100" in s["tip"]

    # Add JPM DEF: 300 * 100 = 30,000 → DEF +3
    eng.place_order("alice", "JPM", "BUY", "MARKET", 300)
    s2 = compute_fighter_stats(eng.portfolio("alice"))
    assert s2["atk"] == pytest.approx(103.0)
    assert s2["def"] == pytest.approx(103.0)
    assert any(b["symbol"] == "NVDA" and b["affinity"] == "atk" for b in s2["breakdown"])


def test_cash_only_is_base_100(eng):
    s = compute_fighter_stats(eng.portfolio("alice"))
    assert s["atk"] == pytest.approx(100.0)
    assert s["def"] == pytest.approx(100.0)
    assert s["spd"] == pytest.approx(100.0)
    assert s["cash_fraction"] > 0.9


def test_spd_etf_boosts_speed(eng):
    eng.feed.prices["SPY"] = 500.0
    eng.place_order("alice", "SPY", "BUY", "MARKET", 40)  # 20k USD SPD
    s = compute_fighter_stats(eng.portfolio("alice"))
    assert s["spd"] == pytest.approx(102.0)
    assert s["spd"] >= s["atk"]


def test_ai_stats_mirror():
    mirror = {"atk": 120, "def": 110, "spd": 105, "dominant": "atk"}
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
    assert body["atk"] == pytest.approx(100.0)
    assert "基礎每項 100" in body["tip"]
    assert c.get("/fighter").status_code == 200
    assert "理財戰士" in c.get("/fighter").text


def test_fighter_match_and_result(app, feed):
    c = client(app)
    register(c, "alice")
    c2 = client(app)
    assert register(c2, "bob").status_code == 200
    # alice ATK (NVDA), bob DEF (JPM)
    assert c.post("/api/me/orders", json={"symbol": "NVDA", "side": "BUY", "type": "MARKET", "qty": 200}).status_code == 200
    assert c2.post("/api/me/orders", json={"symbol": "JPM", "side": "BUY", "type": "MARKET", "qty": 400}).status_code == 200

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


def test_fighter_page_has_three_maps(app):
    c = client(app)
    register(c, "alice")
    page = c.get("/fighter")
    assert page.status_code == 200
    text = page.text
    assert "選擇地圖" in text
    assert 'data-map="hkex"' in text
    assert 'data-map="wallstreet"' in text
    assert 'data-map="vault"' in text
    assert "港交所擂台" in text
    assert "華爾街夜景" in text
    assert "銀行金庫" in text
    assert 'id="mapPicker"' in text
    assert 'id="mapLabel"' in text
    assert "基礎每項 100" in text


def test_fighter_js_maps_have_height_and_movers():
    """Static check: each map has multi-height platforms + a moving L2 platform."""
    from pathlib import Path

    js = Path(__file__).resolve().parents[1] / "static" / "fighter.js"
    src = js.read_text(encoding="utf-8")
    assert "港交所擂台" in src and "華爾街夜景" in src and "銀行金庫" in src
    assert 'id: "hkex"' in src
    assert 'id: "wallstreet"' in src
    assert 'id: "vault"' in src
    assert 'kind: "moving"' in src
    assert 'axis: "x"' in src
    assert 'axis: "y"' in src
    assert "updateMovingPlatforms" in src
    assert "onPlat" in src
    assert "mapPicker" in Path(__file__).resolve().parents[1].joinpath("static/fighter.html").read_text(
        encoding="utf-8"
    )
