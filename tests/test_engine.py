import pytest

from app.engine import Engine, TradingError
from app.quotes import RANGES, SimFeed
from app.symbols import lot_size, normalize


def acct(p, ccy):
    return next(a for a in p["accounts"] if a["currency"] == ccy)


def pos(p, sym):
    return next((x for x in p["positions"] if x["symbol"] == sym), None)


# ---------------------------------------------------------------- symbols
@pytest.mark.parametrize("raw,exp", [("700", "0700.HK"), ("0700", "0700.HK"), ("00700.hk", "0700.HK"),
                                     ("9988.HK", "9988.HK"), ("aapl", "AAPL"), ("brk.b", "BRK-B")])
def test_normalize(raw, exp):
    assert normalize(raw) == exp


def test_lot_sizes():
    assert lot_size("0700.HK") == (100, True)
    assert lot_size("0005.HK") == (400, True)
    assert lot_size("AAPL") == (1, True)
    assert lot_size("6666.HK") == (100, False)


# ---------------------------------------------------------------- users
def test_new_user_gets_initial_cash(eng):
    p = eng.portfolio("alice")
    assert acct(p, "HKD")["cash"] == 1_000_000 and acct(p, "USD")["cash"] == 100_000
    assert p["positions"] == []
    assert p["total"]["return_pct"] == 0


def test_create_user_duplicate_and_invalid(eng):
    assert eng.create_user("bob", "h")["username"] == "bob"
    with pytest.raises(TradingError, match="已經有人用"):
        eng.create_user("ALICE", "h")          # usernames are case-insensitive
    for bad in ("x", "bad name!", "a" * 21, ""):
        with pytest.raises(TradingError):
            eng.create_user(bad, "h")
    with pytest.raises(TradingError):
        eng.create_user("nohash", "")
    with pytest.raises(TradingError):
        eng.portfolio("nobody")


# ---------------------------------------------------------------- market orders
def test_market_buy_then_sell_hk_no_fees(eng, feed):
    o = eng.place_order("alice", "700", "BUY", "MARKET", 200)
    assert o["status"] == "FILLED" and o["fill_price"] == 400.0 and o["symbol"] == "0700.HK"
    p = eng.portfolio("alice")
    assert acct(p, "HKD")["cash"] == 1_000_000 - 80_000      # no fees
    assert acct(p, "USD")["cash"] == 100_000                   # other wallet untouched
    x = pos(p, "0700.HK")
    assert x["qty"] == 200 and x["avg_cost"] == 400.0

    feed.prices["0700.HK"] = 450.0
    p = eng.portfolio("alice")
    x = pos(p, "0700.HK")
    assert x["market_value"] == 90_000 and x["unrealized_pnl"] == 10_000 and x["unrealized_pnl_pct"] == 12.5
    assert acct(p, "HKD")["equity"] == 1_010_000

    s = eng.place_order("alice", "0700.HK", "SELL", "MARKET", 100)
    assert s["status"] == "FILLED"
    p = eng.portfolio("alice")
    assert acct(p, "HKD")["cash"] == 1_000_000 - 80_000 + 45_000
    assert pos(p, "0700.HK")["qty"] == 100
    assert acct(p, "HKD")["realized_pnl"] == 5_000
    trades = eng.trades("alice")
    assert [t["side"] for t in trades] == ["SELL", "BUY"]
    assert trades[0]["realized_pnl"] == 5_000

    eng.place_order("alice", "0700.HK", "SELL", "MARKET", 100)
    p = eng.portfolio("alice")
    assert pos(p, "0700.HK") is None
    assert acct(p, "HKD")["cash"] == 1_010_000
    assert acct(p, "HKD")["realized_pnl"] == 10_000


def test_round_trip_same_price_returns_exact_cash(eng):
    eng.place_order("alice", "AAPL", "BUY", "MARKET", 7)
    eng.place_order("alice", "AAPL", "SELL", "MARKET", 7)
    assert acct(eng.portfolio("alice"), "USD")["cash"] == 100_000


def test_average_cost(eng, feed):
    eng.place_order("alice", "AAPL", "BUY", "MARKET", 10)
    feed.prices["AAPL"] = 260.0
    eng.place_order("alice", "AAPL", "BUY", "MARKET", 30)
    x = pos(eng.portfolio("alice"), "AAPL")
    assert x["qty"] == 40 and x["avg_cost"] == pytest.approx((10 * 200 + 30 * 260) / 40)
    assert acct(eng.portfolio("alice"), "USD")["cash"] == 100_000 - 2_000 - 7_800


def test_us_trades_use_usd(eng):
    eng.place_order("alice", "NVDA", "BUY", "MARKET", 100)
    p = eng.portfolio("alice")
    assert acct(p, "USD")["cash"] == 85_000 and acct(p, "HKD")["cash"] == 1_000_000
    assert pos(p, "NVDA")["currency"] == "USD"


# ---------------------------------------------------------------- validation
def test_board_lot_enforced(eng):
    with pytest.raises(TradingError, match="每手 100"):
        eng.place_order("alice", "0700.HK", "BUY", "MARKET", 150)
    with pytest.raises(TradingError, match="每手 400"):
        eng.place_order("alice", "0005.HK", "BUY", "MARKET", 100)
    assert eng.place_order("alice", "0005.HK", "BUY", "MARKET", 800)["status"] == "FILLED"


def test_insufficient_cash(eng):
    with pytest.raises(TradingError, match="現金不足"):
        eng.place_order("alice", "TSLA", "BUY", "MARKET", 334)  # 100,200 > 100,000
    assert eng.place_order("alice", "TSLA", "BUY", "MARKET", 333)["status"] == "FILLED"


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
    assert a["cash"] == 100_000 and a["reserved"] == 18_000 and a["available"] == 82_000
    # reserved cash can't be spent twice
    with pytest.raises(TradingError, match="現金不足"):
        eng.place_order("alice", "AAPL", "BUY", "MARKET", 411)  # 82,200 > 82,000
    assert eng.process_pending() == []                        # price still 200
    feed.prices["AAPL"] = 175.0
    assert eng.process_pending() == [o["id"]]
    filled = eng.get_order(o["id"])
    assert filled["status"] == "FILLED" and filled["fill_price"] == 175.0
    a = acct(eng.portfolio("alice"), "USD")
    assert a["reserved"] == 0 and a["cash"] == 100_000 - 17_500
    assert pos(eng.portfolio("alice"), "AAPL")["qty"] == 100


def test_resting_limit_sell_reserves_shares_and_cancel(eng, feed):
    eng.place_order("alice", "9988.HK", "BUY", "MARKET", 300)
    o = eng.place_order("alice", "9988.HK", "SELL", "LIMIT", 200, 150)
    assert o["status"] == "PENDING"
    x = pos(eng.portfolio("alice"), "9988.HK")
    assert x["reserved_qty"] == 200 and x["available_qty"] == 100
    with pytest.raises(TradingError, match="可賣股數不足"):
        eng.place_order("alice", "9988.HK", "SELL", "MARKET", 200)
    eng.cancel_order("alice", o["id"])
    assert eng.get_order(o["id"])["status"] == "CANCELLED"
    assert pos(eng.portfolio("alice"), "9988.HK")["available_qty"] == 300
    with pytest.raises(TradingError):
        eng.cancel_order("alice", o["id"])


def test_resting_limit_sell_fills(eng, feed):
    eng.place_order("alice", "9988.HK", "BUY", "MARKET", 300)
    o = eng.place_order("alice", "9988.HK", "SELL", "LIMIT", 300, 150)
    feed.prices["9988.HK"] = 151.0
    assert eng.process_pending() == [o["id"]]
    p = eng.portfolio("alice")
    assert pos(p, "9988.HK") is None
    assert acct(p, "HKD")["cash"] == 1_000_000 - 39_000 + 45_300
    assert acct(p, "HKD")["realized_pnl"] == 6_300


def test_cancel_buy_releases_cash(eng):
    o = eng.place_order("alice", "TSLA", "BUY", "LIMIT", 10, 250)
    eng.cancel_order("alice", o["id"])
    a = acct(eng.portfolio("alice"), "USD")
    assert a["reserved"] == 0 and a["available"] == 100_000


# ---------------------------------------------------------------- multi-user, reset, leaderboard
def test_users_are_isolated(eng):
    eng.create_user("bob", "h")
    eng.place_order("alice", "AAPL", "BUY", "MARKET", 10)
    assert acct(eng.portfolio("bob"), "USD")["cash"] == 100_000
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
    assert acct(p, "USD")["cash"] == 100_000 and acct(p, "USD")["reserved"] == 0


def test_leaderboard_ranks_by_return_in_hkd(eng, feed):
    feed.fx = 7.8
    for u in ("bob", "carol"):
        eng.create_user(u, "h")
    eng.place_order("alice", "AAPL", "BUY", "MARKET", 100)    # USD 20,000 in AAPL
    eng.place_order("bob", "0700.HK", "BUY", "MARKET", 1000)  # HKD 400,000 in Tencent
    feed.prices["AAPL"] = 220.0     # alice +USD 2,000 = +HKD 15,600
    feed.prices["0700.HK"] = 380.0  # bob -HKD 20,000
    lb = eng.leaderboard()
    assert [r["username"] for r in lb["rows"]] == ["alice", "carol", "bob"]
    assert [r["rank"] for r in lb["rows"]] == [1, 2, 3]
    initial = 1_000_000 + 100_000 * 7.8
    a, c, b = lb["rows"]
    assert a["initial"] == initial and a["equity"] == pytest.approx(initial + 15_600)
    assert a["return_pct"] == pytest.approx(round(15_600 / initial * 100, 3))
    assert b["pnl"] == -20_000 and c["return_pct"] == 0
    assert lb["base_currency"] == "HKD" and lb["fx"]["USDHKD"] == 7.8


def test_fx_change_does_not_change_return(eng, feed):
    feed.fx = 7.75
    assert eng.portfolio("alice")["total"]["return_pct"] == 0


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
    q = f.quote("0700.HK")
    assert q.source == "simulated" and q.currency == "HKD" and q.price > 0
    for r in RANGES:
        h = f.history("AAPL", r)
        assert h["source"] == "simulated" and len(h["points"]) > 10
        assert all(p[1] > 0 for p in h["points"])
