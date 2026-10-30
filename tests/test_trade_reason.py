"""Optional trade reason on place + PATCH after the fact."""
from fastapi.testclient import TestClient

import pytest

from app.main import create_app

PW = "secret-pass-1"


@pytest.fixture
def app(feed):
    return create_app(db_path=":memory:", feed=feed, pending_interval=0)


def client(app):
    return TestClient(app, follow_redirects=False)


def register(c, name, pw=PW):
    return c.post("/api/auth/register", json={
        "username": name, "password": pw, "password_confirm": pw,
        "email": f"{name}@example.com",
    })


def test_place_without_reason_ok(app):
    c = client(app)
    register(c, "alice")
    r = c.post("/api/me/orders", json={"symbol": "AAPL", "side": "BUY", "type": "MARKET", "qty": 1})
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "FILLED"
    assert body.get("reason") in (None, "")
    trades = c.get("/api/me/trades").json()
    assert trades[0].get("reason") in (None, "")


def test_place_with_reason_stored_and_in_history(app):
    c = client(app)
    register(c, "alice")
    r = c.post("/api/me/orders", json={
        "symbol": "AAPL", "side": "BUY", "type": "MARKET", "qty": 2,
        "reason": "  基本面買入  ",
    })
    assert r.status_code == 200
    assert r.json()["reason"] == "基本面買入"
    orders = c.get("/api/me/orders").json()
    assert orders[0]["reason"] == "基本面買入"
    trades = c.get("/api/me/trades").json()
    assert trades[0]["reason"] == "基本面買入"
    view = c.get("/api/users/alice/view").json()
    assert view["trades"][0]["reason"] == "基本面買入"


def test_place_whitespace_reason_treated_as_empty(app):
    c = client(app)
    register(c, "alice")
    r = c.post("/api/me/orders", json={
        "symbol": "AAPL", "side": "BUY", "type": "MARKET", "qty": 1, "reason": "   ",
    })
    assert r.status_code == 200
    assert r.json().get("reason") in (None, "")


def test_place_reason_too_long_400(app):
    c = client(app)
    register(c, "alice")
    r = c.post("/api/me/orders", json={
        "symbol": "AAPL", "side": "BUY", "type": "MARKET", "qty": 1,
        "reason": "x" * 501,
    })
    assert r.status_code == 400
    assert "500" in r.json()["detail"]


def test_patch_order_reason_add_edit_clear(app):
    c = client(app)
    register(c, "alice")
    o = c.post("/api/me/orders", json={"symbol": "AAPL", "side": "BUY", "type": "MARKET", "qty": 1}).json()
    oid = o["id"]
    r = c.patch(f"/api/me/orders/{oid}/reason", json={"reason": "  事後補寫  "})
    assert r.status_code == 200 and r.json()["reason"] == "事後補寫"
    assert c.get("/api/me/trades").json()[0]["reason"] == "事後補寫"
    r2 = c.patch(f"/api/me/orders/{oid}/reason", json={"reason": "改過"})
    assert r2.json()["reason"] == "改過"
    r3 = c.patch(f"/api/me/orders/{oid}/reason", json={"reason": ""})
    assert r3.status_code == 200 and r3.json().get("reason") in (None, "")
    assert c.get("/api/me/trades").json()[0].get("reason") in (None, "")


def test_patch_trade_reason_and_authz(app):
    alice, bob = client(app), client(app)
    register(alice, "alice")
    register(bob, "bob")
    alice.post("/api/me/orders", json={"symbol": "AAPL", "side": "BUY", "type": "MARKET", "qty": 1})
    tid = alice.get("/api/me/trades").json()[0]["id"]
    oid = alice.get("/api/me/orders").json()[0]["id"]
    assert bob.patch(f"/api/me/orders/{oid}/reason", json={"reason": "偷改"}).status_code == 400
    assert bob.patch(f"/api/me/trades/{tid}/reason", json={"reason": "偷改"}).status_code == 400
    r = alice.patch(f"/api/me/trades/{tid}/reason", json={"reason": "成交補寫"})
    assert r.status_code == 200 and r.json()["reason"] == "成交補寫"
    assert alice.get("/api/me/orders").json()[0]["reason"] == "成交補寫"


def test_patch_reason_requires_auth(app):
    c = client(app)
    register(c, "alice")
    oid = c.post("/api/me/orders", json={"symbol": "AAPL", "side": "BUY", "type": "MARKET", "qty": 1}).json()["id"]
    anon = client(app)
    assert anon.patch(f"/api/me/orders/{oid}/reason", json={"reason": "x"}).status_code == 401
