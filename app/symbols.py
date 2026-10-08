"""Symbol normalisation, market detection and HK board-lot sizes."""
import re

# Known HK board-lot sizes (每手股數). Lot sizes can change (splits, bonus issues);
# anything not listed here falls back to DEFAULT_HK_LOT and is flagged as "assumed".
HK_LOT_SIZES = {
    "0001.HK": 500, "0002.HK": 500, "0003.HK": 1000, "0005.HK": 400, "0006.HK": 500,
    "0011.HK": 100, "0016.HK": 500, "0027.HK": 1000, "0066.HK": 500, "0175.HK": 1000,
    "0388.HK": 100, "0700.HK": 100, "0823.HK": 100, "0857.HK": 2000, "0883.HK": 1000,
    "0939.HK": 1000, "0941.HK": 500, "0981.HK": 500, "1024.HK": 100, "1211.HK": 500,
    "1299.HK": 200, "1398.HK": 1000, "1810.HK": 200, "2020.HK": 200, "2318.HK": 500,
    "2800.HK": 500, "3690.HK": 100, "3988.HK": 1000, "9618.HK": 50, "9888.HK": 50,
    "9988.HK": 100, "9999.HK": 100,
}
DEFAULT_HK_LOT = 100

MARKET_CURRENCY = {"HK": "HKD", "US": "USD"}


class SymbolError(ValueError):
    pass


def normalize(raw: str) -> str:
    """'700' / '0700' / '00700.hk' -> '0700.HK'; 'aapl' -> 'AAPL'; 'brk.b' -> 'BRK-B'."""
    s = (raw or "").strip().upper()
    if not s:
        raise SymbolError("請輸入股票代號")
    m = re.fullmatch(r"(\d{1,5})(\.HK)?", s)
    if m:
        code = int(m.group(1))
        if code <= 0:
            raise SymbolError(f"無效嘅港股代號：{raw}")
        return f"{code:04d}.HK"
    if re.fullmatch(r"[A-Z][A-Z0-9]{0,5}([.\-][A-Z])?", s):
        return s.replace(".", "-")
    raise SymbolError(f"唔支援嘅股票代號：{raw}（支援港股如 0700.HK / 700，美股如 AAPL）")


def market_of(symbol: str) -> str:
    return "HK" if symbol.endswith(".HK") else "US"


def currency_of(symbol: str) -> str:
    return MARKET_CURRENCY[market_of(symbol)]


def lot_size(symbol: str):
    """Return (lot_size, is_known)."""
    if market_of(symbol) == "US":
        return 1, True
    if symbol in HK_LOT_SIZES:
        return HK_LOT_SIZES[symbol], True
    return DEFAULT_HK_LOT, False
