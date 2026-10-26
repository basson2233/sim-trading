"""Online room store + WebSocket smoke tests."""
import pytest
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from app.main import create_app
from app.rooms import ROOM_CODE_LEN, RoomStore, public_fighter

PW = "secret-pass-1"


def client(app):
    return TestClient(app, follow_redirects=False)


def register(c, name, pw=PW, email=None):
    return c.post("/api/auth/register", json={
        "username": name, "password": pw, "password_confirm": pw,
        "email": email or f"{name}@example.com",
    })


def test_public_fighter_shape():
    out = public_fighter({"username": "a", "atk": 101, "def": 102, "spd": 103, "dominant": "atk"})
    assert out["character_id"] == "herta"
    assert out["atk"] == 101.0
    assert out["is_ai"] is False


def test_room_store_create_join_ready_leave():
    store = RoomStore()
    r = store.create("alice", map_id="hkex")
    assert len(r.room_code) == ROOM_CODE_LEN
    assert r.host == "alice"
    assert r.status == "waiting"
    view = r.client_view("alice")
    assert view["type"] == "room"
    assert view["role"] == "host"
    assert view["guest"] is None
    assert view["mapId"] == "hkex"
    assert view["code"] == r.room_code

    r2 = store.join(r.room_code, "bob")
    assert r2.guest_name() == "bob"
    assert r2.client_view("bob")["role"] == "guest"
    assert r2.client_view("bob")["guest"]["username"] == "bob"

    store.set_ready(r.room_code, "alice", True)
    store.set_ready(r.room_code, "bob", True)
    assert r2.both_ready()
    assert r2.status == "ready"
    ready = r2.ready_view("alice")
    assert ready["type"] == "ready"
    assert ready["you_ready"] is True

    # Guest leaves → host remains, status waiting, ready cleared
    left = store.leave(r.room_code, "bob")
    assert left is not None
    assert left.guest_name() is None
    assert left.status == "waiting"
    assert left.players["alice"].ready is False

    # Host leaves → room closed
    assert store.leave(r.room_code, "alice") is None
    assert store.get(r.room_code) is None


def test_room_store_rejects_third_player():
    store = RoomStore()
    r = store.create("alice")
    store.join(r.room_code, "bob")
    with pytest.raises(ValueError, match="已滿"):
        store.join(r.room_code, "carol")


def test_ws_create_ready_leave_ping(feed):
    """Single-socket smoke: create → ready → ping → leave (dual-client needs real browsers)."""
    app = create_app(db_path=":memory:", feed=feed, pending_interval=0)
    c = client(app)
    assert register(c, "alice").status_code == 200

    with c.websocket_connect("/api/fighter/room/ws") as ws:
        ws.send_json({"type": "create", "mapId": "vault", "map_id": "vault"})
        created = ws.receive_json()
        assert created["type"] == "room"
        assert created["role"] == "host"
        assert created["status"] == "waiting"
        assert created["host"]["username"] == "alice"
        assert created["guest"] is None
        assert created["mapId"] == "vault"
        assert len(created["code"]) == ROOM_CODE_LEN

        ws.send_json({"type": "ready"})
        ready = ws.receive_json()
        assert ready["type"] == "ready"
        assert ready["you_ready"] is True
        assert ready["host"]["ready"] is True
        # Alone → not both ready, no start
        assert ready["status"] == "waiting"

        ws.send_json({"type": "ping"})
        assert ws.receive_json()["type"] == "pong"

        ws.send_json({"type": "leave"})
        closed = ws.receive_json()
        assert closed["type"] == "room"
        assert closed.get("status") == "closed"


def test_ws_join_missing_room(feed):
    app = create_app(db_path=":memory:", feed=feed, pending_interval=0)
    c = client(app)
    register(c, "bob")
    with c.websocket_connect("/api/fighter/room/ws") as ws:
        ws.send_json({"type": "join", "code": "ZZZZZZ"})
        err = ws.receive_json()
        assert err["type"] == "error"
        assert "不存在" in err["message"] or "過期" in err["message"]


def test_ws_requires_auth(feed):
    app = create_app(db_path=":memory:", feed=feed, pending_interval=0)
    c = client(app)
    with pytest.raises(WebSocketDisconnect):
        with c.websocket_connect("/api/fighter/room/ws") as ws:
            ws.receive_json()


def test_fighter_result_accepts_online(feed):
    app = create_app(db_path=":memory:", feed=feed, pending_interval=0)
    c = client(app)
    register(c, "alice")
    r = c.post("/api/fighter/result", json={
        "mode": "online", "opponent_username": "bob", "winner": "player",
        "player_kos": 2, "opponent_kos": 0,
    })
    assert r.status_code == 200 and r.json()["ok"] is True
