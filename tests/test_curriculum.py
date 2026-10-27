"""Fundamentals curriculum: random-draw MC, compliance (P1–P2), and 1% boost."""
import time

import pytest
from fastapi.testclient import TestClient

from app.curriculum import (
    CURRENT_WEEK_ID,
    CurriculumError,
    draw_questions,
    load_lesson_markdown,
    load_mc,
    public_title,
    score_answers,
)
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


def bank_answers():
    mc = load_mc(WEEK)
    return {q["id"]: q["answer"] for q in mc["questions"]}


def answers_for_ids(qids):
    bank = bank_answers()
    return {qid: bank[qid] for qid in qids}


def test_bank_and_draw_unit():
    mc = load_mc(WEEK)
    assert mc["drawCount"] == 7 and mc["passScore"] == 5
    assert mc["bankSize"] >= 20
    assert len(mc["questions"]) == mc["bankSize"]
    drawn = draw_questions(mc)
    assert len(drawn) == 7
    ids = {q["id"] for q in drawn}
    assert len(ids) == 7
    bank_ids = {q["id"] for q in mc["questions"]}
    assert ids <= bank_ids
    # order / membership not fixed across draws (very likely over many trials)
    seen = {tuple(q["id"] for q in draw_questions(mc)) for _ in range(24)}
    assert len(seen) >= 2


def test_score_answers_by_id_not_bank_size():
    mc = load_mc(WEEK)
    bank = bank_answers()
    sample_ids = [q["id"] for q in mc["questions"][:7]]
    perfect = score_answers(mc, {i: bank[i] for i in sample_ids})
    assert perfect["score"] == 7 and perfect["passed"] is True and perfect["total"] == 7

    zero = score_answers(mc, {i: "Z" for i in sample_ids})
    assert zero["score"] == 0 and zero["passed"] is False

    # partial: 5 correct of 7 → pass
    ans = {i: bank[i] for i in sample_ids}
    ans[sample_ids[0]] = "Z"
    ans[sample_ids[1]] = "Z"
    got = score_answers(mc, ans)
    assert got["score"] == 5 and got["passed"] is True

    # cannot submit whole bank to inflate score
    with pytest.raises(CurriculumError):
        score_answers(mc, bank)


def test_public_title_and_lesson_have_no_week1():
    mc = load_mc(WEEK)
    title = public_title(mc)
    assert "Week" not in title and "week1" not in title.lower()
    assert "基本面" in title
    lesson = load_lesson_markdown(WEEK)
    assert "Week 1" not in lesson and "Week1" not in lesson
    assert "基本面" in lesson


def test_current_week_random_draw_strips_answers(app):
    c = client(app)
    assert c.get("/api/curriculum/week/current").status_code == 401
    register(c, "alice")
    r = c.get("/api/curriculum/week/current")
    assert r.status_code == 200
    body = r.json()
    assert body["weekId"] == WEEK  # internal key
    assert "基本面" in body["title"]
    assert "Week 1" not in body["title"] and "Week1" not in body["title"]
    assert "Week 1" not in body["lesson"] and "Week1" not in body["lesson"]
    assert body["universe"] == ["AAPL", "MSFT", "JNJ", "PG", "JPM", "XOM", "SPY"]
    assert body["passScore"] == 5 and body["total"] == 7 and body["drawCount"] == 7
    assert body.get("mode") == "random"
    assert len(body["questions"]) == 7
    for q in body["questions"]:
        assert "answer" not in q and "explain" not in q
        assert q["id"] and q["stem"] and q["choices"]
    assert body["userStatus"] == {"mcScore": None, "mcPassed": False, "submitted": False}

    # second GET very likely different order / set
    orders = [tuple(q["id"] for q in c.get("/api/curriculum/week/current").json()["questions"]) for _ in range(12)]
    assert len(set(orders)) >= 2


def test_submit_scoring_and_leaderboard(app):
    c = client(app)
    register(c, "alice")
    cur = c.get("/api/curriculum/week/current").json()
    qids = [q["id"] for q in cur["questions"]]

    bad = c.post(f"/api/curriculum/week/{WEEK}/submit", json={"answers": {qids[0]: "Z"}})
    assert bad.status_code == 200
    assert bad.json()["score"] < 5 and bad.json()["passed"] is False
    # answers leaked only after submit, graded by id
    detail0 = next(d for d in bad.json()["details"] if d["id"] == qids[0])
    assert detail0["answer"] and detail0["correct"] is False

    good = c.post(
        f"/api/curriculum/week/{WEEK}/submit",
        json={"answers": answers_for_ids(qids)},
    )
    assert good.status_code == 200
    g = good.json()
    assert g["score"] == 7 and g["passed"] is True and g["total"] == 7

    cur2 = c.get("/api/curriculum/week/current").json()
    assert cur2["userStatus"] == {"mcScore": 7, "mcPassed": True, "submitted": True}

    board = c.get(f"/api/curriculum/week/{WEEK}/leaderboard").json()
    assert board["weekId"] == WEEK and board["topRewardUsd"] == 1000
    assert board["rows"][0]["username"] == "alice" and board["rows"][0]["score"] == 7


def test_compliance_false_without_holdings(app):
    c = client(app)
    register(c, "alice")
    cur = c.get("/api/curriculum/week/current").json()
    qids = [q["id"] for q in cur["questions"]]
    c.post(f"/api/curriculum/week/{WEEK}/submit", json={"answers": answers_for_ids(qids)})
    st = c.get("/api/portfolio/compliance").json()
    assert st["matchedTickers"] == []
    assert st["ok"] is False
    assert st["heldDays"] == 0
    assert st["mcPassed"] is True
    assert st["canBoost"] is False

    assert c.post("/api/me/orders", json={
        "symbol": "TSLA", "side": "BUY", "type": "MARKET", "qty": 1,
    }).status_code == 200
    st2 = c.get("/api/portfolio/compliance").json()
    assert st2["matchedTickers"] == [] and st2["ok"] is False


def test_boost_rejected_until_7_days_then_once(app):
    c = client(app)
    register(c, "alice")
    cur = c.get("/api/curriculum/week/current").json()
    qids = [q["id"] for q in cur["questions"]]
    c.post(f"/api/curriculum/week/{WEEK}/submit", json={"answers": answers_for_ids(qids)})

    buy = c.post("/api/me/orders", json={
        "symbol": "AAPL", "side": "BUY", "type": "MARKET", "qty": 10,
    })
    assert buy.status_code == 200 and buy.json()["status"] == "FILLED"

    st = c.get("/api/portfolio/compliance").json()
    assert st["matchedTickers"] == ["AAPL"]
    assert st["ok"] is False
    assert st["canBoost"] is False
    assert c.post("/api/boost/apply").status_code == 400

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
