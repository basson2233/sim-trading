import time

import pytest

from app.engine import Engine
from app.quotes import Quote, UnknownSymbol
from app.symbols import currency_of


class FakeFeed:
    """Deterministic feed for tests: prices are set explicitly."""

    def __init__(self, prices=None, fx=7.8):
        self.prices = dict(prices or {})
        self.fx = fx

    def quote(self, symbol):
        if symbol not in self.prices:
            raise UnknownSymbol(f"搵唔到股票代號 {symbol}")
        p = self.prices[symbol]
        return Quote(symbol, f"Name {symbol}", currency_of(symbol), p, p, "test", time.time())

    def history(self, symbol, range_key):
        return {"symbol": symbol, "range": range_key, "source": "test", "prev_close": None,
                "points": [[0, self.prices[symbol]]]}

    def fx_usd_hkd(self):
        return self.fx


@pytest.fixture
def feed():
    return FakeFeed({"0700.HK": 400.0, "0005.HK": 100.0, "9988.HK": 130.0,
                     "AAPL": 200.0, "TSLA": 300.0, "NVDA": 150.0})


@pytest.fixture
def eng(feed):
    e = Engine(":memory:", feed)
    e.create_user("alice", "test-hash")
    return e
