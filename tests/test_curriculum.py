"""Week1 curriculum MC, compliance (P1–P2), and 1% boost."""
import time

import pytest
from fastapi.testclient import TestClient

from app.curriculum import CURRENT_WEEK_ID, load_mc, score_answers
from app.engine import DEFAULT_INITIAL_CASH
from app.main import create_app

PW = "secret-pass-1"
WEEK = CURRENT_WEEK_ID


@pytest.fixture
def app(feed):
    return create_app(db_path=":memory:", feed=feed, pending_interval=0)


def client(app):
    return TestClient(app, follow_redirects=False)


def register(c, name, pw=PW, email=None):
    return c.post("/api/auth/register", json={
        "username": name, "password": pw, "password_confirm": pw,
        "email": email or f"{name}@example.com",
    })


def correct_answers():
    mc = load_mc(WEEK)
    return {q["id"]: q["answer"] for q in mc["questions"]}


def test_score_answers_unit():
    mc = load_mc(WEEK)
    perfect = score_answers(mc, correct_answers())
    assert perfect["score"] == 7 and perfect["passed"] is True and perfect["total"] == 7
    zero = score_answers(mc, {q["id"]: "Z" for q in mc["questions"]})
    assert zero["score"] == 0 and zero["passed"] is False
    partial = correct_answers()
    partial["q1"] = "A"
    partial["q2"] = "A"
    got = score_answers(mc, partial)
    assert got["score"] == 5 and got["passed"] is True


def test_current_week_strips_answers(app):
    c = client(app)
    assert c.get("/api/curriculum/week/current").status_code == 401
    register(c, "alice")
    r = c.get("/api/curriculum/week/current")
    assert r.status_code == 200
    body = r.json()
    assert body["weekId"] == WEEK
    assert "基本面" in body["title"]
    assert "基本面分析" in body["lesson"]
    assert body["universe"] == ["AAPL", "MSFT", "JNJ", "PG", "JPM", "XOM", "SPY"]
    assert body["passScore"] == 5 and body["total"] == 7
    assert len(body["questions"]) == 7
    for q in body["questions"]:
        assert "answer" not in q and "explain" not in q
        assert q["id"] and q["stem"] and q["choices"]
    assert body["userStatus"] == {"mcScore": None, "mcPassed": False, "submitted": False}


def test_submit_scoring_and_leaderboard(app):
    c = client(app)
    register(c, "alice")
    bad = c.post(f"/api/curriculum/week/{WEEK}/submit", json={"answers": {"q1": "A"}})
    assert bad.status_code == 200
    assert bad.json()["score"] < 5 and bad.json()["passed"] is False
    # answers leaked only after submit
    assert bad.json()["details"][0]["answer"] == "B"

    good = c.post(f"/api/curriculum/week/{WEEK}/submit", json={"answers": correct_answers()})
    assert good.status_code == 200
    g = good.json()
    assert g["score"] == 7 and g["passed"] is True and g["total"] == 7

    cur = c.get("/api/curriculum/week/current").json()
    assert cur["userStatus"] == {"mcScore": 7, "mcPassed": True, "submitted": True}

    board = c.get(f"/api/curriculum/week/{WEEK}/leaderboard").json()
    assert board["weekId"] == WEEK and board["topRewardUsd"] == 1000
    assert board["rows"][0]["username"] == "alice" and board["rows"][0]["score"] == 7


def test_compliance_false_without_holdings(app):
    c = client(app)
    register(c, "alice")
    c.post(f"/api/curriculum/week/{WEEK}/submit", json={"answers": correct_answers()})
    st = c.get("/api/portfolio/compliance").json()
    assert st["matchedTickers"] == []
    assert st["ok"] is False
    assert st["heldDays"] == 0
    assert st["mcPassed"] is True
    assert st["canBoost"] is False

    # buy non-universe stock → still not compliant
    assert c.post("/api/me/orders", json={
        "symbol": "TSLA", "side": "BUY", "type": "MARKET", "qty": 1,
    }).status_code == 200
    st2 = c.get("/api/portfolio/compliance").json()
    assert st2["matchedTickers"] == [] and st2["ok"] is False


def test_boost_rejected_until_7_days_then_once(app):
    c = client(app)
    register(c, "alice")
    c.post(f"/api/curriculum/week/{WEEK}/submit", json={"answers": correct_answers()})

    buy = c.post("/api/me/orders", json={
        "symbol": "AAPL", "side": "BUY", "type": "MARKET", "qty": 10,
    })
    assert buy.status_code == 200 and buy.json()["status"] == "FILLED"

    st = c.get("/api/portfolio/compliance").json()
    assert st["matchedTickers"] == ["AAPL"]
    assert st["ok"] is False  # heldDays ~ 0
    assert st["canBoost"] is False
    assert c.post("/api/boost/apply").status_code == 400

    # time-travel: inject compliant_since 8 days ago
    eng = app.state.engine
    eng.set_curriculum_compliant_since("alice", WEEK, time.time() - 8 * 86400)

    st2 = c.get("/api/portfolio/compliance").json()
    assert st2["heldDays"] >= 7 and st2["ok"] is True and st2["canBoost"] is True

    cash_before = next(a for a in c.get("/api/me/portfolio").json()["accounts"] if a["currency"] == "USD")["cash"]
    equity = c.get("/api/me/portfolio").json()["total"]["equity"]
    r = c.post("/api/boost/apply")
    assert r.status_code == 200
    body = r.json()
    assert body["ok"] and body["credited"]
    assert body["amount"] == round(equity * 0.01 + 0.0, 2)
    cash_after = next(a for a in c.get("/api/me/portfolio").json()["accounts"] if a["currency"] == "USD")["cash"]
    assert abs(cash_after - cash_before - body["amount"]) < 0.011

    # second apply rejected
    assert c.post("/api/boost/apply").status_code == 400
    st3 = c.get("/api/portfolio/compliance").json()
    assert st3["boosted"] is True and st3["canBoost"] is False


def test_selling_last_universe_stock_resets_timer(app):
    c = client(app)
    register(c, "alice")
    assert c.post("/api/me/orders", json={
        "symbol": "MSFT", "side": "BUY", "type": "MARKET", "qty": 5,
    }).json()["status"] == "FILLED"
    st = c.get("/api/portfolio/compliance").json()
    assert st["matchedTickers"] == ["MSFT"] and st["compliantSince"] is not None

    assert c.post("/api/me/orders", json={
        "symbol": "MSFT", "side": "SELL", "type": "MARKET", "qty": 5,
    }).json()["status"] == "FILLED"
    st2 = c.get("/api/portfolio/compliance").json()
    assert st2["matchedTickers"] == [] and st2["compliantSince"] is None and st2["heldDays"] == 0
