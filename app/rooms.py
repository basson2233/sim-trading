"""In-memory online matchmaking rooms for 理財戰士 (Finance Fighter).

Primary protocol is a single WebSocket at /api/fighter/room/ws
(client events: create / join / ready / start / leave). See
docs/fighter-online-api.md.

MVP store lives in process memory — fine for one Railway/uvicorn worker.
Multi-worker deploys need Redis (or similar) later.
"""
from __future__ import annotations

import secrets
import time
import uuid
from dataclasses import dataclass, field
from typing import Any, Optional

from fastapi import WebSocket

# Easy-to-type: no 0/O/1/I ambiguity.
_CODE_ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"
ROOM_CODE_LEN = 6
ROOM_TTL_SEC = 45 * 60  # 45 minutes of inactivity
MAX_PLAYERS = 2

STATUS_WAITING = "waiting"
STATUS_READY = "ready"
STATUS_FIGHTING = "fighting"
STATUS_CLOSED = "closed"


def _now() -> float:
    return time.time()


def _new_code() -> str:
    return "".join(secrets.choice(_CODE_ALPHABET) for _ in range(ROOM_CODE_LEN))


def public_fighter(stats: dict[str, Any]) -> dict[str, Any]:
    """Trim portfolio-derived stats to what the canvas client needs to beginFight."""
    return {
        "username": stats.get("username") or "?",
        "display_name": stats.get("display_name") or stats.get("username") or "?",
        "atk": float(stats.get("atk") or 100),
        "def": float(stats.get("def") or 100),
        "spd": float(stats.get("spd") or 100),
        "dominant": stats.get("dominant") or "cash",
        "character_id": stats.get("character_id") or "herta",
        "is_ai": bool(stats.get("is_ai", False)),
    }


@dataclass
class RoomPlayer:
    username: str
    ready: bool = False
    joined_at: float = field(default_factory=_now)
    websockets: set = field(default_factory=set)


@dataclass
class Room:
    room_id: str
    room_code: str
    host: str
    players: dict[str, RoomPlayer] = field(default_factory=dict)
    status: str = STATUS_WAITING
    map_id: Optional[str] = None
    is_public: bool = False
    created_at: float = field(default_factory=_now)
    last_activity: float = field(default_factory=_now)

    def touch(self) -> None:
        self.last_activity = _now()

    def guest_name(self) -> Optional[str]:
        for name in self.players:
            if name != self.host:
                return name
        return None

    def recompute_status(self) -> None:
        if self.status in (STATUS_FIGHTING, STATUS_CLOSED):
            return
        if len(self.players) == MAX_PLAYERS and all(p.ready for p in self.players.values()):
            self.status = STATUS_READY
        else:
            self.status = STATUS_WAITING

    def both_ready(self) -> bool:
        return (
            len(self.players) == MAX_PLAYERS
            and all(p.ready for p in self.players.values())
        )

    def _seat(self, username: Optional[str]) -> Optional[dict[str, Any]]:
        if not username or username not in self.players:
            return None
        p = self.players[username]
        return {
            "username": username,
            "display_name": username,
            "ready": p.ready,
        }

    def client_view(self, for_username: str) -> dict[str, Any]:
        """Shape expected by static/fighter.js RoomNet (type room/state)."""
        role = "host" if for_username == self.host else "guest"
        me = self.players.get(for_username)
        return {
            "type": "room",
            "code": self.room_code,
            "room_code": self.room_code,
            "room_id": self.room_id,
            "role": role,
            "status": self.status,
            "host": self._seat(self.host),
            "guest": self._seat(self.guest_name()),
            "mapId": self.map_id,
            "map_id": self.map_id,
            "public": self.is_public,
            "you_ready": bool(me.ready) if me else False,
        }

    def list_item(self) -> dict[str, Any]:
        """Public lobby row (HTTP list + WS type rooms)."""
        return {
            "code": self.room_code,
            "room_code": self.room_code,
            "host": {
                "username": self.host,
                "display_name": self.host,
            },
            "mapId": self.map_id,
            "map_id": self.map_id,
            "players": len(self.players),
            "status": self.status,
        }

    def ready_view(self, for_username: str) -> dict[str, Any]:
        view = self.client_view(for_username)
        view["type"] = "ready"
        return view


class RoomStore:
    """Process-local room registry + WebSocket fan-out."""

    def __init__(self, ttl_sec: int = ROOM_TTL_SEC):
        self._rooms_by_code: dict[str, Room] = {}
        self._rooms_by_id: dict[str, Room] = {}
        self._ttl = ttl_sec

    def purge_expired(self) -> None:
        cutoff = _now() - self._ttl
        dead = [
            c for c, r in self._rooms_by_code.items()
            if r.status == STATUS_CLOSED or r.last_activity < cutoff or not r.players
        ]
        for code in dead:
            room = self._rooms_by_code.pop(code, None)
            if room:
                room.status = STATUS_CLOSED
                self._rooms_by_id.pop(room.room_id, None)

    def get(self, room_code: str) -> Optional[Room]:
        self.purge_expired()
        code = (room_code or "").strip().upper()
        room = self._rooms_by_code.get(code)
        if room and room.status == STATUS_CLOSED:
            return None
        return room

    def create(self, host_username: str, map_id: Optional[str] = None,
               public: bool = False) -> Room:
        self.purge_expired()
        self._leave_all(host_username)
        for _ in range(32):
            code = _new_code()
            if code not in self._rooms_by_code:
                break
        else:
            raise RuntimeError("無法產生房間碼")
        room = Room(
            room_id=str(uuid.uuid4()),
            room_code=code,
            host=host_username,
            map_id=map_id or None,
            is_public=bool(public),
        )
        room.players[host_username] = RoomPlayer(username=host_username)
        self._rooms_by_code[code] = room
        self._rooms_by_id[room.room_id] = room
        return room

    def join(self, room_code: str, username: str) -> Room:
        room = self.get(room_code)
        if not room:
            raise LookupError("房間不存在或已過期")
        if room.status == STATUS_FIGHTING:
            raise ValueError("對戰已開始，無法加入")
        if room.status == STATUS_CLOSED:
            raise LookupError("房間已關閉")
        if username in room.players:
            room.touch()
            return room
        if len(room.players) >= MAX_PLAYERS:
            raise ValueError("房間已滿（最多 2 人）")
        if username == room.host:
            room.touch()
            return room
        self._leave_all(username)
        room.players[username] = RoomPlayer(username=username)
        room.recompute_status()
        room.touch()
        return room

    def set_ready(self, room_code: str, username: str, ready: bool = True) -> Room:
        room = self._require_member(room_code, username)
        if room.status == STATUS_FIGHTING:
            raise ValueError("對戰進行中，無法改 ready")
        room.players[username].ready = bool(ready)
        room.recompute_status()
        room.touch()
        return room

    def leave(self, room_code: str, username: str) -> Optional[Room]:
        room = self.get(room_code)
        if not room or username not in room.players:
            return None
        player = room.players.pop(username)
        player.websockets.clear()
        if not room.players:
            room.status = STATUS_CLOSED
            self._rooms_by_code.pop(room.room_code, None)
            self._rooms_by_id.pop(room.room_id, None)
            return None
        if room.host == username:
            room.host = next(iter(room.players))
        for p in room.players.values():
            p.ready = False
        if room.status == STATUS_FIGHTING:
            room.status = STATUS_WAITING
        else:
            room.recompute_status()
        room.touch()
        return room

    def list_public(self) -> list[dict[str, Any]]:
        """Joinable public lobbies: waiting and not full."""
        self.purge_expired()
        rows = []
        for room in self._rooms_by_code.values():
            if not room.is_public:
                continue
            if room.status != STATUS_WAITING:
                continue
            if len(room.players) >= MAX_PLAYERS:
                continue
            if not room.players:
                continue
            rows.append((room.created_at, room.list_item()))
        rows.sort(key=lambda x: x[0], reverse=True)
        return [item for _, item in rows]

    def mark_fighting(self, room: Room, map_id: Optional[str] = None) -> None:
        room.status = STATUS_FIGHTING
        if map_id:
            room.map_id = map_id
        room.touch()

    def attach_ws(self, room: Room, username: str, ws: WebSocket) -> None:
        player = room.players.get(username)
        if not player:
            raise LookupError("你唔喺呢個房間")
        player.websockets.add(ws)
        room.touch()

    def detach_ws(self, room: Room, username: str, ws: WebSocket) -> None:
        player = room.players.get(username)
        if player:
            player.websockets.discard(ws)
            room.touch()

    async def broadcast_views(self, room: Room, kind: str = "room") -> None:
        """Send a personalized room/ready view to every connected seat."""
        dead: list[tuple[str, WebSocket]] = []
        for name, player in list(room.players.items()):
            payload = room.ready_view(name) if kind == "ready" else room.client_view(name)
            for ws in list(player.websockets):
                try:
                    await ws.send_json(payload)
                except Exception:
                    dead.append((name, ws))
        for name, ws in dead:
            self.detach_ws(room, name, ws)

    async def send_json(self, room: Room, username: str, message: dict[str, Any]) -> None:
        player = room.players.get(username)
        if not player:
            return
        dead = []
        for ws in list(player.websockets):
            try:
                await ws.send_json(message)
            except Exception:
                dead.append(ws)
        for ws in dead:
            player.websockets.discard(ws)

    def _require_member(self, room_code: str, username: str) -> Room:
        room = self.get(room_code)
        if not room:
            raise LookupError("房間不存在或已過期")
        if username not in room.players:
            raise PermissionError("你唔喺呢個房間")
        return room

    def _leave_all(self, username: str) -> None:
        for code in list(self._rooms_by_code.keys()):
            room = self._rooms_by_code.get(code)
            if not room or username not in room.players:
                continue
            if room.status == STATUS_FIGHTING:
                continue
            self.leave(code, username)


store = RoomStore()
