"""Accounts, password hashing, sessions and login throttling.

- Passwords: hashlib.scrypt (memory-hard, stdlib) with a random 16-byte per-user salt.
  Stored as  scrypt$<n>$<r>$<p>$<salt b64>$<hash b64>; plaintext is never stored or logged.
- Sessions: 256-bit random token in an httpOnly, SameSite=Lax cookie. Only sha256(token)
  is stored in the DB, with a server-side expiry.
- Throttling: per-account lockout (5 wrong passwords -> locked 15 min, persisted in DB)
  plus an in-memory per-IP limit on failed logins and on registrations.
"""
import base64
import hashlib
import hmac
import logging
import re
import secrets
import smtplib
import threading
import time
from collections import defaultdict, deque
from email.message import EmailMessage
from urllib.parse import urlencode

import requests

from .engine import TradingError

log = logging.getLogger("sim-trading.auth")

SCRYPT_N, SCRYPT_R, SCRYPT_P = 2 ** 14, 8, 1
MIN_PASSWORD, MAX_PASSWORD = 8, 128
SESSION_TTL = 7 * 24 * 3600
MAX_FAILED_PER_ACCOUNT = 5
LOCKOUT_SECONDS = 15 * 60
IP_FAIL_LIMIT, IP_FAIL_WINDOW = 20, 15 * 60
IP_REGISTER_LIMIT, IP_REGISTER_WINDOW = 10, 3600
IP_RESET_LIMIT, IP_RESET_WINDOW = 10, 15 * 60
RESET_TTL = 30 * 60
OAUTH_STATE_TTL = 10 * 60
FORGOT_MESSAGE = "如果呢個電郵有登記，我哋已經寄出重設連結"
EMAIL_RE = re.compile(r"^[a-z0-9._%+\-]+@[a-z0-9.\-]+\.[a-z]{2,}$")


class AuthError(TradingError):
    status = 401


class RateLimited(TradingError):
    status = 429


def _b64(b):
    return base64.b64encode(b).decode()


def hash_password(password: str, n=SCRYPT_N, r=SCRYPT_R, p=SCRYPT_P) -> str:
    salt = secrets.token_bytes(16)
    dk = hashlib.scrypt(password.encode(), salt=salt, n=n, r=r, p=p, maxmem=128 * 1024 * 1024, dklen=32)
    return f"scrypt${n}${r}${p}${_b64(salt)}${_b64(dk)}"


def verify_password(password: str, stored: str) -> bool:
    try:
        algo, n, r, p, salt, dk = stored.split("$")
        if algo != "scrypt":
            return False
        calc = hashlib.scrypt(password.encode(), salt=base64.b64decode(salt), n=int(n), r=int(r), p=int(p),
                              maxmem=128 * 1024 * 1024, dklen=len(base64.b64decode(dk)))
        return hmac.compare_digest(calc, base64.b64decode(dk))
    except Exception:
        return False


# A fixed dummy hash so unknown usernames cost the same time as wrong passwords.
_DUMMY_HASH = hash_password(secrets.token_hex(8))


def _token_hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def validate_password(password: str, username: str = ""):
    if not isinstance(password, str) or len(password) < MIN_PASSWORD:
        raise TradingError(f"密碼最少要 {MIN_PASSWORD} 個字")
    if len(password) > MAX_PASSWORD:
        raise TradingError(f"密碼最多 {MAX_PASSWORD} 個字")
    if username and password.strip().lower() == username.strip().lower():
        raise TradingError("密碼唔可以同用戶名一樣")


class _IpLimiter:
    def __init__(self, limit, window):
        self.limit, self.window = limit, window
        self.hits = defaultdict(deque)
        self.lock = threading.Lock()

    def blocked(self, key):
        now = time.time()
        with self.lock:
            q = self.hits[key]
            while q and now - q[0] > self.window:
                q.popleft()
            return len(q) >= self.limit

    def hit(self, key):
        with self.lock:
            self.hits[key].append(time.time())


class AuthService:
    def __init__(self, engine, session_ttl=SESSION_TTL):
        self.engine = engine
        self.db = engine.db
        self.lock = engine.lock
        self.session_ttl = session_ttl
        self.ip_fail = _IpLimiter(IP_FAIL_LIMIT, IP_FAIL_WINDOW)
        self.ip_register = _IpLimiter(IP_REGISTER_LIMIT, IP_REGISTER_WINDOW)
        self.ip_reset = _IpLimiter(IP_RESET_LIMIT, IP_RESET_WINDOW)

    # ------------------------------------------------------------- migration
    def migrate_legacy_users(self):
        """v1 accounts had no password and can't be authenticated safely -> remove them
        (and their positions/orders/trades). Returns the removed usernames."""
        with self.lock:
            # Only pre-auth rows: a Google-only account also has no password, but it has google_sub/email.
            rows = self.db.execute(
                "SELECT id, username FROM users WHERE password_hash IS NULL AND google_sub IS NULL AND email IS NULL"
            ).fetchall()
            if rows:
                with self.engine._tx() as db:
                    for r in rows:
                        self.engine.delete_user_data(db, r["id"])
                log.warning("removed %d legacy password-less users: %s", len(rows), [r["username"] for r in rows])
            return [r["username"] for r in rows]

    # ------------------------------------------------------------- accounts
    def register(self, username, password, password_confirm=None, email=None, ip="?"):
        if self.ip_register.blocked(ip):
            raise RateLimited("註冊太頻密，請遲啲再試")
        username = self.engine.validate_username(username)
        email = normalize_email(email)
        if password_confirm is not None and password != password_confirm:
            raise TradingError("兩次輸入嘅密碼唔一樣")
        validate_password(password, username)
        user = self.engine.create_user(username, hash_password(password), email=email, email_verified=0)
        self.ip_register.hit(ip)
        return user

    def authenticate(self, username, password, ip="?"):
        if self.ip_fail.blocked(ip):
            raise RateLimited("登入失敗次數太多，請 15 分鐘後再試")
        username = (username or "").strip()
        password = password or ""
        row = self.db.execute("SELECT * FROM users WHERE username = ?", (username,)).fetchone()
        now = time.time()
        if row and row["locked_until"] > now:
            mins = int((row["locked_until"] - now) // 60) + 1
            raise RateLimited(f"密碼錯誤太多次，帳戶暫時鎖定，請 {mins} 分鐘後再試")
        ok = verify_password(password, row["password_hash"] if row and row["password_hash"] else _DUMMY_HASH)
        if not row or not row["password_hash"] or not ok:
            self.ip_fail.hit(ip)
            # Don't lock an account that has no password (Google-only); the error stays generic.
            if row and row["password_hash"]:
                with self.lock:
                    failed = self.db.execute("SELECT failed_logins FROM users WHERE id=?",
                                             (row["id"],)).fetchone()[0] + 1
                    if failed >= MAX_FAILED_PER_ACCOUNT:
                        self.db.execute("UPDATE users SET failed_logins=0, locked_until=? WHERE id=?",
                                        (now + LOCKOUT_SECONDS, row["id"]))
                        raise RateLimited("密碼錯誤太多次，帳戶已暫時鎖定 15 分鐘")
                    self.db.execute("UPDATE users SET failed_logins=? WHERE id=?", (failed, row["id"]))
            raise AuthError("用戶名或密碼錯誤")
        if row["failed_logins"] or row["locked_until"]:
            self.db.execute("UPDATE users SET failed_logins=0, locked_until=0 WHERE id=?", (row["id"],))
        return {"id": row["id"], "username": row["username"]}

    def change_password(self, user_id, current, new, confirm=None, keep_token=None):
        row = self.db.execute("SELECT * FROM users WHERE id=?", (user_id,)).fetchone()
        if not row:
            raise TradingError("搵唔到用戶")
        has_pw = bool(row["password_hash"])
        # Google-only accounts proved identity via this session, so they may set a first password
        # without the current one. Anyone who already has a password must enter it.
        if has_pw and not verify_password(current or "", row["password_hash"]):
            raise TradingError("現有密碼錯誤")
        if confirm is not None and new != confirm:
            raise TradingError("兩次輸入嘅新密碼唔一樣")
        validate_password(new, row["username"])
        if has_pw and verify_password(new, row["password_hash"]):
            raise TradingError("新密碼唔可以同舊密碼一樣")
        new_hash = hash_password(new)
        with self.lock:
            self.db.execute("UPDATE users SET password_hash=? WHERE id=?", (new_hash, user_id))
            # sign out every other session of this user
            keep = _token_hash(keep_token) if keep_token else ""
            self.db.execute("DELETE FROM sessions WHERE user_id=? AND token_hash != ?", (user_id, keep))

    # ------------------------------------------------------------- sessions
    def create_session(self, user_id):
        token = secrets.token_urlsafe(32)
        now = time.time()
        with self.lock:
            self.db.execute("DELETE FROM sessions WHERE expires_at < ?", (now,))
            self.db.execute("INSERT INTO sessions(token_hash, user_id, created_at, expires_at) VALUES (?,?,?,?)",
                            (_token_hash(token), user_id, now, now + self.session_ttl))
        return token

    def session_user(self, token):
        if not token:
            return None
        row = self.db.execute(
            "SELECT u.id, u.username, s.expires_at FROM sessions s JOIN users u ON u.id = s.user_id "
            "WHERE s.token_hash = ?", (_token_hash(token),)).fetchone()
        if not row:
            return None
        if row["expires_at"] < time.time():
            self.delete_session(token)
            return None
        return {"id": row["id"], "username": row["username"]}

    def delete_session(self, token):
        if token:
            with self.lock:
                self.db.execute("DELETE FROM sessions WHERE token_hash = ?", (_token_hash(token),))


def normalize_email(email):
    email = (email or "").strip().lower()
    if not email or len(email) > 254 or not EMAIL_RE.match(email):
        raise TradingError("請輸入有效嘅電郵地址")
    return email


def _append_reset_log(path, email, url):
    if not path:
        return
    try:
        from datetime import datetime, timedelta, timezone
        line = datetime.now(timezone(timedelta(hours=8))).isoformat(timespec="seconds")
        with open(path, "a", encoding="utf-8") as f:
            f.write(f"{line} email={email} reset_url={url}\n")
    except OSError:
        log.exception("could not write password reset log")


def send_reset_email(smtp, to, url):
    msg = EmailMessage()
    msg["Subject"] = "重設模擬交易平台密碼"
    msg["From"] = smtp["from"]
    msg["To"] = to
    msg.set_content(
        "你申請咗重設模擬股票交易平台嘅密碼。\n"
        "請喺 30 分鐘內打開以下連結（只可以用一次）：\n\n"
        f"{url}\n\n"
        "如果你冇申請，可以不理呢封電郵。\n")
    port = int(smtp["port"])
    if port == 465:
        with smtplib.SMTP_SSL(smtp["host"], port, timeout=15) as s:
            if smtp.get("user"):
                s.login(smtp["user"], smtp.get("password") or "")
            s.send_message(msg)
    else:
        with smtplib.SMTP(smtp["host"], port, timeout=15) as s:
            s.ehlo()
            s.starttls()
            s.ehlo()
            if smtp.get("user"):
                s.login(smtp["user"], smtp.get("password") or "")
            s.send_message(msg)


def _same(a, b):
    if not isinstance(a, str) or not isinstance(b, str) or len(a) != len(b) or not a:
        return False
    return hmac.compare_digest(a, b)


class GoogleOAuth:
    """Server-side authorization-code flow. `http` is injectable so tests never call Google."""

    AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
    TOKEN_URL = "https://oauth2.googleapis.com/token"
    USERINFO_URL = "https://www.googleapis.com/oauth2/v3/userinfo"

    def __init__(self, client_id, client_secret, base_url, http=None):
        self.client_id = (client_id or "").strip()
        self.client_secret = client_secret or ""
        self.base_url = (base_url or "http://localhost:8000").rstrip("/")
        self.http = http or requests

    @property
    def enabled(self):
        return bool(self.client_id)

    @property
    def redirect_uri(self):
        return f"{self.base_url}/auth/google/callback"

    def authorization_url(self, state):
        q = urlencode({
            "client_id": self.client_id,
            "redirect_uri": self.redirect_uri,
            "response_type": "code",
            "scope": "openid email profile",
            "state": state,
            "prompt": "select_account",
        })
        return f"{self.AUTH_URL}?{q}"

    def exchange_code(self, code):
        r = self.http.post(self.TOKEN_URL, data={
            "code": code, "client_id": self.client_id, "client_secret": self.client_secret,
            "redirect_uri": self.redirect_uri, "grant_type": "authorization_code",
        }, timeout=10)
        if getattr(r, "status_code", 200) != 200:
            raise TradingError("Google 登入失敗，請再試一次")
        data = r.json()
        if not data.get("access_token"):
            raise TradingError("Google 登入失敗，請再試一次")
        return data

    def fetch_userinfo(self, access_token):
        r = self.http.get(self.USERINFO_URL, headers={"Authorization": f"Bearer {access_token}"}, timeout=10)
        if getattr(r, "status_code", 200) != 200:
            raise TradingError("攞唔到 Google 帳戶資料")
        info = r.json()
        if not info.get("sub"):
            raise TradingError("攞唔到 Google 帳戶資料")
        return info


# bind new methods onto AuthService
def _profile(self, user_id):
    row = self.db.execute(
        "SELECT username, email, email_verified, password_hash, google_sub FROM users WHERE id=?",
        (user_id,)).fetchone()
    if not row:
        raise TradingError("搵唔到用戶")
    return {"username": row["username"], "email": row["email"],
            "email_verified": bool(row["email_verified"]), "has_password": bool(row["password_hash"]),
            "google": bool(row["google_sub"])}


def _change_email(self, user_id, current_password, email):
    row = self.db.execute("SELECT * FROM users WHERE id=?", (user_id,)).fetchone()
    if not row or not row["password_hash"]:
        raise TradingError("請先設定密碼，先可以更改電郵")
    if not verify_password(current_password or "", row["password_hash"]):
        raise TradingError("現有密碼錯誤")
    email = normalize_email(email)
    if email == (row["email"] or ""):
        raise TradingError("新電郵同而家嘅一樣")
    if self.db.execute("SELECT 1 FROM users WHERE email=? AND id!=?", (email, user_id)).fetchone():
        raise TradingError("呢個電郵已經有人用咗")
    with self.lock:
        self.db.execute("UPDATE users SET email=?, email_verified=0 WHERE id=?", (email, user_id))


def _request_password_reset(self, email, base_url, *, dev_show=False, smtp=None, log_path=None, ip="?"):
    """Always the same message. A token is issued only for a password account that has this email.
    Google-only accounts get no token (they should sign in with Google)."""
    if self.ip_reset.blocked(ip):
        raise RateLimited("申請太頻密，請遲啲再試")
    self.ip_reset.hit(ip)
    email_n = normalize_email(email)
    out = {"message": FORGOT_MESSAGE}
    row = self.db.execute("SELECT * FROM users WHERE email = ?", (email_n,)).fetchone()
    if not row or not row["password_hash"]:
        return out
    token = secrets.token_urlsafe(32)
    now = time.time()
    with self.lock:
        self.db.execute("UPDATE password_resets SET used_at=? WHERE user_id=? AND used_at IS NULL", (now, row["id"]))
        self.db.execute(
            "INSERT INTO password_resets(token_hash, user_id, created_at, expires_at) VALUES (?,?,?,?)",
            (_token_hash(token), row["id"], now, now + RESET_TTL))
    url = f"{base_url.rstrip('/')}/reset?token={token}"
    if smtp and smtp.get("host") and smtp.get("from"):
        try:
            send_reset_email(smtp, email_n, url)
        except Exception:
            log.exception("SMTP send failed; wrote the link to the reset log instead")
            _append_reset_log(log_path, email_n, url)
    else:
        _append_reset_log(log_path, email_n, url)
        if dev_show:
            out["reset_url"] = url
    return out


def _reset_password(self, token, new, confirm=None):
    if confirm is not None and new != confirm:
        raise TradingError("兩次輸入嘅新密碼唔一樣")
    row = None
    if token:
        row = self.db.execute(
            "SELECT r.token_hash, r.user_id, r.expires_at, r.used_at, u.username, u.password_hash "
            "FROM password_resets r JOIN users u ON u.id = r.user_id WHERE r.token_hash = ?",
            (_token_hash(token),)).fetchone()
    now = time.time()
    if not row or row["used_at"] or row["expires_at"] < now:
        raise TradingError("重設連結無效或者已過期，請重新申請")
    validate_password(new, row["username"])
    if row["password_hash"] and verify_password(new, row["password_hash"]):
        raise TradingError("新密碼唔可以同舊密碼一樣")
    new_hash = hash_password(new)
    with self.lock:
        cur = self.db.execute("SELECT used_at, expires_at FROM password_resets WHERE token_hash=?",
                              (row["token_hash"],)).fetchone()
        if not cur or cur["used_at"] or cur["expires_at"] < time.time():
            raise TradingError("重設連結無效或者已過期，請重新申請")
        self.db.execute("UPDATE password_resets SET used_at=? WHERE token_hash=?", (time.time(), row["token_hash"]))
        self.db.execute("UPDATE users SET password_hash=?, failed_logins=0, locked_until=0 WHERE id=?",
                        (new_hash, row["user_id"]))
        self.db.execute("DELETE FROM sessions WHERE user_id=?", (row["user_id"],))
    return {"username": row["username"]}


def _begin_oauth(self):
    state = secrets.token_urlsafe(24)
    now = time.time()
    with self.lock:
        self.db.execute("DELETE FROM oauth_states WHERE expires_at < ?", (now,))
        self.db.execute("INSERT INTO oauth_states(state_hash, created_at, expires_at) VALUES (?,?,?)",
                        (_token_hash(state), now, now + OAUTH_STATE_TTL))
    return state


def _consume_oauth_state(self, state, cookie_state):
    if not _same(state or "", cookie_state or ""):
        raise AuthError("Google 登入驗證失敗（state 唔吻合），請再試一次")
    now = time.time()
    with self.lock:
        row = self.db.execute("SELECT expires_at FROM oauth_states WHERE state_hash=?",
                              (_token_hash(state),)).fetchone()
        self.db.execute("DELETE FROM oauth_states WHERE state_hash=?", (_token_hash(state),))
    if not row or row["expires_at"] < now:
        raise AuthError("Google 登入已過期，請再試一次")


def _username_from_email(self, email):
    local = re.sub(r"[^a-z0-9_\-]", "", email.split("@", 1)[0].lower())[:20]
    if len(local) < 2:
        local = "user"
    candidate, n = local, 2
    while self.db.execute("SELECT 1 FROM users WHERE username = ?", (candidate,)).fetchone():
        suffix = str(n)
        candidate = local[:20 - len(suffix)] + suffix
        n += 1
        if n > 9999:
            candidate = "u" + secrets.token_hex(4)
            break
    return candidate


def _google_verified(info):
    v = info.get("email_verified")
    return v in (True, "true", "True", 1, "1")


def _login_with_google(self, code, state, cookie_state, google):
    self._consume_oauth_state(state, cookie_state)
    if not code:
        raise TradingError("Google 冇返回授權碼")
    token = google.exchange_code(code)
    info = google.fetch_userinfo(token["access_token"])
    sub = str(info["sub"])
    verified = _google_verified(info)
    email = None
    if info.get("email"):
        try:
            email = normalize_email(info["email"])
        except TradingError:
            email = None
    with self.lock:
        by_sub = self.db.execute("SELECT * FROM users WHERE google_sub=?", (sub,)).fetchone()
        if by_sub:
            return {"id": by_sub["id"], "username": by_sub["username"], "created": False}
        if email and verified:
            by_email = self.db.execute("SELECT * FROM users WHERE email=?", (email,)).fetchone()
            if by_email:
                if by_email["google_sub"] and by_email["google_sub"] != sub:
                    raise TradingError("呢個電郵已經連結咗另一個 Google 帳戶")
                self.db.execute("UPDATE users SET google_sub=?, email_verified=1 WHERE id=?", (sub, by_email["id"]))
                return {"id": by_email["id"], "username": by_email["username"], "created": False, "linked": True}
        if email:
            taken = self.db.execute("SELECT 1 FROM users WHERE email=?", (email,)).fetchone()
            if taken:
                raise TradingError("呢個電郵已有帳戶，但 Google 未驗證呢個電郵，所以唔可以連結。請用密碼登入。")
        if not email:
            raise TradingError("Google 帳戶冇提供電郵，唔可以開戶")
        username = self._username_from_email(email)
        user = self.engine.create_user(username, None, email=email, email_verified=1 if verified else 0,
                                       google_sub=sub)
        user["created"] = True
        return user


AuthService.profile = _profile
AuthService.change_email = _change_email
AuthService.request_password_reset = _request_password_reset
AuthService.reset_password = _reset_password
AuthService.begin_oauth = _begin_oauth
AuthService._consume_oauth_state = _consume_oauth_state
AuthService._username_from_email = _username_from_email
AuthService.login_with_google = _login_with_google
