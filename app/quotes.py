"""Price feeds.

YahooFeed  - real (delayed) quotes from Yahoo Finance's public chart endpoint, cached.
SimFeed    - offline random-walk feed, clearly labelled source="simulated".
AutoFeed   - tries Yahoo first and falls back to SimFeed per request if Yahoo is unreachable.
"""
import hashlib
import math
import random
import threading
import time
from dataclasses import dataclass, asdict
from datetime import datetime, timezone

import requests

from .symbols import currency_of, market_of

HK_TZ_OFFSET = 8 * 3600


@dataclass
class Quote:
    symbol: str
    name: str
    currency: str
    price: float
    prev_close: float
    source: str  # "yahoo" | "simulated"
    as_of: float  # unix ts

    @property
    def change(self):
        return self.price - self.prev_close if self.prev_close else 0.0

    @property
    def change_pct(self):
        return (self.price / self.prev_close - 1) * 100 if self.prev_close else 0.0

    def to_dict(self):
        d = asdict(self)
        d["change"] = round(self.change, 4)
        d["change_pct"] = round(self.change_pct, 3)
        return d


class UnknownSymbol(ValueError):
    pass


class FeedUnavailable(RuntimeError):
    pass


# chart range key -> (yahoo range, yahoo interval)
RANGES = {
    "1D": ("1d", "5m"),
    "5D": ("5d", "30m"),
    "1M": ("1mo", "1d"),
    "6M": ("6mo", "1d"),
    "1Y": ("1y", "1d"),
    "5Y": ("5y", "1wk"),
}


class YahooFeed:
    URL = "https://query1.finance.yahoo.com/v8/finance/chart/{symbol}"
    HEADERS = {"User-Agent": "Mozilla/5.0 (X11; Linux x86_64) sim-trading/1.0"}

    def __init__(self, quote_ttl=15, history_ttl=300, timeout=6):
        self.quote_ttl = quote_ttl
        self.history_ttl = history_ttl
        self.timeout = timeout
        self._cache = {}
        self._lock = threading.Lock()
        self.session = requests.Session()

    def _fetch(self, symbol, rng, interval, ttl):
        key = (symbol, rng, interval)
        now = time.time()
        with self._lock:
            hit = self._cache.get(key)
            if hit and now - hit[0] < ttl:
                return hit[1]
        try:
            r = self.session.get(self.URL.format(symbol=symbol), headers=self.HEADERS,
                                 params={"range": rng, "interval": interval}, timeout=self.timeout)
        except requests.RequestException as e:
            raise FeedUnavailable(str(e))
        if r.status_code in (400, 404):
            raise UnknownSymbol(f"搵唔到股票代號 {symbol}")
        if r.status_code != 200:
            raise FeedUnavailable(f"Yahoo HTTP {r.status_code}")
        try:
            res = r.json()["chart"]["result"][0]
        except Exception:
            raise UnknownSymbol(f"搵唔到股票代號 {symbol}")
        with self._lock:
            self._cache[key] = (now, res)
        return res

    def quote(self, symbol):
        res = self._fetch(symbol, "1d", "5m", self.quote_ttl)
        m = res["meta"]
        price = m.get("regularMarketPrice")
        if price is None:
            raise UnknownSymbol(f"{symbol} 冇報價")
        return Quote(
            symbol=symbol,
            name=m.get("longName") or m.get("shortName") or symbol,
            currency=m.get("currency") or currency_of(symbol),
            price=float(price),
            prev_close=float(m.get("chartPreviousClose") or m.get("previousClose") or price),
            source="yahoo",
            as_of=float(m.get("regularMarketTime") or time.time()),
        )

    def history(self, symbol, range_key):
        rng, interval = RANGES[range_key]
        res = self._fetch(symbol, rng, interval, 60 if range_key in ("1D", "5D") else self.history_ttl)
        ts = res.get("timestamp") or []
        closes = ((res.get("indicators") or {}).get("quote") or [{}])[0].get("close") or []
        points = [[int(t), round(float(c), 4)] for t, c in zip(ts, closes) if c is not None]
        return {"symbol": symbol, "range": range_key, "source": "yahoo",
                "prev_close": res["meta"].get("chartPreviousClose"), "points": points}

    def fx_usd_hkd(self):
        return self.quote("HKD=X").price


# ---------------------------------------------------------------------------
SEED_PRICES = {
    "0700.HK": 420.0, "0005.HK": 100.0, "9988.HK": 130.0, "3690.HK": 130.0, "1810.HK": 50.0,
    "0941.HK": 85.0, "1299.HK": 70.0, "0388.HK": 400.0, "2800.HK": 25.0,
    "AAPL": 230.0, "TSLA": 300.0, "NVDA": 150.0, "MSFT": 450.0, "GOOGL": 180.0,
    "AMZN": 200.0, "META": 600.0,
}


def _seed(symbol):
    return int(hashlib.md5(symbol.encode()).hexdigest()[:8], 16)


class SimFeed:
    """Geometric random walk. Annualised vol ~35%, advances with wall-clock time."""
    VOL = 0.35

    def __init__(self, seed_prices=None):
        self.seed_prices = dict(SEED_PRICES)
        if seed_prices:
            self.seed_prices.update(seed_prices)
        self._state = {}
        self._lock = threading.Lock()

    def _base(self, symbol):
        if symbol in self.seed_prices:
            return self.seed_prices[symbol]
        return round(5 + (_seed(symbol) % 50000) / 100, 2)

    def set_anchor(self, symbol, price):
        """Continue the walk from a last-known real price."""
        with self._lock:
            st = self._state.get(symbol)
            if st is None:
                self._state[symbol] = {"price": price, "t": time.time(), "prev": price}

    def quote(self, symbol):
        now = time.time()
        with self._lock:
            st = self._state.get(symbol)
            if st is None:
                p = self._base(symbol)
                st = self._state[symbol] = {"price": p, "t": now, "prev": p}
            dt_years = max(now - st["t"], 0) / (252 * 6.5 * 3600)
            if dt_years > 0:
                z = random.gauss(0, 1)
                st["price"] *= math.exp(-0.5 * self.VOL ** 2 * dt_years + self.VOL * math.sqrt(dt_years) * z)
                st["t"] = now
            tick = 0.01 if market_of(symbol) == "US" else 0.001
            price = max(round(round(st["price"] / tick) * tick, 3), 0.01)
            return Quote(symbol, f"{symbol}（模擬）", currency_of(symbol), price, st["prev"], "simulated", now)

    def history(self, symbol, range_key):
        _, interval = RANGES[range_key]
        n, step = {"1D": (78, 300), "5D": (65, 1800), "1M": (22, 86400), "6M": (126, 86400),
                   "1Y": (252, 86400), "5Y": (260, 7 * 86400)}[range_key]
        end = self.quote(symbol).price
        rnd = random.Random(_seed(symbol + range_key))
        vol_step = self.VOL * math.sqrt(step / (252 * 6.5 * 3600 if step < 86400 else 252 * 86400))
        prices = [end]
        for _ in range(n - 1):
            prices.append(prices[-1] / math.exp(rnd.gauss(0, vol_step)))
        prices.reverse()
        now = int(time.time())
        pts = [[now - (n - 1 - i) * step, round(p, 3)] for i, p in enumerate(prices)]
        return {"symbol": symbol, "range": range_key, "source": "simulated",
                "prev_close": prices[0], "points": pts}

    def fx_usd_hkd(self):
        return 7.8  # HKD peg mid-point


class AutoFeed:
    """Yahoo first; fall back to the simulated feed if Yahoo is unreachable.
    After a failure Yahoo is skipped for `cooldown` seconds to keep the UI snappy."""

    def __init__(self, yahoo=None, sim=None, cooldown=60):
        self.yahoo = yahoo or YahooFeed()
        self.sim = sim or SimFeed()
        self.cooldown = cooldown
        self._down_until = 0.0

    def _try(self, fn_name, *args):
        if time.time() >= self._down_until:
            try:
                out = getattr(self.yahoo, fn_name)(*args)
                if fn_name == "quote":
                    self.sim.set_anchor(args[0], out.price)
                return out
            except FeedUnavailable:
                self._down_until = time.time() + self.cooldown
        return getattr(self.sim, fn_name)(*args)

    def quote(self, symbol):
        return self._try("quote", symbol)

    def history(self, symbol, range_key):
        return self._try("history", symbol, range_key)

    def fx_usd_hkd(self):
        return self._try("fx_usd_hkd")


def make_feed(mode: str):
    mode = (mode or "auto").lower()
    if mode == "yahoo":
        return YahooFeed()
    if mode in ("sim", "simulated"):
        return SimFeed()
    return AutoFeed()
