"""理財戰士 (Finance Fighter): stock holdings → ATK / DEF / SPD.

Primary rule (locked with user):
  Base ATK / DEF / SPD each start at **100**.
  For each affinity bucket, add **+1 point per USD 10,000** market value
  held in stocks of that affinity. Example: $30,000 NVDA (ATK) → ATK = 103.

Affinity themes:
  ATK 攻擊 — growth / tech / volatile / high-beta
  DEF 防禦 — banks / utilities / telecom / staples / REITs / defensives
  SPD 速度 — liquid mega-caps / broad ETFs / high-turnover names

Unknown symbols default to a mild ATK bias. Soft cap 999.
"""
from __future__ import annotations

from typing import Any

BASE_STAT = 100.0
MIN_STAT = 1.0
MAX_STAT = 999.0
# USD market value that yields +1 point on the matching affinity.
MV_PER_POINT = 10_000.0

# Primary affinity per symbol. Optional secondary as (affinity, weight 0–1).
# Format: symbol -> (primary, secondary_or_None, secondary_weight)
# Secondary splits MV: primary gets (1 - w), secondary gets w.
_AFFINITY: dict[str, tuple[str, str | None, float]] = {
    # --- ATK: growth / tech / volatile ---
    "AAPL": ("atk", "spd", 0.3),
    "NVDA": ("atk", None, 0.0),
    "TSLA": ("atk", None, 0.0),
    "AMD": ("atk", None, 0.0),
    "META": ("atk", "spd", 0.2),
    "GOOGL": ("atk", "spd", 0.25),
    "AMZN": ("atk", "spd", 0.25),
    "NFLX": ("atk", None, 0.0),
    "AVGO": ("atk", None, 0.0),
    "ADBE": ("atk", None, 0.0),
    "CRM": ("atk", None, 0.0),
    "ORCL": ("atk", "def", 0.15),
    "INTC": ("atk", None, 0.0),
    "QCOM": ("atk", None, 0.0),
    "PLTR": ("atk", None, 0.0),
    "COIN": ("atk", None, 0.0),
    "SHOP": ("atk", None, 0.0),
    "SPOT": ("atk", None, 0.0),
    "ZM": ("atk", None, 0.0),
    "PYPL": ("atk", None, 0.0),
    "SQ": ("atk", None, 0.0),
    "UBER": ("atk", None, 0.0),
    "ABNB": ("atk", None, 0.0),
    "NIO": ("atk", None, 0.0),
    "LI": ("atk", None, 0.0),
    "XPEV": ("atk", None, 0.0),
    "PDD": ("atk", None, 0.0),
    "BABA": ("atk", "spd", 0.2),
    "JD": ("atk", "spd", 0.15),
    "DIS": ("atk", "spd", 0.15),
    "NKE": ("atk", None, 0.0),
    "BA": ("atk", None, 0.0),
    "CAT": ("atk", "def", 0.2),
    "GE": ("atk", "def", 0.2),
    # --- DEF: banks / staples / defensives ---
    "JPM": ("def", None, 0.0),
    "V": ("def", "spd", 0.15),
    "MA": ("def", "spd", 0.15),
    "BRK-B": ("def", None, 0.0),
    "JNJ": ("def", None, 0.0),
    "PG": ("def", None, 0.0),
    "KO": ("def", None, 0.0),
    "PEP": ("def", None, 0.0),
    "WMT": ("def", None, 0.0),
    "COST": ("def", None, 0.0),
    "MCD": ("def", None, 0.0),
    "SBUX": ("def", "atk", 0.15),
    "UNH": ("def", None, 0.0),
    "MRK": ("def", None, 0.0),
    "ABBV": ("def", None, 0.0),
    "HD": ("def", "atk", 0.15),
    "XOM": ("def", "atk", 0.2),
    "CVX": ("def", "atk", 0.2),
    "CSCO": ("def", "atk", 0.2),
    "IBM": ("def", "atk", 0.2),
    "TXN": ("def", "atk", 0.25),
    # --- SPD: mega-caps / ETFs ---
    "MSFT": ("spd", "atk", 0.3),
    "SPY": ("spd", None, 0.0),
    "QQQ": ("spd", "atk", 0.25),
    "IWM": ("spd", "atk", 0.2),
    "DIA": ("spd", "def", 0.2),
}


def affinity_of(symbol: str) -> tuple[str, str | None, float]:
    """Return (primary, secondary|None, secondary_weight). Unknown → mild ATK."""
    row = _AFFINITY.get(symbol)
    if row:
        return row
    return ("atk", "def", 0.2)


def _clamp(x: float, lo: float = MIN_STAT, hi: float = MAX_STAT) -> float:
    return max(lo, min(hi, x))


def _mv_usd(pos: dict) -> float:
    """Position market value in USD. Non-USD (legacy HK) positions contribute 0."""
    if (pos.get("currency") or "USD") != "USD":
        return 0.0
    return float(pos.get("market_value") or 0.0)


def compute_fighter_stats(portfolio: dict) -> dict[str, Any]:
    """Derive ATK/DEF/SPD: base 100 + 1 per USD 10,000 MV in each affinity."""
    username = portfolio.get("username") or "?"
    total = portfolio.get("total") or {}
    equity = float(total.get("equity") or 0.0) or 1.0
    return_pct = float(total.get("return_pct") or 0.0)
    positions = portfolio.get("positions") or []

    bucket = {"atk": 0.0, "def": 0.0, "spd": 0.0}
    breakdown: list[dict] = []
    invested_mv = 0.0

    for p in positions:
        mv = _mv_usd(p)
        if mv <= 0:
            continue
        invested_mv += mv
        primary, secondary, sec_w = affinity_of(p["symbol"])
        primary_share = 1.0 - (sec_w if secondary else 0.0)
        contrib_mv = {"atk": 0.0, "def": 0.0, "spd": 0.0}
        contrib_mv[primary] += mv * primary_share
        if secondary and sec_w > 0:
            contrib_mv[secondary] += mv * sec_w
        for k in bucket:
            bucket[k] += contrib_mv[k]
        points = {k: round(v / MV_PER_POINT, 4) for k, v in contrib_mv.items() if v > 0}
        breakdown.append({
            "symbol": p["symbol"],
            "name": p.get("name") or p["symbol"],
            "affinity": primary,
            "secondary": secondary,
            "market_value_base": round(mv, 2),
            "market_value_usd": round(mv, 2),
            "weight": round(mv / (invested_mv or 1.0), 4),  # refreshed below
            "points": points,
            "contrib": points,
        })

    # Fix weights now that invested_mv is known
    denom = invested_mv if invested_mv > 0 else 1.0
    for b in breakdown:
        b["weight"] = round(b["market_value_usd"] / denom, 4)

    stats = {}
    for key in ("atk", "def", "spd"):
        bonus = bucket[key] / MV_PER_POINT
        stats[key] = round(_clamp(BASE_STAT + bonus), 1)

    dominant = max(bucket, key=bucket.get) if invested_mv > 0 else "cash"
    cash_frac = max(0.0, 1.0 - invested_mv / equity) if equity else 1.0

    return {
        "username": username,
        "display_name": username,
        "atk": stats["atk"],
        "def": stats["def"],
        "spd": stats["spd"],
        "dominant": dominant,
        "cash_fraction": round(cash_frac, 4),
        "commitment": 1.0 if invested_mv > 0 else 0.0,
        "invested_mv_base": round(invested_mv, 2),
        "invested_mv_usd": round(invested_mv, 2),
        "equity_base": round(equity, 2),
        "return_pct": return_pct,
        "breakdown": sorted(breakdown, key=lambda r: -r["market_value_usd"]),
        "tip": "基礎每項 100，相關股票每持有市值 1 萬加 1 點",
        "formula": {"base": BASE_STAT, "mv_per_point_usd": MV_PER_POINT, "max": MAX_STAT},
    }


def ai_stats(difficulty: str = "normal", mirror: dict | None = None) -> dict[str, Any]:
    """Fixed or mirrored AI fighter stats for practice mode."""
    d = (difficulty or "normal").lower()
    if mirror:
        scale = {"easy": 0.85, "normal": 0.95, "hard": 1.05}.get(d, 0.95)
        out = {
            "username": "AI",
            "display_name": f"AI（{'簡單' if d == 'easy' else '普通' if d == 'normal' else '困難'}）",
            "atk": round(_clamp(mirror["atk"] * scale), 1),
            "def": round(_clamp(mirror["def"] * scale), 1),
            "spd": round(_clamp(mirror["spd"] * scale), 1),
            "dominant": mirror.get("dominant", "balanced"),
            "breakdown": [],
            "tip": "練習對手會跟你嘅屬性微調",
            "difficulty": d,
            "is_ai": True,
        }
        return out
    presets = {
        "easy": {"atk": 95.0, "def": 98.0, "spd": 92.0},
        "normal": {"atk": 105.0, "def": 102.0, "spd": 100.0},
        "hard": {"atk": 120.0, "def": 115.0, "spd": 118.0},
    }
    base = presets.get(d, presets["normal"])
    label = {"easy": "簡單", "normal": "普通", "hard": "困難"}.get(d, "普通")
    return {
        "username": "AI",
        "display_name": f"AI（{label}）",
        "atk": base["atk"],
        "def": base["def"],
        "spd": base["spd"],
        "dominant": "balanced",
        "breakdown": [],
        "tip": "練習對手",
        "difficulty": d,
        "is_ai": True,
    }
