"""Forgot-password and Google sign-in. Google's HTTP is mocked; nothing is called for real."""
import time
from urllib.parse import parse_qs, urlparse

import pytest
from fastapi.testclient import TestClient

from app.auth import FORGOT_MESSAGE, GoogleOAuth, AuthService
from app.engine import Engine
from app.main import create_app

PW = "correct-horse-1"


class Resp:
    def __init__(self, payload, status=200):
        self._p, self.status_code = payload, status

    def json(self):
        return self._p


class FakeGoogleHTTP:
    def __init__(self, userinfo, token_status=200):
        self.userinfo = userinfo
        self.token_status = token_status
        self.posts, self.gets = [], []

    def post(self, url, data=None, timeout=None):
        self.posts.append((url, dict(data or {})))
        if self.token_status != 200:
            return Resp({"error": "invalid_grant"}, self.token_status)
        return Resp({"access_token": "tok-1", "token_type": "Bearer"})

    def get(self, url, headers=None, timeout=None):
        self.gets.append((url, dict(headers or {})))
        assert headers["Authorization"] == "Bearer tok-1"
        return Resp(self.userinfo)


def make_app(feed, tmp_path, *, google=None, dev=False):
    return create_app(db_path=":memory:", feed=feed, pending_interval=0, google=google,
                      dev_show_reset=dev, smtp=None, base_url="http://localhost:8000",
                      reset_log=tmp_path / "password-resets.log")


def client(app):
    return TestClient(app, follow_redirects=False)


def register(c, name="alice", email="alice@example.com", pw=PW):
    r = c.post("/api/auth/register", json={"username": name, "password": pw, "password_confirm": pw, "email": email})
    assert r.status_code == 200, r.text
    return r


# ---------------------------------------------------------------- forgot password
def test_forgot_is_generic_for_known_unknown_and_google_only(feed, tmp_path):
    app = make_app(feed, tmp_path, dev=True)
    c = client(app)
    register(c, "alice", "alice@example.com")
    # Google-only account
    app.state.engine.create_user("gwen", None, email="gwen@example.com", email_verified=1, google_sub="gsub-gwen")

    known = c.post("/api/auth/forgot", json={"email": "Alice@Example.com"}).json()
    unknown = c.post("/api/auth/forgot", json={"email": "nobody@example.com"}).json()
    google_only = c.post("/api/auth/forgot", json={"email": "gwen@example.com"}).json()
    assert known["message"] == unknown["message"] == google_only["message"] == FORGOT_MESSAGE
    assert "reset_url" in known and "/reset?token=" in known["reset_url"]
    assert "reset_url" not in unknown and "reset_url" not in google_only
    log = (tmp_path / "password-resets.log").read_text()
    assert known["reset_url"] in log and "nobody@example.com" not in log and "gwen@example.com" not in log
    # no email stored for a password-less legacy row: still generic, no link
    app.state.engine.db.execute(
        "INSERT INTO users(username, password_hash, created_at, reset_at) VALUES ('nomail', 'x', 0, 0)")
    nomail = c.post("/api/auth/forgot", json={"email": "missing@example.com"}).json()
    assert nomail["message"] == FORGOT_MESSAGE and "reset_url" not in nomail


def test_dev_flag_off_never_returns_the_link(feed, tmp_path):
    app = make_app(feed, tmp_path, dev=False)
    c = client(app)
    register(c)
    body = c.post("/api/auth/forgot", json={"email": "alice@example.com"}).json()
    assert body == {"message": FORGOT_MESSAGE}
    assert "reset?token=" in (tmp_path / "password-resets.log").read_text()


def test_reset_single_use_expiry_kills_sessions_and_email_unique(feed, tmp_path):
    app = make_app(feed, tmp_path, dev=True)
    c = client(app)
    other = client(app)
    register(c)
    other.post("/api/auth/login", json={"username": "alice", "password": PW})
    assert c.get("/api/me/portfolio").status_code == 200
    url = c.post("/api/auth/forgot", json={"email": "alice@example.com"}).json()["reset_url"]
    token = parse_qs(urlparse(url).query)["token"][0]

    short = c.post("/api/auth/reset", json={"token": token, "password": "short", "password_confirm": "short"})
    assert short.status_code == 400
    bad = c.post("/api/auth/reset", json={"token": "forged-token", "password": "brand-new-pw",
                                          "password_confirm": "brand-new-pw"})
    assert bad.status_code == 400

    ok = c.post("/api/auth/reset", json={"token": token, "password": "brand-new-pw",
                                         "password_confirm": "brand-new-pw"})
    assert ok.status_code == 200
    # single use
    again = c.post("/api/auth/reset", json={"token": token, "password": "another-pw-1",
                                            "password_confirm": "another-pw-1"})
    assert again.status_code == 400
    # every existing session is dead; old password fails; new one works
    assert c.get("/api/me/portfolio").status_code == 401
    assert other.get("/api/me/portfolio").status_code == 401
    assert c.post("/api/auth/login", json={"username": "alice", "password": PW}).status_code == 401
    assert c.post("/api/auth/login", json={"username": "alice", "password": "brand-new-pw"}).status_code == 200

    # expiry
    url2 = c.post("/api/auth/forgot", json={"email": "alice@example.com"}).json()["reset_url"]
    token2 = parse_qs(urlparse(url2).query)["token"][0]
    from app.auth import _token_hash
    app.state.engine.db.execute("UPDATE password_resets SET expires_at=? WHERE token_hash=?",
                                (time.time() - 1, _token_hash(token2)))
    expired = c.post("/api/auth/reset", json={"token": token2, "password": "newer-pass-1",
                                              "password_confirm": "newer-pass-1"})
    assert expired.status_code == 400

    # email uniqueness is case-insensitive
    dup = c.post("/api/auth/register", json={"username": "bob", "password": PW, "password_confirm": PW,
                                             "email": "ALICE@example.com"})
    assert dup.status_code == 400 and "電郵" in dup.json()["detail"]
    assert c.post("/api/auth/change-email", json={"current_password": "brand-new-pw",
                                                  "email": "alice.new@example.com"}).status_code == 200
    assert c.get("/api/auth/me").json()["email"] == "alice.new@example.com"


def test_google_only_reset_starts_working_after_password_is_set(feed, tmp_path):
    app = make_app(feed, tmp_path, dev=True)
    app.state.engine.create_user("gwen", None, email="gwen@example.com", email_verified=1, google_sub="gsub-gwen")
    # give her a session the way Google login would
    c = client(app)
    token = app.state.auth.create_session(
        app.state.engine.db.execute("SELECT id FROM users WHERE username='gwen'").fetchone()["id"])
    c.cookies.set("sim_session", token)
    assert c.post("/api/auth/forgot", json={"email": "gwen@example.com"}).json().get("reset_url") is None
    assert c.post("/api/auth/change-email", json={"current_password": "x", "email": "a@b.co"}).status_code == 400
    r = c.post("/api/auth/change-password", json={"new_password": "gwen-pass-1", "new_password_confirm": "gwen-pass-1"})
    assert r.status_code == 200 and c.get("/api/auth/me").json()["has_password"] is True
    # now forgot-password issues a token, and the password is required to change it again
    assert "reset_url" in c.post("/api/auth/forgot", json={"email": "gwen@example.com"}).json()
    assert c.post("/api/auth/change-password", json={"new_password": "gwen-pass-2",
                                                     "new_password_confirm": "gwen-pass-2"}).status_code == 400


def test_schema_upgrade_keeps_password_users(tmp_path, feed):
    import sqlite3
    db = tmp_path / "old.db"
    con = sqlite3.connect(db)
    con.executescript("""
        CREATE TABLE users (id INTEGER PRIMARY KEY AUTOINCREMENT, username TEXT NOT NULL UNIQUE COLLATE NOCASE,
            password_hash TEXT, failed_logins INTEGER NOT NULL DEFAULT 0, locked_until REAL NOT NULL DEFAULT 0,
            created_at REAL NOT NULL, reset_at REAL NOT NULL);
        INSERT INTO users(username, password_hash, created_at, reset_at) VALUES ('demo', 'scrypt$kept', 0, 0);
    """)
    con.commit(); con.close()
    eng = Engine(str(db), feed)
    removed = AuthService(eng).migrate_legacy_users()
    assert removed == [] and eng.list_users() == ["demo"]
    cols = {r[1] for r in eng.db.execute("PRAGMA table_info(users)")}
    assert {"email", "email_verified", "google_sub"} <= cols


# ---------------------------------------------------------------- Google
def test_google_button_hidden_when_client_id_missing():
    assert GoogleOAuth("", "", "http://localhost:8000").enabled is False
    assert GoogleOAuth("  ", "secret", "http://localhost:8000").enabled is False
    g = GoogleOAuth("client-id", "secret", "http://localhost:8000")
    assert g.enabled is True
    assert g.redirect_uri == "http://localhost:8000/auth/google/callback"


def test_providers_and_start_when_disabled(feed, tmp_path):
    app = make_app(feed, tmp_path, google=GoogleOAuth("", "", "http://localhost:8000"))
    c = client(app)
    assert c.get("/api/auth/providers").json() == {"google": False}
    html = c.get("/login").text
    assert 'class="btn ghost big google-btn hidden"' in html and "用 Google 登入" in html
    r = c.get("/auth/google/start")
    assert r.status_code == 400 and "GOOGLE_CLIENT_ID" in r.json()["detail"]


def _callback(c, app, http):
    start = c.get("/auth/google/start")
    assert start.status_code == 302 and "accounts.google.com" in start.headers["location"]
    qs = parse_qs(urlparse(start.headers["location"]).query)
    assert qs["redirect_uri"] == ["http://localhost:8000/auth/google/callback"]
    assert qs["client_id"] == [app.state.google.client_id]
    state = qs["state"][0]
    return c.get("/auth/google/callback", params={"code": "auth-code", "state": state}), state


def test_google_state_mismatch_rejected(feed, tmp_path):
    http = FakeGoogleHTTP({"sub": "s", "email": "a@b.co", "email_verified": True})
    g = GoogleOAuth("cid", "sec", "http://localhost:8000", http=http)
    app = make_app(feed, tmp_path, google=g)
    app.state.google = g
    c = client(app)
    c.get("/auth/google/start")
    r = c.get("/auth/google/callback", params={"code": "auth-code", "state": "not-the-state"})
    assert r.status_code == 401 and "state" in r.json()["detail"]
    assert http.posts == []          # rejected before any call to Google
    assert "sim_session" not in c.cookies


def test_google_links_verified_email_and_rejects_unverified(feed, tmp_path):
    http = FakeGoogleHTTP({"sub": "gsub-1", "email": "Alice@Example.com", "email_verified": True})
    g = GoogleOAuth("cid", "sec", "http://localhost:8000", http=http)
    app = make_app(feed, tmp_path, google=g)
    app.state.google = g
    c = client(app)
    register(c, "alice", "alice@example.com")
    c.post("/api/auth/logout")
    r, state = _callback(c, app, http)
    assert r.status_code == 303 and r.headers["location"] == "/"
    me = c.get("/api/auth/me").json()
    assert me["username"] == "alice" and me["google"] is True and me["has_password"] is True
    assert http.posts[0][1]["grant_type"] == "authorization_code"
    assert http.posts[0][1]["code"] == "auth-code"
    # state is single use
    again = c.get("/auth/google/callback", params={"code": "auth-code", "state": state})
    assert again.status_code == 401

    # a different Google account with the same email but unverified must NOT take it over
    http2 = FakeGoogleHTTP({"sub": "gsub-2", "email": "alice@example.com", "email_verified": False})
    g2 = GoogleOAuth("cid", "sec", "http://localhost:8000", http=http2)
    app2 = make_app(feed, tmp_path, google=g2)  # fresh db
    # rebuild on same app's db instead:
    c2 = client(app)
    # swap the google client on the running app
    app.state.google = GoogleOAuth("cid", "sec", "http://localhost:8000", http=http2)
    # the route closure captured `google` local variable, NOT app.state.google.
    # So this swap does nothing. Test unverified on a fresh app instead.
    app3 = make_app(feed, tmp_path, google=GoogleOAuth("cid", "sec", "http://localhost:8000", http=http2))
    c3 = client(app3)
    register(c3, "alice", "alice@example.com")
    c3.post("/api/auth/logout")
    start = c3.get("/auth/google/start")
    st = parse_qs(urlparse(start.headers["location"]).query)["state"][0]
    denied = c3.get("/auth/google/callback", params={"code": "x", "state": st})
    assert denied.status_code == 400 and "未驗證" in denied.json()["detail"]
    # alice is unchanged: still no google link, password login still works
    assert c3.post("/api/auth/login", json={"username": "alice", "password": PW}).status_code == 200
    assert c3.get("/api/auth/me").json()["google"] is False


def test_google_creates_new_user(feed, tmp_path):
    http = FakeGoogleHTTP({"sub": "gsub-new", "email": "New.Person@example.com", "email_verified": True})
    g = GoogleOAuth("cid", "sec", "http://localhost:8000", http=http)
    app = make_app(feed, tmp_path, google=g)
    c = client(app)
    # username taken, so the derived name must be made unique
    register(c, "newperson", "someoneelse@example.com")
    c.post("/api/auth/logout")
    start = c.get("/auth/google/start")
    st = parse_qs(urlparse(start.headers["location"]).query)["state"][0]
    r = c.get("/auth/google/callback", params={"code": "the-code", "state": st})
    assert r.status_code == 303
    me = c.get("/api/auth/me").json()
    assert me["username"] == "newperson2" and me["email"] == "new.person@example.com"
    assert me["has_password"] is False and me["google"] is True and me["email_verified"] is True
    p = c.get("/api/me/portfolio").json()
    assert next(a for a in p["accounts"] if a["currency"] == "HKD")["cash"] == 1_000_000
    assert next(a for a in p["accounts"] if a["currency"] == "USD")["cash"] == 100_000
    # signing in again with the same sub logs into the same account (no second user)
    c.post("/api/auth/logout")
    start = c.get("/auth/google/start")
    st = parse_qs(urlparse(start.headers["location"]).query)["state"][0]
    assert c.get("/auth/google/callback", params={"code": "the-code", "state": st}).status_code == 303
    assert c.get("/api/auth/me").json()["username"] == "newperson2"
    assert app.state.engine.list_users().count("newperson2") == 1
