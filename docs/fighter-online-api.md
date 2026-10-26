# 理財戰士 — Online room API (for lobby UI)

Primary transport is **one WebSocket**. The lobby in `static/fighter.js` (`RoomNet`) already speaks this protocol.

> In-memory rooms: OK on a single Railway/uvicorn worker. Multi-worker needs Redis later.

## Endpoint

```
WS  /api/fighter/room/ws
```

- Requires the normal session cookie (`sim_session`), same as other `/api/fighter/*` routes.
- Use `wss://` on HTTPS hosts (Railway).
- Unauthenticated connections are closed with code `4401`.

AI practice and local classmate match (`POST /api/fighter/match`) are unchanged.

## Client → server

All messages are JSON objects with a `type` field.

### `create`

Create a room; sender becomes **host**. Optional map from the lobby picker.

```json
{ "type": "create", "mapId": "hkex", "map_id": "hkex" }
```

### `join`

Join an existing room by 6-character code (A–Z / 2–9; ambiguous `0O1I` avoided).

```json
{ "type": "join", "code": "AB3K7Q", "room_code": "AB3K7Q" }
```

Either `code` or `room_code` is accepted.

### `ready` / `unready`

```json
{ "type": "ready" }
{ "type": "ready", "ready": false }
{ "type": "unready" }
```

When **both** seats are ready, the server **auto-starts** the match (lobby has no Start button).

### `start` (optional, host only)

Host may force start once both are ready (same payload as auto-start). Optional map override:

```json
{ "type": "start", "mapId": "vault" }
```

### `leave`

```json
{ "type": "leave" }
```

### `ping`

```json
{ "type": "ping" }
```

→ `{ "type": "pong" }`

### `input` (stub)

Reserved for future input sync. Server replies `{ "type": "input_ack" }` only.

## Server → client

### `room` (also accepted by UI as `state`)

Sent after create/join and whenever membership changes.

```json
{
  "type": "room",
  "code": "AB3K7Q",
  "room_code": "AB3K7Q",
  "room_id": "uuid…",
  "role": "host",
  "status": "waiting",
  "host": { "username": "alice", "display_name": "alice", "ready": false },
  "guest": null,
  "mapId": "hkex",
  "map_id": "hkex",
  "you_ready": false
}
```

`status`: `waiting` | `ready` | `fighting` | `closed`  
`role`: `host` | `guest`  
`guest` is `null` until a second player joins.

### `ready`

Same shape as `room`, but `"type": "ready"`. Broadcast after any ready change.

### `start`

Personalized per connection — `player` is **you**, `opponent` is the other seat. Stats match `compute_fighter_stats` / classmate match.

```json
{
  "type": "start",
  "player": {
    "username": "alice",
    "display_name": "alice",
    "atk": 103.0,
    "def": 100.0,
    "spd": 100.0,
    "dominant": "atk",
    "character_id": "herta",
    "is_ai": false
  },
  "opponent": {
    "username": "bob",
    "display_name": "bob",
    "atk": 100.0,
    "def": 104.0,
    "spd": 100.0,
    "dominant": "def",
    "character_id": "herta",
    "is_ai": false
  },
  "mapId": "hkex",
  "map_id": "hkex",
  "code": "AB3K7Q",
  "room_code": "AB3K7Q",
  "role": "host",
  "mode": "online"
}
```

Frontend should call `showArena` / `beginFight` like classmate mode (`mode: "online"`).

### `error`

```json
{ "type": "error", "message": "房間不存在或已過期" }
```

## Room rules

| Rule | Value |
|------|--------|
| Code length | 6 |
| Alphabet | `A–Z` without `I/O`, digits `2–9` (no `0/1`) |
| Max players | 2 |
| Host | Creator; if host leaves, the remaining player is promoted |
| TTL | ~45 minutes idle, or closed when empty |
| Stats | Live portfolio snapshot at `start` (same as `/api/fighter/match`) |

## History

`POST /api/fighter/result` accepts `mode: "online"` in addition to `ai` / `classmate`.

## Local smoke test

```bash
# terminal 1
cd /workspace/sim-trading && .venv/bin/uvicorn app.main:app --reload --port 8000

# pytest (uses TestClient WebSocket)
.venv/bin/pytest tests/test_fighter_rooms.py -q
```

Manual: open two browsers (two logged-in users) → 建立房間 / 輸入房間碼 → 準備就緒 → fight starts.
