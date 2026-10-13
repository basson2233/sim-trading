import pytest

from app.engine import DEFAULT_INITIAL_CASH, Engine, TradingError
from app.quotes import RANGES, SimFeed
from app.symbols import SymbolError, lot_size, normalize

USD0 = DEFAULT_INITIAL_CASH["USD"]


def acct(p, ccy):
    return next(a for a in p["accounts"] if a["currency"] == ccy)


def pos(p, sym):
    return next((x for x in p["positions"] if x["symbol"] == sym), None)


# ---------------------------------------------------------------- symbols
@pytest.mark.parametrize("raw,exp", [("aapl", "AAPL"), ("brk.b", "BRK-B"), ("NVDA", "NVDA"), ("spy", "SPY")])
def test_normalize(raw, exp):
    assert normalize(raw) == exp


@pytest.mark.parametrize("raw", ["700", "0700", "0700.HK", "9988.HK", "00700.hk"])
def test_normalize_rejects_hk(raw):
    with pytest.raises(SymbolError, match="港股"):
        normalize(raw)


def test_lot_sizes():
    assert lot_size("AAPL") == (1, True)
    assert lot_size("NVDA") == (1, True)


# ---------------------------------------------------------------- users
def test_new_user_gets_initial_cash(eng):
    p = eng.portfolio("alice")
    assert [a["currency"] for a in p["accounts"]] == ["USD"]
    assert acct(p, "USD")["cash"] == USD0 == 1_000_000.0
    assert p["positions"] == []
    assert p["total"]["return_pct"] == 0
    assert p["base_currency"] == "USD"


def test_create_user_duplicate_and_invalid(eng):
    assert eng.create_user("bob", "h")["username"] == "bob"
    with pytest.raises(TradingError, match="已經有人用"):
        eng.create_user("ALICE", "h")
    for bad in ("x", "bad name!", "a" * 21, ""):
        with pytest.raises(TradingError):
            eng.create_user(bad, "h")
    with pytest.raises(TradingError):
        eng.create_user("nohash", "")
    with pytest.raises(TradingError):
        eng.portfolio("nobody")


# ---------------------------------------------------------------- market orders
def test_market_buy_then_sell_us_no_fees(eng, feed):
    o = eng.place_order("alice", "AAPL", "BUY", "MARKET", 100)
    assert o["status"] == "FILLED" and o["fill_price"] == 200.0 and o["symbol"] == "AAPL"
    p = eng.portfolio("alice")
    assert acct(p, "USD")["cash"] == USD0 - 20_000
    assert len(p["accounts"]) == 1
    x = pos(p, "AAPL")
    assert x["qty"] == 100 and x["avg_cost"] == 200.0

    feed.prices["AAPL"] = 220.0
    p = eng.portfolio("alice")
    x = pos(p, "AAPL")
    assert x["market_value"] == 22_000 and x["unrealized_pnl"] == 2_000
    assert acct(p, "USD")["equity"] == USD0 + 2_000

    s = eng.place_order("alice", "AAPL", "SELL", "MARKET", 50)
    assert s["status"] == "FILLED"
    p = eng.portfolio("alice")
    assert acct(p, "USD")["cash"] == USD0 - 20_000 + 11_000
    assert pos(p, "AAPL")["qty"] == 50
    assert acct(p, "USD")["realized_pnl"] == 1_000

    eng.place_order("alice", "AAPL", "SELL", "MARKET", 50)
    p = eng.portfolio("alice")
    assert pos(p, "AAPL") is None
    assert acct(p, "USD")["cash"] == USD0 + 2_000
    assert acct(p, "USD")["realized_pnl"] == 2_000


def test_round_trip_same_price_returns_exact_cash(eng):
    eng.place_order("alice", "AAPL", "BUY", "MARKET", 7)
    eng.place_order("alice", "AAPL", "SELL", "MARKET", 7)
    assert acct(eng.portfolio("alice"), "USD")["cash"] == USD0


def test_average_cost(eng, feed):
    eng.place_order("alice", "AAPL", "BUY", "MARKET", 10)
    feed.prices["AAPL"] = 260.0
    eng.place_order("alice", "AAPL", "BUY", "MARKET", 30)
    x = pos(eng.portfolio("alice"), "AAPL")
    assert x["qty"] == 40 and x["avg_cost"] == pytest.approx((10 * 200 + 30 * 260) / 40)
    assert acct(eng.portfolio("alice"), "USD")["cash"] == USD0 - 2_000 - 7_800


def test_us_trades_use_usd(eng):
    eng.place_order("alice", "NVDA", "BUY", "MARKET", 100)
    p = eng.portfolio("alice")
    assert acct(p, "USD")["cash"] == USD0 - 15_000
    assert pos(p, "NVDA")["currency"] == "USD"


def test_hk_symbols_rejected(eng):
    with pytest.raises(TradingError, match="港股"):
        eng.place_order("alice", "0700.HK", "BUY", "MARKET", 100)
    with pytest.raises(TradingError, match="港股"):
        eng.place_order("alice", "700", "BUY", "MARKET", 100)


# ---------------------------------------------------------------- validation
def test_insufficient_cash(eng):
    # TSLA @ 300; 1_000_000 / 300 ≈ 3333.33
    with pytest.raises(TradingError, match="現金不足"):
        eng.place_order("alice", "TSLA", "BUY", "MARKET", 3334)
    assert eng.place_order("alice", "TSLA", "BUY", "MARKET", 3333)["status"] == "FILLED"


def test_insufficient_shares(eng):
    with pytest.raises(TradingError, match="可賣股數不足"):
        eng.place_order("alice", "AAPL", "SELL", "MARKET", 1)
    eng.place_order("alice", "AAPL", "BUY", "MARKET", 5)
    with pytest.raises(TradingError, match="可賣股數不足"):
        eng.place_order("alice", "AAPL", "SELL", "MARKET", 6)


def test_bad_inputs(eng):
    for args in [("AAPL", "HOLD", "MARKET", 1), ("AAPL", "BUY", "STOP", 1), ("AAPL", "BUY", "MARKET", 0),
                 ("AAPL", "BUY", "MARKET", 1.5), ("AAPL", "BUY", "LIMIT", 1), ("ZZZZ", "BUY", "MARKET", 1),
                 ("$$$", "BUY", "MARKET", 1)]:
        with pytest.raises(TradingError):
            eng.place_order("alice", *args)
    assert eng.orders("alice") == []


# ---------------------------------------------------------------- limit orders
def test_marketable_limit_fills_immediately_at_market(eng):
    o = eng.place_order("alice", "AAPL", "BUY", "LIMIT", 10, 210)
    assert o["status"] == "FILLED" and o["fill_price"] == 200.0


def test_resting_limit_buy_reserves_then_fills(eng, feed):
    o = eng.place_order("alice", "AAPL", "BUY", "LIMIT", 100, 180)
    assert o["status"] == "PENDING"
    a = acct(eng.portfolio("alice"), "USD")
    assert a["cash"] == USD0 and a["reserved"] == 18_000 and a["available"] == USD0 - 18_000
    with pytest.raises(TradingError, match="現金不足"):
        eng.place_order("alice", "AAPL", "BUY", "MARKET", int((USD0 - 18_000) // 200) + 1)
    assert eng.process_pending() == []
    feed.prices["AAPL"] = 175.0
    assert eng.process_pending() == [o["id"]]
    filled = eng.get_order(o["id"])
    assert filled["status"] == "FILLED" and filled["fill_price"] == 175.0
    a = acct(eng.portfolio("alice"), "USD")
    assert a["reserved"] == 0 and a["cash"] == USD0 - 17_500
    assert pos(eng.portfolio("alice"), "AAPL")["qty"] == 100


def test_resting_limit_sell_reserves_shares_and_cancel(eng, feed):
    eng.place_order("alice", "NVDA", "BUY", "MARKET", 300)
    o = eng.place_order("alice", "NVDA", "SELL", "LIMIT", 200, 160)
    assert o["status"] == "PENDING"
    x = pos(eng.portfolio("alice"), "NVDA")
    assert x["reserved_qty"] == 200 and x["available_qty"] == 100
    with pytest.raises(TradingError, match="可賣股數不足"):
        eng.place_order("alice", "NVDA", "SELL", "MARKET", 200)
    eng.cancel_order("alice", o["id"])
    assert eng.get_order(o["id"])["status"] == "CANCELLED"
    assert pos(eng.portfolio("alice"), "NVDA")["available_qty"] == 300
    with pytest.raises(TradingError):
        eng.cancel_order("alice", o["id"])


def test_resting_limit_sell_fills(eng, feed):
    eng.place_order("alice", "NVDA", "BUY", "MARKET", 300)
    o = eng.place_order("alice", "NVDA", "SELL", "LIMIT", 300, 160)
    feed.prices["NVDA"] = 165.0
    assert eng.process_pending() == [o["id"]]
    p = eng.portfolio("alice")
    assert pos(p, "NVDA") is None
    assert acct(p, "USD")["cash"] == USD0 - 45_000 + 49_500
    assert acct(p, "USD")["realized_pnl"] == 4_500


def test_cancel_buy_releases_cash(eng):
    o = eng.place_order("alice", "TSLA", "BUY", "LIMIT", 10, 250)
    eng.cancel_order("alice", o["id"])
    a = acct(eng.portfolio("alice"), "USD")
    assert a["reserved"] == 0 and a["available"] == USD0


# ---------------------------------------------------------------- multi-user, reset, leaderboard
def test_users_are_isolated(eng):
    eng.create_user("bob", "h")
    eng.place_order("alice", "AAPL", "BUY", "MARKET", 10)
    assert acct(eng.portfolio("bob"), "USD")["cash"] == USD0
    assert eng.trades("bob") == []
    o = eng.place_order("alice", "AAPL", "BUY", "LIMIT", 1, 1)
    with pytest.raises(TradingError):
        eng.cancel_order("bob", o["id"])


def test_reset(eng):
    eng.place_order("alice", "AAPL", "BUY", "MARKET", 10)
    eng.place_order("alice", "AAPL", "BUY", "LIMIT", 1, 1)
    eng.reset("alice")
    p = eng.portfolio("alice")
    assert p["positions"] == [] and eng.orders("alice") == [] and eng.trades("alice") == []
    assert acct(p, "USD")["cash"] == USD0 and acct(p, "USD")["reserved"] == 0


def test_leaderboard_ranks_by_return(eng, feed):
    for u in ("bob", "carol"):
        eng.create_user(u, "h")
    eng.place_order("alice", "AAPL", "BUY", "MARKET", 100)    # USD 20,000 in AAPL
    eng.place_order("bob", "NVDA", "BUY", "MARKET", 200)      # USD 30,000 in NVDA
    feed.prices["AAPL"] = 220.0     # alice +USD 2,000
    feed.prices["NVDA"] = 140.0     # bob -USD 2,000
    lb = eng.leaderboard()
    assert [r["username"] for r in lb["rows"]] == ["alice", "carol", "bob"]
    assert [r["rank"] for r in lb["rows"]] == [1, 2, 3]
    a, c, b = lb["rows"]
    assert a["initial"] == USD0 and a["equity"] == pytest.approx(USD0 + 2_000)
    assert a["return_pct"] == pytest.approx(round(2_000 / USD0 * 100, 3))
    assert b["pnl"] == pytest.approx(-2_000) and c["return_pct"] == 0
    assert lb["base_currency"] == "USD"


def test_fx_change_does_not_change_return(eng, feed):
    feed.fx = 7.75
    assert eng.portfolio("alice")["total"]["return_pct"] == 0


def test_migrate_usd_only_capital_resets_everyone(tmp_path, feed):
    import sqlite3
    db = str(tmp_path / "legacy.db")
    con = sqlite3.connect(db)
    con.executescript("""
        CREATE TABLE users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT NOT NULL UNIQUE COLLATE NOCASE,
            password_hash TEXT,
            email TEXT,
            email_verified INTEGER NOT NULL DEFAULT 0,
            google_sub TEXT,
            failed_logins INTEGER NOT NULL DEFAULT 0,
            locked_until REAL NOT NULL DEFAULT 0,
            created_at REAL NOT NULL,
            reset_at REAL NOT NULL
        );
        CREATE TABLE cash (
            user_id INTEGER NOT NULL, currency TEXT NOT NULL, initial REAL NOT NULL,
            balance REAL NOT NULL, reserved REAL NOT NULL DEFAULT 0,
            PRIMARY KEY (user_id, currency)
        );
        CREATE TABLE positions (
            user_id INTEGER NOT NULL, symbol TEXT NOT NULL, name TEXT, currency TEXT NOT NULL,
            qty INTEGER NOT NULL, avg_cost REAL NOT NULL, reserved_qty INTEGER NOT NULL DEFAULT 0,
            PRIMARY KEY (user_id, symbol)
        );
        CREATE TABLE orders (
            id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER NOT NULL, symbol TEXT NOT NULL,
            name TEXT, currency TEXT NOT NULL, side TEXT NOT NULL, type TEXT NOT NULL,
            qty INTEGER NOT NULL, limit_price REAL, status TEXT NOT NULL,
            reserved_amount REAL NOT NULL DEFAULT 0, fill_price REAL,
            created_at REAL NOT NULL, updated_at REAL NOT NULL, price_source TEXT
        );
        CREATE TABLE trades (
            id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER NOT NULL, order_id INTEGER NOT NULL,
            symbol TEXT NOT NULL, name TEXT, currency TEXT NOT NULL, side TEXT NOT NULL,
            qty INTEGER NOT NULL, price REAL NOT NULL, amount REAL NOT NULL,
            realized_pnl REAL, executed_at REAL NOT NULL, price_source TEXT
        );
        INSERT INTO users(username, password_hash, created_at, reset_at)
            VALUES ('alice', 'h', 1, 1);
        INSERT INTO cash VALUES (1, 'HKD', 500000, 500000, 0);
        INSERT INTO cash VALUES (1, 'USD', 64000, 50000, 0);
        INSERT INTO positions VALUES (1, 'AAPL', 'Apple', 'USD', 10, 200, 0);
    """)
    con.commit(); con.close()
    e = Engine(db, feed)
    p = e.portfolio("alice")
    assert [a["currency"] for a in p["accounts"]] == ["USD"]
    assert acct(p, "USD")["cash"] == USD0 and acct(p, "USD")["initial"] == USD0
    assert p["positions"] == [] and e.orders("alice") == [] and e.trades("alice") == []
    # second open does not wipe a traded account that already has USD 1M initial
    e.place_order("alice", "AAPL", "BUY", "MARKET", 5)
    e2 = Engine(db, feed)
    assert pos(e2.portfolio("alice"), "AAPL")["qty"] == 5


def test_persistence(tmp_path, feed):
    db = str(tmp_path / "t.db")
    e1 = Engine(db, feed)
    e1.create_user("dave", "h")
    e1.place_order("dave", "AAPL", "BUY", "MARKET", 3)
    e2 = Engine(db, feed)
    assert pos(e2.portfolio("dave"), "AAPL")["qty"] == 3


# ---------------------------------------------------------------- simulated feed
def test_sim_feed_quote_and_all_chart_ranges():
    f = SimFeed()
    q = f.quote("AAPL")
    assert q.source == "simulated" and q.currency == "USD" and q.price > 0
    for r in RANGES:
        h = f.history("AAPL", r)
        assert h["source"] == "simulated" and len(h["points"]) > 10
        assert all(p[1] > 0 for p in h["points"])
