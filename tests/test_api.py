import pytest
from fastapi.testclient import TestClient

from app.main import COOKIE, create_app
from app.quotes import SimFeed

PW = "secret-pass-1"


@pytest.fixture
def app(feed):
    return create_app(db_path=":memory:", feed=feed, pending_interval=0)


def client(app):
    return TestClient(app, follow_redirects=False)


def register(c, name, pw=PW, email=None):
    return c.post("/api/auth/register", json={"username": name, "password": pw, "password_confirm": pw,
                                              "email": email or f"{name}@example.com"})


def hkd(p):
    return next(a for a in p["accounts"] if a["currency"] == "HKD")


def test_everything_requires_auth(app):
    c = client(app)
    for path in ["/api/me/portfolio", "/api/me/orders", "/api/me/trades", "/api/leaderboard",
                 "/api/quote?symbol=AAPL", "/api/history?symbol=AAPL&range=1M", "/api/auth/me"]:
        assert c.get(path).status_code == 401, path
    for path in ["/api/me/orders", "/api/me/reset", "/api/me/orders/1/cancel", "/api/auth/change-password"]:
        assert c.post(path, json={}).status_code in (401, 422), path
    assert c.post("/api/me/orders", json={"symbol": "AAPL", "side": "BUY", "type": "MARKET", "qty": 1}).status_code == 401
    assert c.post("/api/me/reset").status_code == 401
    r = c.get("/")
    assert r.status_code == 303 and r.headers["location"] == "/login"
    assert c.get("/login").status_code == 200 and "註冊" in c.get("/register").text
    # old username-in-URL endpoints are gone
    assert c.get("/api/u/alice/portfolio").status_code == 404
    assert c.post("/api/login", json={"username": "alice"}).status_code in (404, 405)


def test_register_sets_secure_session_cookie(app):
    c = client(app)
    r = register(c, "alice")
    assert r.status_code == 200 and r.json() == {"username": "alice"}
    sc = r.headers["set-cookie"].lower()
    assert f"{COOKIE}=" in sc and "httponly" in sc and "samesite=lax" in sc and "max-age=604800" in sc
    me = c.get("/api/auth/me").json()
    assert me["username"] == "alice" and me["email"] == "alice@example.com" and me["has_password"] is True
    assert c.get("/").status_code == 200 and c.get("/login").status_code == 303
    bad = client(app)
    assert register(bad, "alice").status_code == 400                       # duplicate
    assert bad.post("/api/auth/register", json={"username": "bob", "password": "short",
                                                 "password_confirm": "short", "email": "bob@example.com"}).status_code == 400
    assert bad.post("/api/auth/register", json={"username": "bob", "password": PW,
                                                 "password_confirm": PW + "x", "email": "bob@example.com"}).status_code == 400
    assert bad.post("/api/auth/register", json={"username": "cara", "password": PW, "password_confirm": PW,
                                                 "email": "alice@example.com"}).status_code == 400


def test_login_logout_and_token_reuse(app):
    c = client(app)
    register(c, "alice")
    c.post("/api/auth/logout")
    assert c.get("/api/me/portfolio").status_code == 401
    assert c.post("/api/auth/login", json={"username": "alice", "password": "wrong-pass"}).status_code == 401
    assert c.post("/api/auth/login", json={"username": "ghost", "password": PW}).status_code == 401
    r = c.post("/api/auth/login", json={"username": "alice", "password": PW})
    assert r.status_code == 200
    token = c.cookies.get(COOKIE)
    assert c.get("/api/me/portfolio").status_code == 200
    c.post("/api/auth/logout")
    thief = client(app)
    thief.cookies.set(COOKIE, token)
    assert thief.get("/api/me/portfolio").status_code == 401             # logged-out token is dead


def test_lockout_via_api(app):
    c = client(app)
    register(c, "alice")
    c.post("/api/auth/logout")
    codes = [c.post("/api/auth/login", json={"username": "alice", "password": "wrong-pass"}).status_code
             for _ in range(6)]
    assert codes == [401, 401, 401, 401, 429, 429]
    assert c.post("/api/auth/login", json={"username": "alice", "password": PW}).status_code == 429


def test_buy_sell_flow_acts_on_logged_in_user_only(app):
    alice, bob = client(app), client(app)
    register(alice, "alice")
    register(bob, "bob")
    q = alice.get("/api/quote", params={"symbol": "700"}).json()
    assert q["symbol"] == "0700.HK" and q["lot_size"] == 100

    r = alice.post("/api/me/orders", json={"symbol": "0700.HK", "side": "BUY", "type": "MARKET", "qty": 300})
    assert r.status_code == 200 and r.json()["status"] == "FILLED"
    p = alice.get("/api/me/portfolio").json()
    assert p["username"] == "alice" and hkd(p)["cash"] == 880_000 and p["positions"][0]["qty"] == 300
    r = alice.post("/api/me/orders", json={"symbol": "0700.HK", "side": "SELL", "type": "MARKET", "qty": 100})
    assert r.json()["status"] == "FILLED"
    p = alice.get("/api/me/portfolio").json()
    assert hkd(p)["cash"] == 920_000 and p["positions"][0]["qty"] == 200
    assert len(alice.get("/api/me/trades").json()) == 2

    # bob sees only his own (empty) account and cannot touch alice's orders
    pb = bob.get("/api/me/portfolio").json()
    assert pb["username"] == "bob" and pb["positions"] == [] and hkd(pb)["cash"] == 1_000_000
    assert bob.get("/api/me/orders").json() == [] and bob.get("/api/me/trades").json() == []
    lim = alice.post("/api/me/orders", json={"symbol": "AAPL", "side": "BUY", "type": "LIMIT", "qty": 1,
                                              "limit_price": 1}).json()
    assert bob.post(f"/api/me/orders/{lim['id']}/cancel").status_code == 400
    assert alice.get("/api/me/orders", params={"status": "PENDING"}).json()[0]["id"] == lim["id"]
    # bob's reset does not affect alice; a username in the body is ignored
    bob.post("/api/me/reset")
    assert len(alice.get("/api/me/trades").json()) == 2
    r = bob.post("/api/me/orders", json={"symbol": "AAPL", "side": "SELL", "type": "MARKET", "qty": 1,
                                          "username": "alice"})
    assert r.status_code == 400   # bob holds no AAPL

    lb = alice.get("/api/leaderboard").json()
    assert {r["username"] for r in lb["rows"]} == {"alice", "bob"}

    assert alice.post("/api/me/reset").json()["ok"]
    assert alice.get("/api/me/portfolio").json()["positions"] == []


def test_change_password_api(app):
    c, other = client(app), client(app)
    register(c, "alice")
    other.post("/api/auth/login", json={"username": "alice", "password": PW})
    body = {"current_password": "wrong-pass", "new_password": "brand-new-pw", "new_password_confirm": "brand-new-pw"}
    assert c.post("/api/auth/change-password", json=body).status_code == 400
    body["current_password"] = PW
    assert c.post("/api/auth/change-password", json=body).status_code == 200
    assert c.get("/api/me/portfolio").status_code == 200                  # current session kept
    assert other.get("/api/me/portfolio").status_code == 401              # other sessions revoked
    c.post("/api/auth/logout")
    assert c.post("/api/auth/login", json={"username": "alice", "password": PW}).status_code == 401
    assert c.post("/api/auth/login", json={"username": "alice", "password": "brand-new-pw"}).status_code == 200


def test_cross_origin_write_rejected(app):
    c = client(app)
    register(c, "alice")
    r = c.post("/api/me/reset", headers={"Origin": "https://evil.example"})
    assert r.status_code == 403
    assert c.post("/api/me/reset", headers={"Origin": "http://testserver"}).status_code == 200


def test_history_ranges():
    app = create_app(db_path=":memory:", feed=SimFeed(), pending_interval=0)
    c = client(app)
    register(c, "alice")
    for r in ["1D", "5D", "1M", "6M", "1Y", "5Y"]:
        h = c.get("/api/history", params={"symbol": "AAPL", "range": r}).json()
        assert h["range"] == r and h["points"] and h["currency"] == "USD"
    assert c.get("/api/history", params={"symbol": "AAPL", "range": "2W"}).status_code == 400


def test_pages_served_after_login(app):
    c = client(app)
    register(c, "alice")
    r = c.get("/")
    assert r.status_code == 200 and "模擬股票交易平台" in r.text and "登出" in r.text
    assert c.get("/static/app.js").status_code == 200
