"""理財戰士 (Finance Fighter): stock holdings → ATK / DEF / SPD.

Primary rule (locked with user):
  Stats are driven by **position market value** (持倉市值), not share count.
  Weight each holding by its market value relative to total invested equity
  (positions MV in base currency HKD). Whichever affinity bucket (atk/def/spd)
  has more HK$/USD market value invested → that fighter stat goes higher.

Affinity themes (documented for mapping):
  ATK 攻擊 — growth / tech / volatile / high-beta
  DEF 防禦 — banks / utilities / telecom / staples / REITs / defensives
  SPD 速度 — liquid mega-caps / broad ETFs / high-turnover names

Unknown symbols default to a mild balanced affinity (slight ATK bias).
"""
from __future__ import annotations

from typing import Any

BASE_STAT = 50.0
MIN_STAT = 30.0
MAX_STAT = 99.0
# How many points full equity allocation into one affinity can add above base.
MAX_BOOST = 42.0
# Cash (uninvested) fraction pulls all stats slightly toward / below base.
CASH_PENALTY = 8.0

# Primary affinity per symbol. Optional secondary as (affinity, weight 0–1).
# Format: symbol -> (primary, secondary_or_None, secondary_weight)
_AFFINITY: dict[str, tuple[str, str | None, float]] = {
    # --- ATK: growth / tech / volatile ---
    "0700.HK": ("atk", "spd", 0.25),   # 騰訊
    "9988.HK": ("atk", "spd", 0.2),    # 阿里巴巴
    "1810.HK": ("atk", None, 0.0),     # 小米
    "3690.HK": ("atk", "spd", 0.15),   # 美團
    "1024.HK": ("atk", None, 0.0),     # 快手
    "0981.HK": ("atk", None, 0.0),     # 中芯
    "1211.HK": ("atk", None, 0.0),     # 比亞迪
    "2015.HK": ("atk", None, 0.0),     # 理想汽車
    "9626.HK": ("atk", None, 0.0),     # 嗶哩嗶哩
    "9888.HK": ("atk", None, 0.0),     # 百度
    "9999.HK": ("atk", "spd", 0.15),   # 網易
    "9618.HK": ("atk", "spd", 0.15),   # 京東
    "9961.HK": ("atk", None, 0.0),     # 攜程
    "0175.HK": ("atk", None, 0.0),     # 吉利
    "2382.HK": ("atk", None, 0.0),     # 舜宇光學
    "0992.HK": ("atk", None, 0.0),     # 聯想
    "0241.HK": ("atk", None, 0.0),     # 阿里健康
    "6618.HK": ("atk", None, 0.0),     # 京東健康
    "9901.HK": ("atk", None, 0.0),     # 新東方
    "2269.HK": ("atk", None, 0.0),     # 藥明生物
    "1177.HK": ("atk", None, 0.0),     # 中國生物製藥
    "1093.HK": ("atk", "def", 0.2),    # 石藥
    "6862.HK": ("atk", None, 0.0),     # 海底撈
    "0027.HK": ("atk", None, 0.0),     # 銀河娛樂
    "1928.HK": ("atk", None, 0.0),     # 金沙中國
    "2020.HK": ("atk", None, 0.0),     # 安踏
    "2331.HK": ("atk", None, 0.0),     # 李寧
    "0669.HK": ("atk", None, 0.0),     # 創科
    "0868.HK": ("atk", None, 0.0),     # 信義玻璃
    "0968.HK": ("atk", None, 0.0),     # 信義光能
    "1378.HK": ("atk", None, 0.0),     # 中國宏橋
    "2899.HK": ("atk", None, 0.0),     # 紫金礦業
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
    # --- DEF: banks / utilities / telecom / staples / REITs ---
    "0005.HK": ("def", None, 0.0),     # 匯豐
    "0939.HK": ("def", None, 0.0),     # 建行
    "0002.HK": ("def", None, 0.0),     # 中電
    "0941.HK": ("def", "spd", 0.15),   # 移動
    "0823.HK": ("def", None, 0.0),     # 領展
    "0003.HK": ("def", None, 0.0),     # 中華煤氣
    "0006.HK": ("def", None, 0.0),     # 電能
    "0011.HK": ("def", None, 0.0),     # 恒生銀行
    "1398.HK": ("def", None, 0.0),     # 工商銀行
    "3988.HK": ("def", None, 0.0),     # 中國銀行
    "3968.HK": ("def", None, 0.0),     # 招商銀行
    "2388.HK": ("def", None, 0.0),     # 中銀香港
    "1299.HK": ("def", "spd", 0.15),   # 友邦
    "2318.HK": ("def", None, 0.0),     # 平安
    "2628.HK": ("def", None, 0.0),     # 中國人壽
    "0066.HK": ("def", None, 0.0),     # 港鐵
    "0762.HK": ("def", None, 0.0),     # 聯通
    "2688.HK": ("def", None, 0.0),     # 新奧能源
    "0016.HK": ("def", None, 0.0),     # 新鴻基
    "1109.HK": ("def", None, 0.0),     # 華潤置地
    "0688.HK": ("def", None, 0.0),     # 中海外
    "0960.HK": ("def", None, 0.0),     # 龍湖
    "0288.HK": ("def", None, 0.0),     # 萬洲
    "1044.HK": ("def", None, 0.0),     # 恒安
    "2319.HK": ("def", None, 0.0),     # 蒙牛
    "1876.HK": ("def", None, 0.0),     # 百威亞太
    "0386.HK": ("def", "atk", 0.15),   # 中石化
    "0857.HK": ("def", "atk", 0.15),   # 中石油
    "0883.HK": ("def", "atk", 0.2),    # 中海油
    "1088.HK": ("def", "atk", 0.15),   # 神華
    "0001.HK": ("def", "spd", 0.15),   # 長和
    "0267.HK": ("def", None, 0.0),     # 中信
    "1929.HK": ("def", None, 0.0),     # 周大福
    "2313.HK": ("def", None, 0.0),     # 申洲
    "JNJ": ("def", None, 0.0),
    "PG": ("def", None, 0.0),
    "KO": ("def", None, 0.0),
    "PEP": ("def", None, 0.0),
    "WMT": ("def", "spd", 0.15),
    "COST": ("def", "spd", 0.15),
    "JPM": ("def", "spd", 0.2),
    "BRK-B": ("def", None, 0.0),
    "UNH": ("def", None, 0.0),
    "XOM": ("def", "atk", 0.2),
    "CVX": ("def", "atk", 0.2),
    "MRK": ("def", None, 0.0),
    "ABBV": ("def", None, 0.0),
    "V": ("def", "spd", 0.25),
    "MA": ("def", "spd", 0.25),
    "HD": ("def", None, 0.0),
    "MCD": ("def", None, 0.0),
    "SBUX": ("def", None, 0.0),
    "CSCO": ("def", "atk", 0.2),
    "IBM": ("def", "atk", 0.2),
    "TXN": ("def", "atk", 0.25),
    # --- SPD: liquid mega-caps / ETFs / high turnover ---
    "0388.HK": ("spd", "atk", 0.2),    # 港交所
    "2800.HK": ("spd", None, 0.0),     # 盈富
    "2823.HK": ("spd", None, 0.0),     # 安碩A50
    "2828.HK": ("spd", None, 0.0),     # 恒生中國企業
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
    # Unknown / not in map: slight ATK bias so holdings still matter
    return ("atk", "def", 0.2)


def _clamp(x: float, lo: float = MIN_STAT, hi: float = MAX_STAT) -> float:
    return max(lo, min(hi, x))


def _mv_base(pos: dict, fx: float) -> float:
    """Position market value in HKD (base currency)."""
    mv = float(pos.get("market_value") or 0.0)
    if (pos.get("currency") or "HKD") == "USD":
        return mv * fx
    return mv


def compute_fighter_stats(portfolio: dict) -> dict[str, Any]:
    """Derive ATK/DEF/SPD from portfolio using **market-value weights**.

    Primary rule: weight each holding by its market value relative to
    **total invested equity** (sum of position MVs in HKD). Affinity buckets
    accumulate those composition weights — whichever category has more
    market value invested gets the higher stat.

    Commitment: scale boosts by how much of total account equity is invested
    (full scale once ~20% of equity is in stocks) so typical paper portfolios
    feel distinct; cash-heavy accounts stay near base with a small penalty.

    Optional light nudge from total return_pct (± few points).
    """
    username = portfolio.get("username") or "?"
    fx = float((portfolio.get("fx") or {}).get("USDHKD") or 7.8)
    total = portfolio.get("total") or {}
    equity = float(total.get("equity") or 0.0) or 1.0
    return_pct = float(total.get("return_pct") or 0.0)
    positions = portfolio.get("positions") or []

    # First pass: invested market value (base currency)
    rows: list[tuple[dict, float]] = []
    invested_mv = 0.0
    for p in positions:
        mv_b = _mv_base(p, fx)
        if mv_b <= 0:
            continue
        invested_mv += mv_b
        rows.append((p, mv_b))

    bucket = {"atk": 0.0, "def": 0.0, "spd": 0.0}
    breakdown: list[dict] = []
    denom = invested_mv if invested_mv > 0 else 1.0

    for p, mv_b in rows:
        # Composition weight among holdings (持倉市值 / 總投入市值)
        weight = mv_b / denom
        primary, secondary, sec_w = affinity_of(p["symbol"])
        primary_share = 1.0 - (sec_w if secondary else 0.0)
        contrib = {"atk": 0.0, "def": 0.0, "spd": 0.0}
        contrib[primary] += weight * primary_share
        if secondary and sec_w > 0:
            contrib[secondary] += weight * sec_w
        for k in bucket:
            bucket[k] += contrib[k]
        breakdown.append({
            "symbol": p["symbol"],
            "name": p.get("name") or p["symbol"],
            "affinity": primary,
            "secondary": secondary,
            "market_value_base": round(mv_b, 2),
            "weight": round(weight, 4),
            "contrib": {k: round(v, 4) for k, v in contrib.items() if v > 0},
        })

    cash_frac = max(0.0, 1.0 - invested_mv / equity)
    # Full boost scale once ~20% of equity is invested (game feel)
    commitment = 0.0 if invested_mv <= 0 else min(1.0, invested_mv / (equity * 0.20))
    pnl_nudge = max(-5.0, min(5.0, return_pct / 10.0))

    stats = {}
    for key in ("atk", "def", "spd"):
        boost = bucket[key] * MAX_BOOST * commitment
        penalty = CASH_PENALTY if invested_mv <= 0 else cash_frac * (CASH_PENALTY * 0.35)
        val = BASE_STAT + boost - penalty + pnl_nudge
        stats[key] = round(_clamp(val), 1)

    dominant = max(bucket, key=bucket.get) if invested_mv > 0 else "cash"

    return {
        "username": username,
        "display_name": username,
        "atk": stats["atk"],
        "def": stats["def"],
        "spd": stats["spd"],
        "dominant": dominant,
        "cash_fraction": round(cash_frac, 4),
        "commitment": round(commitment, 4),
        "invested_mv_base": round(invested_mv, 2),
        "equity_base": round(equity, 2),
        "return_pct": return_pct,
        "breakdown": sorted(breakdown, key=lambda r: -r["market_value_base"]),
        "tip": "你嘅持倉市值決定戰士屬性——邊類股票投得多，對應屬性就愈高",
    }


def ai_stats(difficulty: str = "normal", mirror: dict | None = None) -> dict[str, Any]:
    """Fixed or mirrored AI fighter stats for practice mode."""
    d = (difficulty or "normal").lower()
    if mirror:
        # Slightly weaker / stronger copy of player's live stats
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
        "easy": {"atk": 42.0, "def": 45.0, "spd": 40.0},
        "normal": {"atk": 55.0, "def": 52.0, "spd": 50.0},
        "hard": {"atk": 72.0, "def": 68.0, "spd": 70.0},
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
