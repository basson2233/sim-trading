"""Admin API: delete-by-id + room purge + auth gate."""
import pytest
from fastapi.testclient import TestClient

from app.main import create_app
from app.rooms import RoomStore, STATUS_FIGHTING

PW = "secret-pass-1"
ADMIN_KEY = "test-admin-key-please-change"


@pytest.fixture
def app(feed, monkeypatch):
    monkeypatch.setenv("ADMIN_API_KEY", ADMIN_KEY)
    return create_app(db_path=":memory:", feed=feed, pending_interval=0)


@pytest.fixture
def app_no_key(feed, monkeypatch):
    monkeypatch.delenv("ADMIN_API_KEY", raising=False)
    monkeypatch.setenv("ADMIN_API_KEY", "")
    return create_app(db_path=":memory:", feed=feed, pending_interval=0)


def client(app):
    return TestClient(app, follow_redirects=False)


def register(c, name, pw=PW, email=None):
    return c.post("/api/auth/register", json={
        "username": name, "password": pw, "password_confirm": pw,
        "email": email or f"{name}@example.com",
    })


def admin_headers(key=ADMIN_KEY):
    return {"X-Admin-Key": key}


def _user_id(app, username):
    eng = app.state.engine
    row = eng.db.execute("SELECT id FROM users WHERE username = ?", (username,)).fetchone()
    assert row is not None
    return row["id"]


def test_admin_disabled_without_key(app_no_key):
    c = client(app_no_key)
    register(c, "alice")
    uid = _user_id(app_no_key, "alice")
    r = c.delete(f"/api/admin/users/{uid}", headers=admin_headers("anything"))
    assert r.status_code == 503
    assert "admin disabled" in r.json()["detail"]
    r2 = c.get(f"/api/admin/users/{uid}", headers=admin_headers("anything"))
    assert r2.status_code == 503


def test_admin_wrong_key_rejected(app):
    c = client(app)
    register(c, "alice")
    uid = _user_id(app, "alice")
    for method, path in (("get", f"/api/admin/users/{uid}"),
                         ("delete", f"/api/admin/users/{uid}")):
        r = getattr(c, method)(path, headers=admin_headers("wrong-key"))
        assert r.status_code == 401, path
    r = c.delete(f"/api/admin/users/{uid}")  # no header
    assert r.status_code == 401


def test_admin_get_user_privacy(app):
    c = client(app)
    register(c, "alice")
    uid = _user_id(app, "alice")
    r = c.get(f"/api/admin/users/{uid}", headers=admin_headers())
    assert r.status_code == 200
    body = r.json()
    assert body["id"] == uid
    assert body["username"] == "alice"
    assert body["has_email"] is True
    assert body["has_google"] is False
    assert "email" not in body
    assert "password" not in body
    assert "password_hash" not in body
    assert "google_sub" not in body
    assert c.get("/api/admin/users/999999", headers=admin_headers()).status_code == 404


def test_admin_delete_wipes_related_rows(app):
    c = client(app)
    register(c, "alice")
    uid = _user_id(app, "alice")
    eng = app.state.engine

    # Seed related rows via normal trading flow
    assert c.post("/api/me/orders", json={
        "symbol": "AAPL", "side": "BUY", "type": "MARKET", "qty": 10,
    }).status_code == 200
    # Limit order that stays pending
    assert c.post("/api/me/orders", json={
        "symbol": "TSLA", "side": "BUY", "type": "LIMIT", "qty": 1, "limit_price": 1.0,
    }).status_code == 200
    with eng._tx() as db:
        db.execute(
            "INSERT INTO fighter_matches(mode,player_username,opponent_username,winner,created_at) "
            "VALUES (?,?,?,?,?)",
            ("ai", "alice", "bot", "alice", 1.0),
        )

    assert eng.db.execute("SELECT COUNT(*) AS n FROM positions WHERE user_id=?", (uid,)).fetchone()["n"] >= 1
    assert eng.db.execute("SELECT COUNT(*) AS n FROM orders WHERE user_id=?", (uid,)).fetchone()["n"] >= 1
    assert eng.db.execute("SELECT COUNT(*) AS n FROM trades WHERE user_id=?", (uid,)).fetchone()["n"] >= 1
    assert eng.db.execute("SELECT COUNT(*) AS n FROM cash WHERE user_id=?", (uid,)).fetchone()["n"] >= 1
    assert eng.db.execute("SELECT COUNT(*) AS n FROM sessions WHERE user_id=?", (uid,)).fetchone()["n"] >= 1
    assert eng.db.execute(
        "SELECT COUNT(*) AS n FROM fighter_matches WHERE player_username=? OR opponent_username=?",
        ("alice", "alice"),
    ).fetchone()["n"] >= 1

    r = c.delete(f"/api/admin/users/{uid}", headers=admin_headers())
    assert r.status_code == 200
    body = r.json()
    assert body == {"ok": True, "id": uid, "username": "alice", "deleted": True}

    assert eng.db.execute("SELECT 1 FROM users WHERE id=?", (uid,)).fetchone() is None
    for table in ("positions", "orders", "trades", "cash", "sessions", "password_resets"):
        n = eng.db.execute(f"SELECT COUNT(*) AS n FROM {table} WHERE user_id=?", (uid,)).fetchone()["n"]
        assert n == 0, table
    assert eng.db.execute(
        "SELECT COUNT(*) AS n FROM fighter_matches WHERE player_username=? OR opponent_username=?",
        ("alice", "alice"),
    ).fetchone()["n"] == 0

    # Second delete → 404
    r2 = c.delete(f"/api/admin/users/{uid}", headers=admin_headers())
    assert r2.status_code == 404


def test_room_purge_removes_user(app):
    store = RoomStore()
    room = store.create("alice", map_id="hkex", public=True)
    store.join(room.room_code, "bob")
    code = room.room_code

    sockets, remaining = store.purge_user("alice")
    assert sockets == []
    assert store.get(code) is not None  # bob remains
    assert "alice" not in store.get(code).players
    assert store.get(code).host == "bob"
    assert len(remaining) == 1

    # Purge last member → room gone
    sockets2, remaining2 = store.purge_user("bob")
    assert store.get(code) is None
    assert remaining2 == []

    # Fighting room also purged
    r2 = store.create("carol")
    store.join(r2.room_code, "dave")
    store.mark_fighting(r2)
    assert r2.status == STATUS_FIGHTING
    store.purge_user("carol")
    left = store.get(r2.room_code)
    assert left is not None
    assert "carol" not in left.players
    assert left.host == "dave"


def test_admin_delete_purges_room_membership(app):
    c = client(app)
    register(c, "alice")
    register(client(app), "bob")  # separate client so alice session stays
    # bob on same app via engine create isn't logged in — just need alice in a room
    uid = _user_id(app, "alice")
    rooms = app.state.rooms
    room = rooms.create("alice")
    rooms.join(room.room_code, "bob")
    code = room.room_code
    assert "alice" in rooms.get(code).players

    r = c.delete(f"/api/admin/users/{uid}", headers=admin_headers())
    assert r.status_code == 200
    left = rooms.get(code)
    assert left is not None
    assert "alice" not in left.players
    assert left.host == "bob"
