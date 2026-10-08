"""Paper-trading engine: users, cash, positions, orders, trades, leaderboard.

Design
- Each user holds two separate cash wallets: HKD (for HK stocks) and USD (for US stocks).
  A HK stock can only be bought with HKD, a US stock with USD -> no FX in trading.
- For the leaderboard / combined totals only, USD is converted to HKD (base currency)
  at the current USD/HKD rate. The *initial* capital is converted at the same rate, so
  FX moves do not change anyone's return %; ranking reflects trading performance only.
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
DEFAULT_INITIAL_CASH = {"HKD": 1_000_000.0, "USD": 100_000.0}
BASE_CURRENCY = "HKD"


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
            raise TradingError(f"{symbol} 以 {q.currency} 報價，暫時只支援港股 (HKD) 同美股 (USD)")
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

    def delete_user_data(self, db, user_id):
        for t in ("positions", "orders", "trades", "cash", "sessions", "password_resets"):
            db.execute(f"DELETE FROM {t} WHERE user_id = ?", (user_id,))
        db.execute("DELETE FROM users WHERE id = ?", (user_id,))

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
        to_base = {"HKD": 1.0, "USD": fx}
        quote_cache = quote_cache if quote_cache is not None else {}
        positions = []
        mv_by_ccy = {c: 0.0 for c in self.initial_cash}
        upnl_by_ccy = {c: 0.0 for c in self.initial_cash}
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
            tot_equity += equity * to_base[ccy]
            tot_initial += c["initial"] * to_base[ccy]
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
            p = self.portfolio(name, fx=fx, quote_cache=cache)
            n_trades = self.db.execute("SELECT COUNT(*) FROM trades t JOIN users u ON u.id=t.user_id "
                                       "WHERE u.username=?", (name,)).fetchone()[0]
            rows.append({"username": name, "equity": p["total"]["equity"], "initial": p["total"]["initial"],
                         "pnl": p["total"]["pnl"], "return_pct": p["total"]["return_pct"],
                         "positions": len(p["positions"]), "trades": n_trades})
        rows.sort(key=lambda r: (-r["return_pct"], r["username"].lower()))
        for i, r in enumerate(rows, 1):
            r["rank"] = i
        return {"base_currency": BASE_CURRENCY, "fx": {"USDHKD": fx}, "rows": rows, "as_of": _iso(_now())}
