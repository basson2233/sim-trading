#!/usr/bin/env python3
"""Manual dual-client smoke for /api/fighter/room/ws (run against a live server).

Usage:
  uvicorn app.main:app --port 8000
  python scripts/smoke_fighter_room.py
"""
from __future__ import annotations

import json
import threading
import urllib.request

import httpx

BASE = "http://127.0.0.1:8000"
WS = "ws://127.0.0.1:8000/api/fighter/room/ws"
PW = "smoke-pass-1"


def register_or_login(client: httpx.Client, name: str) -> None:
    email = f"{name}@smoke.local"
    r = client.post(f"{BASE}/api/auth/register", json={
        "username": name, "password": PW, "password_confirm": PW, "email": email,
    })
    if r.status_code != 200:
        r = client.post(f"{BASE}/api/auth/login", json={"email": email, "password": PW})
        r.raise_for_status()


def main() -> None:
    try:
        import websockets  # type: ignore
    except ImportError:
        raise SystemExit("pip install websockets")

    host_c, guest_c = httpx.Client(), httpx.Client()
    register_or_login(host_c, "smoke_host")
    register_or_login(guest_c, "smoke_guest")

    async def run():
        import asyncio
        cookie_h = "; ".join(f"{k}={v}" for k, v in host_c.cookies.items())
        cookie_g = "; ".join(f"{k}={v}" for k, v in guest_c.cookies.items())
        async with websockets.connect(WS, additional_headers={"Cookie": cookie_h}) as ws_h, \
                websockets.connect(WS, additional_headers={"Cookie": cookie_g}) as ws_g:
            await ws_h.send(json.dumps({"type": "create", "mapId": "hkex"}))
            created = json.loads(await ws_h.recv())
            print("created", created)
            code = created["code"]
            await ws_g.send(json.dumps({"type": "join", "code": code}))
            print("host after join", json.loads(await ws_h.recv()))
            print("guest after join", json.loads(await ws_g.recv()))
            await ws_h.send(json.dumps({"type": "ready"}))
            print("ready1", json.loads(await ws_h.recv()), json.loads(await ws_g.recv()))
            await ws_g.send(json.dumps({"type": "ready"}))
            print("ready2h", json.loads(await ws_h.recv()))
            print("starth", json.loads(await ws_h.recv()))
            print("ready2g", json.loads(await ws_g.recv()))
            print("startg", json.loads(await ws_g.recv()))

    import asyncio
    asyncio.run(run())


if __name__ == "__main__":
    main()
