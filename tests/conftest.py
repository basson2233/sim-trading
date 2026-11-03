import time

import pytest

from app.engine import Engine
from app.market_session import SESSION_RTH
from app.quotes import Quote, UnknownSymbol
from app.symbols import currency_of


class FakeFeed:
    """Deterministic feed for tests: prices are set explicitly."""

    def __init__(self, prices=None, volumes=None, fx=7.8, session=SESSION_RTH, price_source="regular"):
        self.prices = dict(prices or {})
        self.volumes = dict(volumes or {})
        self.fx = fx
        self.session = session
        self.price_source = price_source

    def quote(self, symbol):
        if symbol not in self.prices:
            raise UnknownSymbol(f"搵唔到股票代號 {symbol}")
        p = self.prices[symbol]
        vol = self.volumes.get(symbol)  # may be intentionally absent → None
        return Quote(symbol, f"Name {symbol}", currency_of(symbol), p, p, "test", time.time(),
                     session=self.session, price_source=self.price_source, volume=vol)

    def history(self, symbol, range_key):
        return {"symbol": symbol, "range": range_key, "source": "test", "prev_close": None,
                "points": [[0, self.prices[symbol]]]}

    def fx_usd_hkd(self):
        return self.fx


@pytest.fixture
def feed():
    return FakeFeed({"AAPL": 200.0, "TSLA": 300.0, "NVDA": 150.0, "JPM": 100.0,
                     "JNJ": 160.0, "SPY": 500.0, "MSFT": 400.0, "PG": 150.0, "XOM": 110.0})


@pytest.fixture
def eng(feed):
    # Pin RTH so MARKET order tests do not depend on wall-clock ET session.
    e = Engine(":memory:", feed, session_fn=lambda: SESSION_RTH)
    e.create_user("alice", "test-hash")
    return e


@pytest.fixture(autouse=True)
def _force_rth_session(monkeypatch):
    """Keep API/engine tests independent of wall-clock ET (PRE/AFTER/CLOSED)."""
    monkeypatch.setenv("SIM_FORCE_SESSION", SESSION_RTH)
