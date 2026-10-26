"""Paper-trading engine: users, cash, positions, orders, trades, leaderboard.

Design
- Trading is US stocks only (USD wallet). HK symbols are rejected at normalize / place_order.
- Starting capital is USD 1,000,000 for every account (no HKD wallet).
- Leaderboard / combined totals use USD as the base currency.
- No trading fees (by request).
- Market orders fill immediately at the current quote. Limit orders fill immediately if
  marketable, otherwise rest as PENDING with cash (buy) or shares (sell) reserved, and are
  filled by process_pending() when the market price crosses the limit (filled at the
  market price at that moment, which is at least as good as the limit).
"""
import re
import sqlite3
import threading
import time
from datetime import datetime, timedelta, timezone

from .symbols import SymbolError, currency_of, lot_size, market_of, normalize

HKT = timezone(timedelta(hours=8))
# New accounts / reset: USD 1,000,000 only (US stocks).
DEFAULT_INITIAL_CASH = {"USD": 1_000_000.0}
BASE_CURRENCY = "USD"
_LEGACY_USD_INITIAL = 64_000.0  # previous starting USD (triggers one-shot capital migration)


class TradingError(ValueError):
    """Business-rule rejection (shown to the user)."""


def _now():
    return time.time()


def _iso(ts):
    return datetime.fromtimestamp(ts, HKT).isoformat(timespec="seconds") if ts else None


def _r2(x):
    return round(x + 0.0, 2)


SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    username TEXT NOT NULL UNIQUE COLLATE NOCASE,
    password_hash TEXT,          -- NULL for Google-only accounts
    email TEXT,                  -- stored lowercased; NULL until the user sets one
    email_verified INTEGER NOT NULL DEFAULT 0,
    google_sub TEXT,             -- Google "sub", NULL if not linked
    failed_logins INTEGER NOT NULL DEFAULT 0,
    locked_until REAL NOT NULL DEFAULT 0,
    created_at REAL NOT NULL,
    reset_at REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS password_resets (
    token_hash TEXT PRIMARY KEY,   -- sha256 of the raw token; raw token is never stored
    user_id INTEGER NOT NULL,
    created_at REAL NOT NULL,
    expires_at REAL NOT NULL,
    used_at REAL
);
CREATE TABLE IF NOT EXISTS oauth_states (
    state_hash TEXT PRIMARY KEY,
    created_at REAL NOT NULL,
    expires_at REAL NOT NULL
);
CREATE UNIQUE INDEX IF NOT EXISTS ux_users_email ON users(email) WHERE email IS NOT NULL;
CREATE UNIQUE INDEX IF NOT EXISTS ux_users_google ON users(google_sub) WHERE google_sub IS NOT NULL;
CREATE TABLE IF NOT EXISTS sessions (
    token_hash TEXT PRIMARY KEY,   -- sha256 of the cookie token; raw token is never stored
    user_id INTEGER NOT NULL,
    created_at REAL NOT NULL,
    expires_at REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS cash (
    user_id INTEGER NOT NULL,
    currency TEXT NOT NULL,
    initial REAL NOT NULL,
    balance REAL NOT NULL,
    reserved REAL NOT NULL DEFAULT 0,
    PRIMARY KEY (user_id, currency)
);
CREATE TABLE IF NOT EXISTS positions (
    user_id INTEGER NOT NULL,
    symbol TEXT NOT NULL,
    name TEXT,
    currency TEXT NOT NULL,
    qty INTEGER NOT NULL,
    avg_cost REAL NOT NULL,
    reserved_qty INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (user_id, symbol)
);
CREATE TABLE IF NOT EXISTS orders (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL,
    symbol TEXT NOT NULL,
    name TEXT,
    currency TEXT NOT NULL,
    side TEXT NOT NULL,          -- BUY | SELL
    type TEXT NOT NULL,          -- MARKET | LIMIT
    qty INTEGER NOT NULL,
    limit_price REAL,
    status TEXT NOT NULL,        -- PENDING | FILLED | CANCELLED
    reserved_amount REAL NOT NULL DEFAULT 0,
    fill_price REAL,
    created_at REAL NOT NULL,
    updated_at REAL NOT NULL,
    price_source TEXT
);
CREATE TABLE IF NOT EXISTS trades (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL,
    order_id INTEGER NOT NULL,
    symbol TEXT NOT NULL,
    name TEXT,
    currency TEXT NOT NULL,
    side TEXT NOT NULL,
    qty INTEGER NOT NULL,
    price REAL NOT NULL,
    amount REAL NOT NULL,
    realized_pnl REAL,
    executed_at REAL NOT NULL,
    price_source TEXT
);
CREATE INDEX IF NOT EXISTS ix_orders_user ON orders(user_id, status);
CREATE INDEX IF NOT EXISTS ix_trades_user ON trades(user_id);
CREATE TABLE IF NOT EXISTS fighter_matches (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    mode TEXT NOT NULL,
    player_username TEXT NOT NULL,
    opponent_username TEXT NOT NULL,
    winner TEXT NOT NULL,
    player_kos INTEGER NOT NULL DEFAULT 0,
    opponent_kos INTEGER NOT NULL DEFAULT 0,
    player_atk REAL, player_def REAL, player_spd REAL,
    opponent_atk REAL, opponent_def REAL, opponent_spd REAL,
    created_at REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_fighter_matches_player ON fighter_matches(player_username, created_at);
"""

USERNAME_RE = re.compile(r"^[A-Za-z0-9_\-\u4e00-\u9fff]{2,20}$")


class _Result:
    """Eagerly-fetched cursor result, so the connection lock is never held while callers iterate."""
    __slots__ = ("rows", "lastrowid")

    def __init__(self, rows, lastrowid):
        self.rows, self.lastrowid = rows, lastrowid

    def fetchone(self):
        return self.rows[0] if self.rows else None

    def fetchall(self):
        return self.rows

    def __iter__(self):
        return iter(self.rows)


class LockedDB:
    """One shared sqlite3 connection used from FastAPI's thread pool. sqlite3 connections are not
    safe for concurrent use, so every statement (and every BEGIN..COMMIT block, see Engine._tx)
    runs under a single re-entrant lock."""

    def __init__(self, con, lock):
        self.con, self.lock = con, lock

    def execute(self, sql, args=()):
        with self.lock:
            cur = self.con.execute(sql, args)
            return _Result(cur.fetchall(), cur.lastrowid)

    def executescript(self, sql):
        with self.lock:
            self.con.executescript(sql)


class Engine:
    def __init__(self, db_path, feed, initial_cash=None):
        self.feed = feed
        self.initial_cash = dict(initial_cash or DEFAULT_INITIAL_CASH)
        self.lock = threading.RLock()
        con = sqlite3.connect(db_path, check_same_thread=False, isolation_level=None)
        con.row_factory = sqlite3.Row
        self.db = LockedDB(con, self.lock)
        self.db.execute("PRAGMA journal_mode=WAL")
        self._migrate_pre_schema()
        self.db.executescript(SCHEMA)
        self._migrate_usd_only_capital()

    def _migrate_pre_schema(self):
        """v1 databases had a users table without auth columns: add them (legacy rows get NULL hash)."""
        cols = {r[1] for r in self.db.execute("PRAGMA table_info(users)")}
        if not cols:
            return
        adds = [
            ("password_hash", "ALTER TABLE users ADD COLUMN password_hash TEXT"),
            ("failed_logins", "ALTER TABLE users ADD COLUMN failed_logins INTEGER NOT NULL DEFAULT 0"),
            ("locked_until", "ALTER TABLE users ADD COLUMN locked_until REAL NOT NULL DEFAULT 0"),
            ("email", "ALTER TABLE users ADD COLUMN email TEXT"),
            ("email_verified", "ALTER TABLE users ADD COLUMN email_verified INTEGER NOT NULL DEFAULT 0"),
            ("google_sub", "ALTER TABLE users ADD COLUMN google_sub TEXT"),
        ]
        for col, ddl in adds:
            if col not in cols:
                self.db.execute(ddl)

    def _migrate_usd_only_capital(self):
        """One-shot: drop HKD wallets, set everyone to USD 1M starting capital, clear trades."""
        tables = {r[0] for r in self.db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        if "cash" not in tables or "users" not in tables:
            return
        usd_amt = float(self.initial_cash.get("USD", 1_000_000.0))
        need = bool(self.db.execute("SELECT 1 FROM cash WHERE currency = 'HKD' LIMIT 1").fetchone())
        need = need or bool(self.db.execute(
            "SELECT 1 FROM cash WHERE currency = 'USD' AND initial = ? LIMIT 1",
            (_LEGACY_USD_INITIAL,)).fetchone())
        if not need:
            for u in self.db.execute("SELECT id FROM users").fetchall():
                rows = self.db.execute(
                    "SELECT currency, initial FROM cash WHERE user_id = ?", (u["id"],)).fetchall()
                ccys = {r["currency"] for r in rows}
                if ccys != set(self.initial_cash) or any(
                        r["currency"] == "USD" and float(r["initial"]) != usd_amt for r in rows):
                    need = True
                    break
        if not need:
            return
        with self._tx() as db:
            db.execute("DELETE FROM positions")
            db.execute("DELETE FROM orders")
            db.execute("DELETE FROM trades")
            db.execute("DELETE FROM cash")
            now = _now()
            for u in db.execute("SELECT id FROM users").fetchall():
                for ccy, amt in self.initial_cash.items():
                    db.execute(
                        "INSERT INTO cash(user_id, currency, initial, balance, reserved) "
                        "VALUES (?,?,?,?,0)",
                        (u["id"], ccy, amt, amt))
                db.execute("UPDATE users SET reset_at = ? WHERE id = ?", (now, u["id"]))

    # ------------------------------------------------------------------ helpers
    def _tx(self):
        db, lock = self.db, self.lock

        class _T:
            def __enter__(s):
                lock.acquire()
                try:
                    db.execute("BEGIN IMMEDIATE")
                except BaseException:
                    lock.release()
                    raise
                return db

            def __exit__(s, et, ev, tb):
                try:
                    db.execute("ROLLBACK" if et else "COMMIT")
                finally:
                    lock.release()
                return False

        return _T()

    def _user(self, username):
        row = self.db.execute("SELECT * FROM users WHERE username = ?", (username,)).fetchone()
        if not row:
            raise TradingError(f"冇呢個用戶：{username}")
        return row

    def _quote(self, symbol):
        from .quotes import UnknownSymbol
        try:
            q = self.feed.quote(symbol)
        except UnknownSymbol as e:
            raise TradingError(str(e))
        if q.currency != currency_of(symbol):
            raise TradingError(f"{symbol} 以 {q.currency} 報價，暫時只支援美股 (USD)")
        if not q.price or q.price <= 0:
            raise TradingError(f"{symbol} 暫時冇有效報價")
        return q

    # ------------------------------------------------------------------ users
    @staticmethod
    def validate_username(username):
        username = (username or "").strip()
        if not USERNAME_RE.match(username):
            raise TradingError("用戶名要 2-20 個字，只可以用中英文、數字、_ 或 -")
        return username

    def create_user(self, username, password_hash, email=None, email_verified=0, google_sub=None):
        """Create a user with fresh virtual cash. Password hashing is done by the auth layer.
        password_hash may be None only for a Google-linked account."""
        username = self.validate_username(username)
        if not password_hash and not google_sub:
            raise TradingError("缺少密碼")
        with self.lock:
            if self.db.execute("SELECT 1 FROM users WHERE username = ?", (username,)).fetchone():
                raise TradingError("呢個用戶名已經有人用咗")
            if email and self.db.execute("SELECT 1 FROM users WHERE email = ?", (email,)).fetchone():
                raise TradingError("呢個電郵已經有人用咗")
            if google_sub and self.db.execute("SELECT 1 FROM users WHERE google_sub = ?", (google_sub,)).fetchone():
                raise TradingError("呢個 Google 帳戶已經連結咗")
            with self._tx() as db:
                now = _now()
                try:
                    cur = db.execute(
                        "INSERT INTO users(username, password_hash, email, email_verified, google_sub, created_at, reset_at) "
                        "VALUES (?,?,?,?,?,?,?)",
                        (username, password_hash or None, email, 1 if email_verified else 0, google_sub, now, now))
                except sqlite3.IntegrityError:
                    raise TradingError("呢個電郵或 Google 帳戶已經有人用咗")
                for ccy, amt in self.initial_cash.items():
                    db.execute("INSERT INTO cash(user_id, currency, initial, balance) VALUES (?,?,?,?)",
                               (cur.lastrowid, ccy, amt, amt))
            return {"id": cur.lastrowid, "username": username}

    def delete_user_data(self, db, user_id, username=None):
        for t in ("positions", "orders", "trades", "cash", "sessions", "password_resets"):
            db.execute(f"DELETE FROM {t} WHERE user_id = ?", (user_id,))
        if username:
            db.execute(
                "DELETE FROM fighter_matches WHERE player_username = ? OR opponent_username = ?",
                (username, username))
        db.execute("DELETE FROM users WHERE id = ?", (user_id,))

    def delete_user_by_credentials(self, username, email=None):
        """Delete one user and related rows. If email is given it must match (case-insensitive).
        Returns a short status string for logs; never touches other users."""
        username = (username or "").strip()
        if not username:
            return "skipped: empty username"
        email = (email or "").strip().lower() or None
        with self.lock:
            row = self.db.execute("SELECT id, username, email FROM users WHERE username = ?", (username,)).fetchone()
            if not row:
                return f"not_found: {username}"
            if email and (row["email"] or "").lower() != email:
                return f"email_mismatch: {username}"
            with self._tx() as db:
                self.delete_user_data(db, row["id"], username=row["username"])
            return f"deleted: id={row['id']} username={row['username']}"

    def admin_user_summary(self, user_id):
        """Privacy-safe admin lookup: no email / password / google_sub values."""
        try:
            user_id = int(user_id)
        except (TypeError, ValueError):
            return None
        with self.lock:
            row = self.db.execute(
                "SELECT id, username, created_at, email, google_sub FROM users WHERE id = ?",
                (user_id,),
            ).fetchone()
        if not row:
            return None
        return {
            "id": row["id"],
            "username": row["username"],
            "created_at": row["created_at"],
            "has_google": bool(row["google_sub"]),
            "has_email": bool(row["email"]),
        }

    def delete_user_by_id(self, user_id):
        """Delete one user by id and all related rows. Returns a status dict for the admin API."""
        try:
            user_id = int(user_id)
        except (TypeError, ValueError):
            return {"ok": False, "deleted": False, "error": "invalid_id"}
        with self.lock:
            row = self.db.execute(
                "SELECT id, username FROM users WHERE id = ?", (user_id,)
            ).fetchone()
            if not row:
                return {"ok": False, "deleted": False, "error": "not_found", "id": user_id}
            username = row["username"]
            with self._tx() as db:
                self.delete_user_data(db, row["id"], username=username)
            return {"ok": True, "deleted": True, "id": row["id"], "username": username}

    def rename_user(self, old_username, new_username):
        """Rename a user and update denormalized fighter_matches rows. Returns status string."""
        old_username = (old_username or "").strip()
        if not old_username:
            return "skipped: empty old username"
        new_username = self.validate_username(new_username)
        with self.lock:
            row = self.db.execute("SELECT id, username FROM users WHERE username = ?", (old_username,)).fetchone()
            if not row:
                return f"not_found: {old_username}"
            if row["username"] == new_username:
                return f"unchanged: {new_username}"
            if self.db.execute("SELECT 1 FROM users WHERE username = ?", (new_username,)).fetchone():
                return f"taken: {new_username}"
            old = row["username"]
            with self._tx() as db:
                db.execute("UPDATE users SET username=? WHERE id=?", (new_username, row["id"]))
                db.execute("UPDATE fighter_matches SET player_username=? WHERE player_username=?", (new_username, old))
                db.execute("UPDATE fighter_matches SET opponent_username=? WHERE opponent_username=?", (new_username, old))
                db.execute("UPDATE fighter_matches SET winner=? WHERE winner=?", (new_username, old))
            return f"renamed: {old} -> {new_username} (id={row['id']})"

    def migrate_google_numeric_usernames(self):
        """Privacy: Google-linked users whose public name is not u###### get a numeric handle."""
        import secrets
        numeric = re.compile(r"^u\d{6}$")
        changed = []
        with self.lock:
            rows = self.db.execute(
                "SELECT id, username FROM users WHERE google_sub IS NOT NULL AND google_sub != ''"
            ).fetchall()
            for row in rows:
                old = row["username"]
                if numeric.match(old or ""):
                    continue
                new = None
                for _ in range(64):
                    cand = "u" + f"{secrets.randbelow(1_000_000):06d}"
                    if not self.db.execute("SELECT 1 FROM users WHERE username = ?", (cand,)).fetchone():
                        new = cand
                        break
                if not new:
                    new = "u" + secrets.token_hex(3)
                with self._tx() as db:
                    db.execute("UPDATE users SET username=? WHERE id=?", (new, row["id"]))
                    db.execute("UPDATE fighter_matches SET player_username=? WHERE player_username=?", (new, old))
                    db.execute("UPDATE fighter_matches SET opponent_username=? WHERE opponent_username=?", (new, old))
                    db.execute("UPDATE fighter_matches SET winner=? WHERE winner=?", (new, old))
                changed.append(f"{old}->{new}")
        return changed

    def list_users(self):
        return [r["username"] for r in self.db.execute("SELECT username FROM users ORDER BY username")]

    def reset(self, username):
        with self.lock:
            u = self._user(username)
            with self._tx() as db:
                for t in ("positions", "orders", "trades"):
                    db.execute(f"DELETE FROM {t} WHERE user_id = ?", (u["id"],))
                db.execute("DELETE FROM cash WHERE user_id = ?", (u["id"],))
                for ccy, amt in self.initial_cash.items():
                    db.execute("INSERT INTO cash(user_id, currency, initial, balance) VALUES (?,?,?,?)",
                               (u["id"], ccy, amt, amt))
                db.execute("UPDATE users SET reset_at = ? WHERE id = ?", (_now(), u["id"]))

    # ------------------------------------------------------------------ orders
    def place_order(self, username, symbol, side, order_type, qty, limit_price=None):
        side = (side or "").upper()
        order_type = (order_type or "").upper()
        if side not in ("BUY", "SELL"):
            raise TradingError("買賣方向必須係 BUY 或 SELL")
        if order_type not in ("MARKET", "LIMIT"):
            raise TradingError("訂單類型必須係 MARKET（市價）或 LIMIT（限價）")
        try:
            symbol = normalize(symbol)
        except SymbolError as e:
            raise TradingError(str(e))
        if market_of(symbol) == "HK" or symbol.endswith(".HK"):
            raise TradingError(f"已唔再支援港股：{symbol}（請用美股代號）")
        try:
            qty_f = float(qty)
        except (TypeError, ValueError):
            raise TradingError("數量無效")
        if qty_f <= 0 or qty_f != int(qty_f):
            raise TradingError("數量必須係正整數")
        qty = int(qty_f)
        lot, _known = lot_size(symbol)
        if qty % lot:
            raise TradingError(f"{symbol} 每手 {lot} 股，數量必須係 {lot} 嘅倍數")
        if order_type == "LIMIT":
            try:
                limit_price = float(limit_price)
            except (TypeError, ValueError):
                raise TradingError("限價單要輸入限價")
            if limit_price <= 0:
                raise TradingError("限價必須大過 0")
            limit_price = round(limit_price, 3)
        else:
            limit_price = None

        q = self._quote(symbol)  # network call outside the lock
        with self.lock:
            u = self._user(username)
            ccy = currency_of(symbol)
            marketable = (order_type == "MARKET"
                          or (side == "BUY" and q.price <= limit_price)
                          or (side == "SELL" and q.price >= limit_price))
            check_price = q.price if marketable else limit_price
            with self._tx() as db:
                cash = db.execute("SELECT * FROM cash WHERE user_id=? AND currency=?", (u["id"], ccy)).fetchone()
                pos = db.execute("SELECT * FROM positions WHERE user_id=? AND symbol=?", (u["id"], symbol)).fetchone()
                if side == "BUY":
                    need = _r2(check_price * qty)
                    avail = _r2(cash["balance"] - cash["reserved"])
                    if need > avail + 1e-9:
                        raise TradingError(f"{ccy} 可用現金不足：需要 {need:,.2f}，可用 {avail:,.2f}")
                else:
                    held = (pos["qty"] - pos["reserved_qty"]) if pos else 0
                    if qty > held:
                        raise TradingError(f"可賣股數不足：想賣 {qty}，可賣 {held}")
                now = _now()
                cur = db.execute(
                    "INSERT INTO orders(user_id,symbol,name,currency,side,type,qty,limit_price,status,"
                    "created_at,updated_at,price_source) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                    (u["id"], symbol, q.name, ccy, side, order_type, qty, limit_price, "PENDING", now, now, q.source))
                oid = cur.lastrowid
                if marketable:
                    self._fill(db, oid, q.price, q.source)
                else:
                    if side == "BUY":
                        amt = _r2(limit_price * qty)
                        db.execute("UPDATE cash SET reserved = reserved + ? WHERE user_id=? AND currency=?",
                                   (amt, u["id"], ccy))
                        db.execute("UPDATE orders SET reserved_amount=? WHERE id=?", (amt, oid))
                    else:
                        db.execute("UPDATE positions SET reserved_qty = reserved_qty + ? WHERE user_id=? AND symbol=?",
                                   (qty, u["id"], symbol))
            return self.get_order(oid)

    def _fill(self, db, order_id, price, source, resting=False):
        """Execute an order at `price`. `resting=True` means it was a resting limit order whose
        cash / shares were reserved and must be released first."""
        o = db.execute("SELECT * FROM orders WHERE id=?", (order_id,)).fetchone()
        uid, sym, ccy, qty = o["user_id"], o["symbol"], o["currency"], o["qty"]
        if resting:
            if o["side"] == "BUY":
                db.execute("UPDATE cash SET reserved = MAX(ROUND(reserved - ?, 2), 0) WHERE user_id=? AND currency=?",
                           (o["reserved_amount"], uid, ccy))
            else:
                db.execute("UPDATE positions SET reserved_qty = MAX(reserved_qty - ?, 0) WHERE user_id=? AND symbol=?",
                           (qty, uid, sym))
        amount = _r2(price * qty)
        pos = db.execute("SELECT * FROM positions WHERE user_id=? AND symbol=?", (uid, sym)).fetchone()
        realized = None
        if o["side"] == "BUY":
            db.execute("UPDATE cash SET balance = ROUND(balance - ?, 2) WHERE user_id=? AND currency=?",
                       (amount, uid, ccy))
            if pos:
                new_qty = pos["qty"] + qty
                new_avg = (pos["qty"] * pos["avg_cost"] + amount) / new_qty
                db.execute("UPDATE positions SET qty=?, avg_cost=?, name=? WHERE user_id=? AND symbol=?",
                           (new_qty, new_avg, o["name"], uid, sym))
            else:
                db.execute("INSERT INTO positions(user_id,symbol,name,currency,qty,avg_cost) VALUES (?,?,?,?,?,?)",
                           (uid, sym, o["name"], ccy, qty, amount / qty))
        else:
            realized = _r2(amount - pos["avg_cost"] * qty)
            db.execute("UPDATE cash SET balance = ROUND(balance + ?, 2) WHERE user_id=? AND currency=?",
                       (amount, uid, ccy))
            left = pos["qty"] - qty
            if left == 0:
                db.execute("DELETE FROM positions WHERE user_id=? AND symbol=?", (uid, sym))
            else:
                db.execute("UPDATE positions SET qty=? WHERE user_id=? AND symbol=?", (left, uid, sym))
        now = _now()
        db.execute("UPDATE orders SET status='FILLED', fill_price=?, reserved_amount=0, updated_at=?, price_source=? "
                   "WHERE id=?", (price, now, source, order_id))
        db.execute("INSERT INTO trades(user_id,order_id,symbol,name,currency,side,qty,price,amount,realized_pnl,"
                   "executed_at,price_source) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                   (uid, order_id, sym, o["name"], ccy, o["side"], qty, price, amount, realized, now, source))

    def cancel_order(self, username, order_id):
        with self.lock:
            u = self._user(username)
            with self._tx() as db:
                o = db.execute("SELECT * FROM orders WHERE id=? AND user_id=?", (order_id, u["id"])).fetchone()
                if not o:
                    raise TradingError("搵唔到呢張訂單")
                if o["status"] != "PENDING":
                    raise TradingError("只可以取消未成交嘅訂單")
                if o["side"] == "BUY":
                    db.execute("UPDATE cash SET reserved = MAX(ROUND(reserved - ?, 2), 0) WHERE user_id=? AND currency=?",
                               (o["reserved_amount"], u["id"], o["currency"]))
                else:
                    db.execute("UPDATE positions SET reserved_qty = MAX(reserved_qty - ?, 0) "
                               "WHERE user_id=? AND symbol=?", (o["qty"], u["id"], o["symbol"]))
                db.execute("UPDATE orders SET status='CANCELLED', reserved_amount=0, updated_at=? WHERE id=?",
                           (_now(), order_id))
            return self.get_order(order_id)

    def process_pending(self):
        """Fill resting limit orders whose limit has been reached. Returns list of filled order ids."""
        pending = self.db.execute("SELECT id, symbol, side, limit_price FROM orders WHERE status='PENDING'").fetchall()
        quotes, filled = {}, []
        for o in pending:
            sym = o["symbol"]
            if sym not in quotes:
                try:
                    quotes[sym] = self.feed.quote(sym)
                except Exception:
                    quotes[sym] = None
            q = quotes[sym]
            if q is None:
                continue
            hit = (o["side"] == "BUY" and q.price <= o["limit_price"]) or \
                  (o["side"] == "SELL" and q.price >= o["limit_price"])
            if not hit:
                continue
            with self.lock:
                with self._tx() as db:
                    cur = db.execute("SELECT status FROM orders WHERE id=?", (o["id"],)).fetchone()
                    if cur and cur["status"] == "PENDING":
                        self._fill(db, o["id"], q.price, q.source, resting=True)
                        filled.append(o["id"])
        return filled

    # ------------------------------------------------------------------ queries
    def get_order(self, order_id):
        r = self.db.execute("SELECT * FROM orders WHERE id=?", (order_id,)).fetchone()
        return self._order_dict(r) if r else None

    @staticmethod
    def _order_dict(r):
        d = dict(r)
        d.pop("user_id", None)
        d["created_at_iso"] = _iso(d["created_at"])
        d["updated_at_iso"] = _iso(d["updated_at"])
        return d

    def orders(self, username, status=None, limit=200):
        u = self._user(username)
        sql, args = "SELECT * FROM orders WHERE user_id=?", [u["id"]]
        if status:
            sql += " AND status=?"
            args.append(status.upper())
        sql += " ORDER BY id DESC LIMIT ?"
        args.append(limit)
        return [self._order_dict(r) for r in self.db.execute(sql, args)]

    def trades(self, username, limit=200):
        u = self._user(username)
        out = []
        for r in self.db.execute("SELECT * FROM trades WHERE user_id=? ORDER BY id DESC LIMIT ?", (u["id"], limit)):
            d = dict(r)
            d.pop("user_id")
            d["executed_at_iso"] = _iso(d["executed_at"])
            out.append(d)
        return out

    def _fx(self):
        try:
            return float(self.feed.fx_usd_hkd())
        except Exception:
            return 7.8

    def portfolio(self, username, fx=None, quote_cache=None):
        u = self._user(username)
        fx = fx or self._fx()
        # Base currency is USD; keep HKD→USD for any leftover legacy cash rows.
        to_base = {"USD": 1.0, "HKD": (1.0 / fx) if fx else (1.0 / 7.8)}
        quote_cache = quote_cache if quote_cache is not None else {}
        positions = []
        mv_by_ccy = {c: 0.0 for c in ("USD", "HKD")}
        upnl_by_ccy = {c: 0.0 for c in ("USD", "HKD")}
        for p in self.db.execute("SELECT * FROM positions WHERE user_id=? ORDER BY currency, symbol", (u["id"],)):
            sym = p["symbol"]
            if sym not in quote_cache:
                try:
                    quote_cache[sym] = self.feed.quote(sym)
                except Exception:
                    quote_cache[sym] = None
            q = quote_cache[sym]
            price = q.price if q else p["avg_cost"]
            mv = price * p["qty"]
            cost = p["avg_cost"] * p["qty"]
            upnl = mv - cost
            mv_by_ccy[p["currency"]] += mv
            upnl_by_ccy[p["currency"]] += upnl
            positions.append({
                "symbol": sym, "name": p["name"], "currency": p["currency"], "market": market_of(sym),
                "qty": p["qty"], "reserved_qty": p["reserved_qty"], "available_qty": p["qty"] - p["reserved_qty"],
                "avg_cost": round(p["avg_cost"], 4), "price": price,
                "day_change_pct": round(q.change_pct, 2) if q else None,
                "cost": _r2(cost), "market_value": _r2(mv),
                "unrealized_pnl": _r2(upnl), "unrealized_pnl_pct": round(upnl / cost * 100, 2) if cost else 0.0,
                "price_source": q.source if q else "unavailable",
            })
        realized = {r["currency"]: r["s"] or 0.0 for r in self.db.execute(
            "SELECT currency, SUM(realized_pnl) s FROM trades WHERE user_id=? GROUP BY currency", (u["id"],))}
        accounts = []
        tot_equity = tot_initial = 0.0
        for c in self.db.execute("SELECT * FROM cash WHERE user_id=? ORDER BY currency", (u["id"],)):
            ccy = c["currency"]
            equity = c["balance"] + mv_by_ccy.get(ccy, 0.0)
            accounts.append({
                "currency": ccy, "initial": c["initial"], "cash": _r2(c["balance"]), "reserved": _r2(c["reserved"]),
                "available": _r2(c["balance"] - c["reserved"]), "market_value": _r2(mv_by_ccy.get(ccy, 0.0)),
                "equity": _r2(equity), "unrealized_pnl": _r2(upnl_by_ccy.get(ccy, 0.0)),
                "realized_pnl": _r2(realized.get(ccy, 0.0)),
                "return_pct": round((equity / c["initial"] - 1) * 100, 3) if c["initial"] else 0.0,
            })
            rate = to_base.get(ccy, 1.0)
            tot_equity += equity * rate
            tot_initial += c["initial"] * rate
        return {
            "username": u["username"],
            "base_currency": BASE_CURRENCY,
            "fx": {"USDHKD": fx},
            "accounts": accounts,
            "total": {"equity": _r2(tot_equity), "initial": _r2(tot_initial), "pnl": _r2(tot_equity - tot_initial),
                      "return_pct": round((tot_equity / tot_initial - 1) * 100, 3) if tot_initial else 0.0},
            "positions": positions,
        }

    def leaderboard(self):
        fx = self._fx()
        cache = {}
        rows = []
        for name in self.list_users():
            uid = self.db.execute("SELECT id FROM users WHERE username=?", (name,)).fetchone()
            p = self.portfolio(name, fx=fx, quote_cache=cache)
            n_trades = self.db.execute("SELECT COUNT(*) FROM trades t JOIN users u ON u.id=t.user_id "
                                       "WHERE u.username=?", (name,)).fetchone()[0]
            rows.append({"id": uid["id"] if uid else None, "username": name,
                         "equity": p["total"]["equity"], "initial": p["total"]["initial"],
                         "pnl": p["total"]["pnl"], "return_pct": p["total"]["return_pct"],
                         "positions": len(p["positions"]), "trades": n_trades})
        rows.sort(key=lambda r: (-r["return_pct"], r["username"].lower()))
        for i, r in enumerate(rows, 1):
            r["rank"] = i
        return {"base_currency": BASE_CURRENCY, "fx": {"USDHKD": fx}, "rows": rows, "as_of": _iso(_now())}

    def record_fighter_match(self, mode, player_username, opponent_username, winner,
                             player_kos, opponent_kos, player_stats, opponent_stats):
        """Store a 理財戰士 match result for later leaderboard / history."""
        now = _now()
        ps, os_ = player_stats or {}, opponent_stats or {}
        with self.lock:
            cur = self.db.execute(
                "INSERT INTO fighter_matches(mode,player_username,opponent_username,winner,"
                "player_kos,opponent_kos,player_atk,player_def,player_spd,"
                "opponent_atk,opponent_def,opponent_spd,created_at) "
                "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (mode, player_username, opponent_username, winner,
                 int(player_kos), int(opponent_kos),
                 ps.get("atk"), ps.get("def"), ps.get("spd"),
                 os_.get("atk"), os_.get("def"), os_.get("spd"), now))
            return {"id": cur.lastrowid, "created_at": now, "created_at_iso": _iso(now)}

    def recent_fighter_matches(self, username, limit=20):
        rows = self.db.execute(
            "SELECT * FROM fighter_matches WHERE player_username=? OR opponent_username=? "
            "ORDER BY id DESC LIMIT ?", (username, username, limit)).fetchall()
        out = []
        for r in rows:
            d = dict(r)
            d["created_at_iso"] = _iso(d["created_at"])
            out.append(d)
        return out
