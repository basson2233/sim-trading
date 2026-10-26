"""FastAPI app: JSON API under /api (auth required), login/register pages, trading SPA at /."""
import asyncio
import hmac
import logging
import os
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Optional
from urllib.parse import urlsplit

from fastapi import BackgroundTasks, Depends, FastAPI, HTTPException, Query, Request, Response, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from .auth import AuthError, AuthService, GoogleOAuth, RateLimited
from .auth import OAUTH_STATE_TTL
from .engine import Engine, TradingError
from .quotes import RANGES, UnknownSymbol, make_feed
from .symbols import SymbolError, currency_of, lot_size, market_of, normalize
from .universe import suggest_symbols
from .fighter import ai_stats, compute_fighter_stats
from .rooms import RoomStore, public_fighter

log = logging.getLogger("sim-trading")
ROOT = Path(__file__).resolve().parent.parent
STATIC = ROOT / "static"
COOKIE = "sim_session"


def data_dir() -> Path:
    """Writable data directory for SQLite and logs.
    Prefer APP_DATA_DIR (Render/Fly disk mount, e.g. /data); else ./data under the project."""
    raw = os.environ.get("APP_DATA_DIR") or os.environ.get("SIM_DATA_DIR")
    path = Path(raw).expanduser() if raw else (ROOT / "data")
    path.mkdir(parents=True, exist_ok=True)
    return path


def _smtp_from_env():
    host = os.environ.get("SMTP_HOST", "").strip()
    sender = os.environ.get("SMTP_FROM", "").strip()
    if not host or not sender:
        return None
    return {"host": host, "port": int(os.environ.get("SMTP_PORT", "587") or 587),
            "user": os.environ.get("SMTP_USER", ""), "password": os.environ.get("SMTP_PASSWORD", ""),
            "from": sender}


def create_app(db_path=None, feed=None, pending_interval=None, cookie_secure=None,
               google=None, dev_show_reset=None, smtp=None, base_url=None, reset_log=None):
    dd = data_dir()
    db_path = db_path or os.environ.get("SIM_DB", str(dd / "sim_trading.db"))
    if db_path != ":memory:":
        Path(db_path).parent.mkdir(parents=True, exist_ok=True)
    feed = feed or make_feed(os.environ.get("PRICE_SOURCE", "auto"))
    engine = Engine(db_path, feed)
    auth = AuthService(engine)
    removed = auth.migrate_legacy_users()
    if removed:
        print(f"[migration] removed legacy password-less users: {removed}", flush=True)
    renamed = engine.migrate_google_numeric_usernames()
    if renamed:
        print(f"[migration] google privacy usernames: {renamed}", flush=True)
    # One-shot admin rename via env (set RENAME_USER_FROM + RENAME_USER_TO, redeploy, then unset).
    ren_from = os.environ.get("RENAME_USER_FROM", "").strip()
    ren_to = os.environ.get("RENAME_USER_TO", "").strip()
    if ren_from and ren_to:
        status = engine.rename_user(ren_from, ren_to)
        print(f"[admin] RENAME_USER {ren_from!r} -> {ren_to!r}: {status}", flush=True)
    # One-shot admin delete via env (set DELETE_USER_USERNAME[+EMAIL], redeploy, then unset).
    del_user = os.environ.get("DELETE_USER_USERNAME", "").strip()
    if del_user:
        del_email = os.environ.get("DELETE_USER_EMAIL", "").strip()
        status = engine.delete_user_by_credentials(del_user, del_email or None)
        print(f"[admin] DELETE_USER_USERNAME={del_user!r}: {status}", flush=True)
    interval = pending_interval if pending_interval is not None else float(os.environ.get("PENDING_INTERVAL", 10))
    if cookie_secure is None:
        cookie_secure = os.environ.get("COOKIE_SECURE", "0") == "1"
    # Prefer explicit APP_BASE_URL; else Railway/public host; else localhost.
    if base_url is None:
        base_url = os.environ.get("APP_BASE_URL", "").strip()
    if not base_url:
        railway_domain = os.environ.get("RAILWAY_PUBLIC_DOMAIN", "").strip()
        if railway_domain:
            base_url = f"https://{railway_domain}"
    if not base_url:
        base_url = "http://localhost:8000"
    base_url = base_url.rstrip("/")
    if google is None:
        google = GoogleOAuth(os.environ.get("GOOGLE_CLIENT_ID", ""), os.environ.get("GOOGLE_CLIENT_SECRET", ""),
                             base_url)
    if dev_show_reset is None:
        dev_show_reset = os.environ.get("DEV_SHOW_RESET_LINK", "0") == "1"
    if smtp is None:
        smtp = _smtp_from_env()
    reset_log = reset_log or (dd / "password-resets.log")

    @asynccontextmanager
    async def lifespan(app):
        task = None
        if interval > 0:
            async def loop():
                while True:
                    await asyncio.sleep(interval)
                    try:
                        filled = await asyncio.to_thread(engine.process_pending)
                        if filled:
                            log.info("filled limit orders: %s", filled)
                    except Exception:
                        log.exception("process_pending failed")
            task = asyncio.create_task(loop())
        yield
        if task:
            task.cancel()

    app = FastAPI(title="模擬股票交易平台", lifespan=lifespan, docs_url=None, redoc_url=None)
    app.state.engine = engine
    app.state.auth = auth
    app.state.google = google
    app.state.rooms = RoomStore()

    @app.middleware("http")
    async def same_origin_writes(request: Request, call_next):
        """CSRF defence in depth (on top of SameSite=Lax): reject cross-origin state-changing API calls."""
        if request.method not in ("GET", "HEAD", "OPTIONS") and request.url.path.startswith("/api/"):
            origin = request.headers.get("origin")
            if origin and urlsplit(origin).netloc != request.headers.get("host"):
                return JSONResponse({"detail": "跨站請求被拒絕"}, status_code=403)
        return await call_next(request)

    def guard(fn, *a, **kw):
        try:
            return fn(*a, **kw)
        except RateLimited as e:
            raise HTTPException(status_code=429, detail=str(e))
        except AuthError as e:
            raise HTTPException(status_code=401, detail=str(e))
        except (TradingError, SymbolError, UnknownSymbol) as e:
            raise HTTPException(status_code=400, detail=str(e))

    def current_user(request: Request):
        user = auth.session_user(request.cookies.get(COOKIE))
        if not user:
            raise HTTPException(status_code=401, detail="請先登入")
        return user

    def set_session_cookie(resp: Response, token: str):
        resp.set_cookie(COOKIE, token, max_age=auth.session_ttl, httponly=True, samesite="lax",
                        secure=cookie_secure, path="/")

    def client_ip(request: Request):
        return request.client.host if request.client else "?"

    # ------------------------------------------------------------- models
    class RegisterIn(BaseModel):
        username: str
        password: str
        password_confirm: str
        email: str

    class ForgotIn(BaseModel):
        email: str

    class ResetIn(BaseModel):
        token: str
        password: str
        password_confirm: str

    class ChangeEmailIn(BaseModel):
        current_password: str
        email: str

    class LoginIn(BaseModel):
        email: str
        password: str

    class ChangeUsernameIn(BaseModel):
        username: str

    class ChangePwIn(BaseModel):
        current_password: Optional[str] = None
        new_password: str
        new_password_confirm: str

    class OrderIn(BaseModel):
        symbol: str
        side: str
        type: str = "MARKET"
        qty: float
        limit_price: Optional[float] = None

    # ------------------------------------------------------------- auth API
    @app.post("/api/auth/register")
    def register(body: RegisterIn, request: Request, response: Response):
        user = guard(auth.register, body.username, body.password, body.password_confirm, body.email,
                     ip=client_ip(request))
        set_session_cookie(response, auth.create_session(user["id"]))
        return {"username": user["username"]}

    @app.post("/api/auth/login")
    def login(body: LoginIn, request: Request, response: Response):
        user = guard(auth.authenticate, body.email, body.password, ip=client_ip(request))
        old = request.cookies.get(COOKIE)
        if old:
            auth.delete_session(old)  # rotate session on login
        set_session_cookie(response, auth.create_session(user["id"]))
        return {"username": user["username"]}

    @app.post("/api/auth/logout")
    def logout(request: Request, response: Response):
        auth.delete_session(request.cookies.get(COOKIE))
        response.delete_cookie(COOKIE, path="/", httponly=True, samesite="lax", secure=cookie_secure)
        return {"ok": True}

    @app.get("/api/auth/providers")
    def providers():
        return {"google": google.enabled}

    @app.get("/api/auth/me")
    def me(user=Depends(current_user)):
        return guard(auth.profile, user["id"])

    @app.post("/api/auth/forgot")
    def forgot(body: ForgotIn, request: Request):
        return guard(auth.request_password_reset, body.email, base_url, dev_show=dev_show_reset, smtp=smtp,
                     log_path=reset_log, ip=client_ip(request))

    @app.post("/api/auth/reset")
    def reset_pw(body: ResetIn):
        return guard(auth.reset_password, body.token, body.password, body.password_confirm)

    @app.post("/api/auth/change-email")
    def change_email(body: ChangeEmailIn, user=Depends(current_user)):
        guard(auth.change_email, user["id"], body.current_password, body.email)
        return {"ok": True}

    @app.post("/api/auth/change-username")
    def change_username(body: ChangeUsernameIn, user=Depends(current_user)):
        return guard(auth.change_username, user["id"], body.username)

    @app.post("/api/auth/change-password")
    def change_password(body: ChangePwIn, request: Request, user=Depends(current_user)):
        guard(auth.change_password, user["id"], body.current_password, body.new_password,
              body.new_password_confirm, keep_token=request.cookies.get(COOKIE))
        return {"ok": True}

    # ------------------------------------------------------------- market data (auth required)
    @app.get("/api/health")
    def health():
        try:
            q = feed.quote("AAPL")
        except Exception as e:  # pragma: no cover
            return {"ok": True, "price_source": "error", "error": str(e)}
        return {"ok": True, "price_mode": os.environ.get("PRICE_SOURCE", "auto"), "price_source": q.source}

    def _require_admin_key(request: Request) -> None:
        """Constant-time check of X-Admin-Key against ADMIN_API_KEY."""
        expected = (os.environ.get("ADMIN_API_KEY") or "").strip()
        if not expected:
            raise HTTPException(status_code=503, detail="admin disabled")
        got = request.headers.get("X-Admin-Key") or ""
        if not hmac.compare_digest(got, expected):
            raise HTTPException(status_code=401, detail="unauthorized")

    async def _admin_purge_cleanup(rooms: RoomStore, sockets, remaining_rooms) -> None:
        for room in remaining_rooms:
            try:
                await rooms.broadcast_views(room, "room")
            except Exception:
                log.exception("admin purge broadcast failed")
        for ws in sockets:
            try:
                await ws.close(code=4401)
            except Exception:
                pass

    @app.get("/api/admin/users/{user_id}")
    def admin_get_user(user_id: int, request: Request):
        """Privacy-safe user lookup for the admin UI (no email/password/google_sub)."""
        _require_admin_key(request)
        summary = engine.admin_user_summary(user_id)
        if not summary:
            raise HTTPException(status_code=404, detail="user not found")
        return summary

    @app.delete("/api/admin/users/{user_id}")
    async def admin_delete_user(user_id: int, request: Request, background_tasks: BackgroundTasks):
        """Delete user by id: purge room seats, wipe all related DB rows."""
        _require_admin_key(request)
        summary = engine.admin_user_summary(user_id)
        if not summary:
            raise HTTPException(status_code=404, detail="user not found")
        username = summary["username"]
        rooms: RoomStore = request.app.state.rooms
        sockets, remaining = rooms.purge_user(username)
        result = engine.delete_user_by_id(user_id)
        if not result.get("deleted"):
            # Race: wiped from rooms but row gone — still report not found
            raise HTTPException(status_code=404, detail="user not found")
        if sockets or remaining:
            background_tasks.add_task(_admin_purge_cleanup, rooms, sockets, remaining)
        return {
            "ok": True,
            "id": result["id"],
            "username": result["username"],
            "deleted": True,
        }

    @app.get("/api/symbols/suggest")
    def symbols_suggest(q: str = Query("", max_length=64), limit: int = Query(10, ge=1, le=25),
                        user=Depends(current_user)):
        """Autocomplete: match built-in US symbols by code prefix or name."""
        return {"query": q, "results": suggest_symbols(q, limit)}

    @app.get("/api/quote")
    def quote(symbol: str, user=Depends(current_user)):
        sym = guard(normalize, symbol)
        q = guard(engine._quote, sym)
        lot, known = lot_size(sym)
        d = q.to_dict()
        d.update({"market": market_of(sym), "lot_size": lot, "lot_size_known": known})
        return d

    @app.get("/api/history")
    def history(symbol: str, range: str = Query("1M"), user=Depends(current_user)):
        sym = guard(normalize, symbol)
        r = range.upper()
        if r not in RANGES:
            raise HTTPException(400, f"range 必須係 {', '.join(RANGES)}")
        h = guard(feed.history, sym, r)
        h["currency"] = currency_of(sym)
        return h

    # ------------------------------------------------------------- the logged-in user's account
    @app.get("/api/me/portfolio")
    def portfolio(user=Depends(current_user)):
        return guard(engine.portfolio, user["username"])

    @app.get("/api/me/orders")
    def orders(status: Optional[str] = None, user=Depends(current_user)):
        return guard(engine.orders, user["username"], status)

    @app.get("/api/me/trades")
    def trades(user=Depends(current_user)):
        return guard(engine.trades, user["username"])

    @app.post("/api/me/orders")
    def place(body: OrderIn, user=Depends(current_user)):
        return guard(engine.place_order, user["username"], body.symbol, body.side, body.type, body.qty,
                     body.limit_price)

    @app.post("/api/me/orders/{order_id}/cancel")
    def cancel(order_id: int, user=Depends(current_user)):
        return guard(engine.cancel_order, user["username"], order_id)

    @app.post("/api/me/reset")
    def reset(user=Depends(current_user)):
        guard(engine.reset, user["username"])
        return {"ok": True}

    @app.get("/api/leaderboard")
    def leaderboard(user=Depends(current_user)):
        return engine.leaderboard()

    @app.get("/api/users/{username}/view")
    def user_public_view(username: str, user=Depends(current_user)):
        """Read-only portfolio + recent trades for any classmate (auth required).
        Reuses engine.portfolio / engine.trades — no email, password, or secrets."""
        def _view():
            # Normalize via validate so path casing / trim matches stored usernames
            name = engine.validate_username(username)
            p = engine.portfolio(name)
            trades = engine.trades(name, limit=100)
            return {
                "username": p["username"],
                "base_currency": p.get("base_currency"),
                "total": p["total"],
                "accounts": p["accounts"],
                "positions": p["positions"],
                "trades": trades,
            }
        return guard(_view)

    # ------------------------------------------------------------- 理財戰士 (Finance Fighter)
    class FighterMatchIn(BaseModel):
        opponent_username: str

    class FighterResultIn(BaseModel):
        mode: str  # ai | classmate
        opponent_username: str
        winner: str  # player | opponent | draw
        player_kos: int = 0
        opponent_kos: int = 0
        player_stats: Optional[dict] = None
        opponent_stats: Optional[dict] = None
        difficulty: Optional[str] = None

    @app.get("/api/fighter/stats")
    def fighter_stats(user=Depends(current_user)):
        """Own fighter ATK/DEF/SPD from current holdings market value."""
        pf = guard(engine.portfolio, user["username"])
        return compute_fighter_stats(pf)

    @app.get("/api/fighter/ai")
    def fighter_ai(difficulty: str = Query("normal"), mirror: int = Query(1),
                   user=Depends(current_user)):
        """Practice AI stats. mirror=1 uses a scaled copy of the player's stats."""
        pf = guard(engine.portfolio, user["username"])
        me = compute_fighter_stats(pf)
        return ai_stats(difficulty, mirror=me if mirror else None)

    @app.post("/api/fighter/match")
    def fighter_match(body: FighterMatchIn, user=Depends(current_user)):
        """Snapshot both players' live portfolio-derived stats for a classmate 1v1."""
        opp = (body.opponent_username or "").strip()
        if not opp:
            raise HTTPException(400, "請輸入同學用戶名")
        if opp.lower() == user["username"].lower():
            raise HTTPException(400, "唔可以同自己對戰")
        try:
            pf_me = engine.portfolio(user["username"])
            pf_opp = engine.portfolio(opp)
        except TradingError as e:
            raise HTTPException(400, str(e))
        return {
            "player": compute_fighter_stats(pf_me),
            "opponent": compute_fighter_stats(pf_opp),
            "mode": "classmate",
        }

    @app.post("/api/fighter/result")
    def fighter_result(body: FighterResultIn, user=Depends(current_user)):
        """Record a finished match (optional history)."""
        mode = (body.mode or "").lower()
        if mode not in ("ai", "classmate", "online"):
            raise HTTPException(400, "mode 必須係 ai / classmate / online")
        winner = (body.winner or "").lower()
        if winner not in ("player", "opponent", "draw"):
            raise HTTPException(400, "winner 必須係 player / opponent / draw")
        opp = (body.opponent_username or "").strip() or ("AI" if mode == "ai" else "")
        if not opp:
            raise HTTPException(400, "缺少對手名稱")
        rec = engine.record_fighter_match(
            mode, user["username"], opp, winner,
            body.player_kos, body.opponent_kos,
            body.player_stats, body.opponent_stats)
        return {"ok": True, **rec}

    @app.get("/api/fighter/history")
    def fighter_history(user=Depends(current_user)):
        return {"rows": engine.recent_fighter_matches(user["username"])}

    @app.get("/api/fighter/rooms/public")
    def fighter_public_rooms(user=Depends(current_user)):
        """List joinable public lobbies (waiting, not full). Auth required."""
        return {"rooms": app.state.rooms.list_public()}

    # ------------------------------------------------------------- 聯機房間 (WebSocket)
    @app.websocket("/api/fighter/room/ws")
    async def fighter_room_ws(websocket: WebSocket):
        """Single-socket lobby: create / join / ready / start / leave.

        Matches static/fighter.js RoomNet. Session cookie required.
        """
        user = auth.session_user(websocket.cookies.get(COOKIE))
        if not user:
            await websocket.close(code=4401)
            return
        await websocket.accept()
        username = user["username"]
        room_code = None
        rooms = websocket.app.state.rooms

        async def _err(message: str):
            try:
                await websocket.send_json({"type": "error", "message": message})
            except Exception:
                pass

        async def _start_match(room):
            """Snapshot live stats and send personalized start to each seat."""
            names = list(room.players.keys())
            if len(names) != 2:
                await _err("需要兩位玩家先開戰")
                return
            try:
                stats_by = {
                    n: public_fighter(compute_fighter_stats(engine.portfolio(n)))
                    for n in names
                }
            except TradingError as e:
                await _err(str(e))
                return
            rooms.mark_fighting(room, room.map_id)
            for n in names:
                opp = next(x for x in names if x != n)
                await rooms.send_json(room, n, {
                    "type": "start",
                    "player": stats_by[n],
                    "opponent": stats_by[opp],
                    "mapId": room.map_id,
                    "map_id": room.map_id,
                    "code": room.room_code,
                    "room_code": room.room_code,
                    "role": "host" if n == room.host else "guest",
                    "mode": "online",
                })

        try:
            while True:
                raw = await websocket.receive_json()
                if not isinstance(raw, dict):
                    await _err("無效訊息")
                    continue
                typ = (raw.get("type") or raw.get("event") or "").strip().lower()

                try:
                    if typ == "create":
                        map_id = raw.get("mapId") or raw.get("map_id")
                        is_public = bool(raw.get("public", False))
                        if room_code:
                            left = rooms.leave(room_code, username)
                            if left:
                                await rooms.broadcast_views(left, "room")
                        room = rooms.create(username, map_id=map_id, public=is_public)
                        room_code = room.room_code
                        rooms.attach_ws(room, username, websocket)
                        await websocket.send_json(room.client_view(username))

                    elif typ == "list":
                        await websocket.send_json({
                            "type": "rooms",
                            "rooms": rooms.list_public(),
                        })

                    elif typ == "join":
                        code = (raw.get("code") or raw.get("room_code") or "").strip().upper()
                        if not code:
                            await _err("請輸入房間碼")
                            continue
                        if room_code and room_code != code:
                            left = rooms.leave(room_code, username)
                            if left:
                                await rooms.broadcast_views(left, "room")
                        room = rooms.join(code, username)
                        room_code = room.room_code
                        rooms.attach_ws(room, username, websocket)
                        await rooms.broadcast_views(room, "room")

                    elif typ == "ready":
                        if not room_code:
                            await _err("你仲未加入房間")
                            continue
                        ready_flag = raw.get("ready")
                        if ready_flag is None:
                            ready_flag = True
                        room = rooms.set_ready(room_code, username, bool(ready_flag))
                        await rooms.broadcast_views(room, "ready")
                        # Both ready → auto-start (lobby has no Start button).
                        if room.both_ready() and room.status == "ready":
                            await _start_match(room)

                    elif typ == "unready":
                        if not room_code:
                            await _err("你仲未加入房間")
                            continue
                        room = rooms.set_ready(room_code, username, False)
                        await rooms.broadcast_views(room, "ready")

                    elif typ == "start":
                        if not room_code:
                            await _err("你仲未加入房間")
                            continue
                        room = rooms.get(room_code)
                        if not room or username not in room.players:
                            await _err("你唔喺呢個房間")
                            continue
                        if username != room.host:
                            await _err("只有房主可以開戰")
                            continue
                        if not room.both_ready():
                            await _err("雙方都要準備就緒先開戰")
                            continue
                        map_id = raw.get("mapId") or raw.get("map_id")
                        if map_id:
                            room.map_id = map_id
                        await _start_match(room)

                    elif typ == "leave":
                        if room_code:
                            left = rooms.leave(room_code, username)
                            room_code = None
                            if left:
                                await rooms.broadcast_views(left, "room")
                        try:
                            await websocket.send_json({"type": "room", "status": "closed", "code": None})
                        except Exception:
                            pass

                    elif typ == "ping":
                        await websocket.send_json({"type": "pong"})

                    elif typ == "input":
                        # Stub for future input sync — acknowledge only.
                        await websocket.send_json({"type": "input_ack"})

                    else:
                        await _err(f"未知事件: {typ or '?'}")

                except LookupError as e:
                    await _err(str(e))
                except ValueError as e:
                    await _err(str(e))
                except PermissionError as e:
                    await _err(str(e))
                except RuntimeError as e:
                    await _err(str(e))
                except TradingError as e:
                    await _err(str(e))

        except WebSocketDisconnect:
            pass
        except Exception:
            log.exception("fighter room ws error user=%s", username)
        finally:
            if room_code:
                room = rooms.get(room_code)
                if room and username in room.players:
                    rooms.detach_ws(room, username, websocket)
                    # Drop seat if no sockets left (tab closed).
                    player = room.players.get(username)
                    if player is not None and not player.websockets:
                        left = rooms.leave(room_code, username)
                        if left:
                            try:
                                await rooms.broadcast_views(left, "room")
                            except Exception:
                                pass

    # ------------------------------------------------------------- pages
    def logged_in(request):
        return auth.session_user(request.cookies.get(COOKIE)) is not None

    @app.get("/")
    @app.get("/leaderboard")
    def index(request: Request):
        if not logged_in(request):
            return RedirectResponse("/login", status_code=303)
        return FileResponse(STATIC / "index.html", headers={"Cache-Control": "no-store"})

    @app.get("/fighter")
    def fighter_page(request: Request):
        if not logged_in(request):
            return RedirectResponse("/login", status_code=303)
        return FileResponse(STATIC / "fighter.html", headers={"Cache-Control": "no-store"})

    @app.get("/admin")
    def admin_page():
        """Admin privacy wipe UI. Operator pastes X-Admin-Key in-page; never hardcode."""
        return FileResponse(STATIC / "admin.html", headers={"Cache-Control": "no-store"})

    @app.get("/login")
    @app.get("/register")
    def login_page(request: Request):
        if logged_in(request):
            return RedirectResponse("/", status_code=303)
        return FileResponse(STATIC / "login.html", headers={"Cache-Control": "no-store"})

    @app.get("/forgot")
    def forgot_page():
        return FileResponse(STATIC / "forgot.html", headers={"Cache-Control": "no-store"})

    @app.get("/reset")
    def reset_page():
        return FileResponse(STATIC / "reset.html", headers={"Cache-Control": "no-store"})

    OAUTH_COOKIE = "sim_oauth_state"

    @app.get("/auth/google/start")
    def google_start():
        if not google.enabled:
            raise HTTPException(400, "未設定 Google 登入（GOOGLE_CLIENT_ID 未設定）")
        state = auth.begin_oauth()
        resp = RedirectResponse(google.authorization_url(state), status_code=302)
        resp.set_cookie(OAUTH_COOKIE, state, max_age=OAUTH_STATE_TTL, httponly=True, samesite="lax",
                        secure=cookie_secure, path="/")
        return resp

    @app.get("/auth/google/callback")
    def google_callback(request: Request, code: Optional[str] = None, state: Optional[str] = None,
                        error: Optional[str] = None):
        if not google.enabled:
            raise HTTPException(400, "未設定 Google 登入（GOOGLE_CLIENT_ID 未設定）")
        if error:
            raise HTTPException(400, "Google 登入已取消或失敗")
        user = guard(auth.login_with_google, code, state, request.cookies.get(OAUTH_COOKIE), google)
        resp = RedirectResponse("/", status_code=303)
        set_session_cookie(resp, auth.create_session(user["id"]))
        resp.delete_cookie(OAUTH_COOKIE, path="/", httponly=True, samesite="lax", secure=cookie_secure)
        return resp

    @app.middleware("http")
    async def fighter_assets_no_cache(request: Request, call_next):
        """Avoid stale fighter.js showing blue/red rectangles after sprite deploys."""
        response = await call_next(request)
        path = request.url.path or ""
        if path.startswith("/static/fighter") or path in ("/static/fighter.js", "/static/fighter.css", "/static/fighter.html"):
            response.headers["Cache-Control"] = "no-cache, must-revalidate"
        return response

    app.mount("/static", StaticFiles(directory=STATIC), name="static")
    return app
