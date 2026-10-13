"""Symbol normalisation and market detection (US stocks only)."""
import re

MARKET_CURRENCY = {"US": "USD"}


class SymbolError(ValueError):
    pass


def normalize(raw: str) -> str:
    """'aapl' -> 'AAPL'; 'brk.b' -> 'BRK-B'. Rejects HK / numeric codes."""
    s = (raw or "").strip().upper()
    if not s:
        raise SymbolError("請輸入股票代號")
    if s.endswith(".HK") or re.fullmatch(r"\d{1,5}(\.HK)?", s):
        raise SymbolError(f"已唔再支援港股：{raw}（請用美股代號，例如 AAPL、NVDA）")
    if re.fullmatch(r"[A-Z][A-Z0-9]{0,5}([.\-][A-Z])?", s):
        return s.replace(".", "-")
    raise SymbolError(f"唔支援嘅股票代號：{raw}（只支援美股，例如 AAPL、NVDA、SPY）")


def market_of(symbol: str) -> str:
    return "HK" if symbol.endswith(".HK") else "US"


def currency_of(symbol: str) -> str:
    if market_of(symbol) == "HK":
        return "HKD"
    return "USD"


def lot_size(symbol: str):
    """Return (lot_size, is_known). US stocks trade in 1-share lots."""
    if market_of(symbol) == "US":
        return 1, True
    # Legacy HK symbols (should be rejected at normalize / place_order)
    return 100, False
