"""FastAPI app: JSON API under /api (auth required), login/register pages, trading SPA at /."""
import asyncio
import logging
import os
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Optional
from urllib.parse import urlsplit

from fastapi import Depends, FastAPI, HTTPException, Query, Request, Response
from fastapi.responses import FileResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from .auth import AuthError, AuthService, GoogleOAuth, RateLimited
from .auth import OAUTH_STATE_TTL
from .engine import Engine, TradingError
from .quotes import RANGES, UnknownSymbol, make_feed
from .symbols import SymbolError, currency_of, lot_size, market_of, normalize

log = logging.getLogger("sim-trading")
ROOT = Path(__file__).resolve().parent.parent
STATIC = ROOT / "static"
COOKIE = "sim_session"


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
    db_path = db_path or os.environ.get("SIM_DB", str(ROOT / "data" / "sim_trading.db"))
    if db_path != ":memory:":
        Path(db_path).parent.mkdir(parents=True, exist_ok=True)
    feed = feed or make_feed(os.environ.get("PRICE_SOURCE", "auto"))
    engine = Engine(db_path, feed)
    auth = AuthService(engine)
    removed = auth.migrate_legacy_users()
    if removed:
        print(f"[migration] removed legacy password-less users: {removed}", flush=True)
    interval = pending_interval if pending_interval is not None else float(os.environ.get("PENDING_INTERVAL", 10))
    if cookie_secure is None:
        cookie_secure = os.environ.get("COOKIE_SECURE", "0") == "1"
    base_url = (base_url or os.environ.get("APP_BASE_URL") or "http://localhost:8000").rstrip("/")
    if google is None:
        google = GoogleOAuth(os.environ.get("GOOGLE_CLIENT_ID", ""), os.environ.get("GOOGLE_CLIENT_SECRET", ""),
                             base_url)
    if dev_show_reset is None:
        dev_show_reset = os.environ.get("DEV_SHOW_RESET_LINK", "0") == "1"
    if smtp is None:
        smtp = _smtp_from_env()
    reset_log = reset_log or (ROOT / "data" / "password-resets.log")

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
        username: str
        password: str

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
        user = guard(auth.authenticate, body.username, body.password, ip=client_ip(request))
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

    # ------------------------------------------------------------- pages
    def logged_in(request):
        return auth.session_user(request.cookies.get(COOKIE)) is not None

    @app.get("/")
    @app.get("/leaderboard")
    def index(request: Request):
        if not logged_in(request):
            return RedirectResponse("/login", status_code=303)
        return FileResponse(STATIC / "index.html", headers={"Cache-Control": "no-store"})

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

    app.mount("/static", StaticFiles(directory=STATIC), name="static")
    return app
