"""Unit tests: US session boundaries + MARKET rejection in PRE/AFTER/CLOSED."""
from datetime import datetime
from zoneinfo import ZoneInfo

import pytest

from app.engine import Engine, TradingError
from app.market_session import (
    SESSION_AFTER,
    SESSION_CLOSED,
    SESSION_PRE,
    SESSION_RTH,
    allow_market_orders,
    is_open_for_matching,
    market_session_info,
    session_at,
)
from app.quotes import _pick_yahoo_price

ET = ZoneInfo("America/New_York")


def _et(y, m, d, hh, mm, ss=0):
    return datetime(y, m, d, hh, mm, ss, tzinfo=ET)


# Monday 2026-11-02 is a weekday
@pytest.mark.parametrize(
    "dt,expect",
    [
        (_et(2026, 11, 2, 3, 59), SESSION_CLOSED),
        (_et(2026, 11, 2, 4, 0), SESSION_PRE),
        (_et(2026, 11, 2, 9, 29), SESSION_PRE),
        (_et(2026, 11, 2, 9, 30), SESSION_RTH),
        (_et(2026, 11, 2, 15, 59), SESSION_RTH),
        (_et(2026, 11, 2, 16, 0), SESSION_AFTER),
        (_et(2026, 11, 2, 19, 59), SESSION_AFTER),
        (_et(2026, 11, 2, 20, 0), SESSION_CLOSED),
        (_et(2026, 11, 2, 23, 0), SESSION_CLOSED),
        # weekend
        (_et(2026, 11, 7, 12, 0), SESSION_CLOSED),  # Saturday
        (_et(2026, 11, 8, 10, 0), SESSION_CLOSED),  # Sunday
    ],
)
def test_session_boundaries(dt, expect):
    assert session_at(dt) == expect


def test_allow_market_orders_rules():
    assert allow_market_orders(SESSION_RTH) is True
    assert allow_market_orders(SESSION_PRE) is False
    assert allow_market_orders(SESSION_AFTER) is False
    assert allow_market_orders(SESSION_CLOSED) is False
    assert allow_market_orders(SESSION_RTH, force_extended=True) is False


def test_is_open_for_matching():
    assert is_open_for_matching(SESSION_PRE)
    assert is_open_for_matching(SESSION_RTH)
    assert is_open_for_matching(SESSION_AFTER)
    assert not is_open_for_matching(SESSION_CLOSED)


def test_market_session_info_shape():
    info = market_session_info(_et(2026, 11, 2, 10, 0))
    d = info.to_dict()
    assert d["session"] == SESSION_RTH
    assert d["exchange_tz"] == "America/New_York"
    assert d["extended_hours_supported"] is True
    assert d["overnight_supported"] is False
    assert "2026-11-02" in d["server_time_et"]


def test_pick_yahoo_price_extended_and_fallback():
    meta = {
        "regularMarketPrice": 100.0,
        "regularMarketTime": 1_700_000_000,
        "preMarketPrice": 101.5,
        "preMarketTime": 1_700_000_100,
        "postMarketPrice": 99.2,
        "postMarketTime": 1_700_000_200,
    }
    p, src, _ = _pick_yahoo_price(meta, SESSION_PRE)
    assert (p, src) == (101.5, "extended")
    p, src, _ = _pick_yahoo_price(meta, SESSION_AFTER)
    assert (p, src) == (99.2, "extended")
    p, src, _ = _pick_yahoo_price(meta, SESSION_RTH)
    assert (p, src) == (100.0, "regular")

    meta2 = {"regularMarketPrice": 100.0, "regularMarketTime": 1}
    p, src, _ = _pick_yahoo_price(meta2, SESSION_PRE)
    assert (p, src) == (100.0, "regular_fallback")


def test_reject_market_in_pre(feed):
    eng = Engine(":memory:", feed, session_fn=lambda: SESSION_PRE)
    feed.session = SESSION_PRE
    feed.price_source = "extended"
    eng.create_user("alice", "h")
    with pytest.raises(TradingError, match="限價"):
        eng.place_order("alice", "AAPL", "BUY", "MARKET", 1)


def test_reject_market_in_after(feed):
    eng = Engine(":memory:", feed, session_fn=lambda: SESSION_AFTER)
    feed.session = SESSION_AFTER
    feed.price_source = "extended"
    eng.create_user("alice", "h")
    with pytest.raises(TradingError, match="限價"):
        eng.place_order("alice", "AAPL", "BUY", "MARKET", 1)


def test_reject_market_when_closed_queue_limit(feed):
    eng = Engine(":memory:", feed, session_fn=lambda: SESSION_CLOSED)
    feed.session = SESSION_CLOSED
    eng.create_user("alice", "h")
    with pytest.raises(TradingError, match="CLOSED|收市"):
        eng.place_order("alice", "AAPL", "BUY", "MARKET", 1)
    # LIMIT queues, does not fill even if price would be marketable
    o = eng.place_order("alice", "AAPL", "BUY", "LIMIT", 10, 250)
    assert o["status"] == "PENDING"
    assert o["session"] == SESSION_CLOSED
    assert eng.process_pending() == []  # still closed


def test_extended_limit_can_fill_in_pre(feed):
    eng = Engine(":memory:", feed, session_fn=lambda: SESSION_PRE)
    feed.session = SESSION_PRE
    feed.price_source = "extended"
    feed.prices["AAPL"] = 200.0
    eng.create_user("alice", "h")
    o = eng.place_order("alice", "AAPL", "BUY", "LIMIT", 5, 210)
    assert o["status"] == "FILLED"
    assert o["session"] == SESSION_PRE
    trades = eng.trades("alice")
    assert trades[0]["session"] == SESSION_PRE


def test_force_extended_rejects_market_even_in_rth(feed):
    eng = Engine(":memory:", feed, session_fn=lambda: SESSION_RTH)
    eng.create_user("alice", "h")
    with pytest.raises(TradingError, match="限價"):
        eng.place_order("alice", "AAPL", "BUY", "MARKET", 1, session="extended")


def test_session_api(feed):
    from fastapi.testclient import TestClient
    from app.main import create_app

    app = create_app(db_path=":memory:", feed=feed, pending_interval=0)
    c = TestClient(app)
    assert c.get("/api/market/session").status_code == 401
    c.post("/api/auth/register", json={
        "password": "secret-pass-1", "password_confirm": "secret-pass-1",
        "email": "bob@example.com",
    })
    r = c.get("/api/market/session")
    assert r.status_code == 200
    body = r.json()
    assert body["session"] in (SESSION_PRE, SESSION_RTH, SESSION_AFTER, SESSION_CLOSED)
    assert body["overnight_supported"] is False
    assert body["extended_hours_supported"] is True
