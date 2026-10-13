"""Built-in starter universe for stock-code autocomplete (美股大型股)."""
from __future__ import annotations

from .symbols import market_of

# (symbol, English name, Chinese name). UI prefers Chinese name.
_UNIVERSE: list[tuple[str, str, str]] = [
    ("AAPL", "Apple", "蘋果"),
    ("MSFT", "Microsoft", "微軟"),
    ("NVDA", "NVIDIA", "英偉達"),
    ("GOOGL", "Alphabet", "谷歌"),
    ("AMZN", "Amazon", "亞馬遜"),
    ("META", "Meta Platforms", "Meta"),
    ("TSLA", "Tesla", "特斯拉"),
    ("BRK-B", "Berkshire Hathaway B", "伯克希爾B"),
    ("JPM", "JPMorgan Chase", "摩根大通"),
    ("V", "Visa", "Visa"),
    ("MA", "Mastercard", "萬事達"),
    ("UNH", "UnitedHealth", "聯合健康"),
    ("XOM", "Exxon Mobil", "埃克森美孚"),
    ("JNJ", "Johnson & Johnson", "強生"),
    ("WMT", "Walmart", "沃爾瑪"),
    ("PG", "Procter & Gamble", "寶潔"),
    ("HD", "Home Depot", "家得寶"),
    ("CVX", "Chevron", "雪佛龍"),
    ("MRK", "Merck", "默沙東"),
    ("ABBV", "AbbVie", "艾伯維"),
    ("KO", "Coca-Cola", "可口可樂"),
    ("PEP", "PepsiCo", "百事"),
    ("COST", "Costco", "好市多"),
    ("AVGO", "Broadcom", "博通"),
    ("AMD", "AMD", "超微半導體"),
    ("NFLX", "Netflix", "奈飛"),
    ("ADBE", "Adobe", "Adobe"),
    ("CRM", "Salesforce", "Salesforce"),
    ("ORCL", "Oracle", "甲骨文"),
    ("INTC", "Intel", "英特爾"),
    ("CSCO", "Cisco", "思科"),
    ("QCOM", "Qualcomm", "高通"),
    ("TXN", "Texas Instruments", "德州儀器"),
    ("IBM", "IBM", "IBM"),
    ("BA", "Boeing", "波音"),
    ("CAT", "Caterpillar", "卡特彼勒"),
    ("GE", "GE Aerospace", "通用電氣"),
    ("DIS", "Walt Disney", "迪士尼"),
    ("NKE", "Nike", "耐克"),
    ("SBUX", "Starbucks", "星巴克"),
    ("MCD", "McDonald's", "麥當勞"),
    ("PYPL", "PayPal", "PayPal"),
    ("SQ", "Block", "Block"),
    ("UBER", "Uber", "Uber"),
    ("ABNB", "Airbnb", "Airbnb"),
    ("COIN", "Coinbase", "Coinbase"),
    ("PLTR", "Palantir", "Palantir"),
    ("SHOP", "Shopify", "Shopify"),
    ("SPOT", "Spotify", "Spotify"),
    ("ZM", "Zoom", "Zoom"),
    ("BABA", "Alibaba ADR", "阿里巴巴ADR"),
    ("JD", "JD.com ADR", "京東ADR"),
    ("PDD", "PDD Holdings", "拼多多"),
    ("NIO", "NIO", "蔚來"),
    ("LI", "Li Auto ADR", "理想汽車ADR"),
    ("XPEV", "XPeng ADR", "小鵬汽車ADR"),
    ("SPY", "SPDR S&P 500 ETF", "標普500 ETF"),
    ("QQQ", "Invesco QQQ", "納指100 ETF"),
    ("IWM", "iShares Russell 2000", "羅素2000 ETF"),
    ("DIA", "SPDR Dow Jones", "道瓊斯 ETF"),
]

UNIVERSE: list[dict] = [
    {"symbol": s, "name_en": en, "name_zh": zh, "market": market_of(s)}
    for s, en, zh in _UNIVERSE
]


def suggest_symbols(query: str, limit: int = 10) -> list[dict]:
    """Match built-in US symbols for autocomplete.

    Matches code prefix (AAP→AAPL) and English/Chinese name substring.
    Ranking: exact symbol, then code/symbol prefix, then name. Empty query → [].
    """
    q = (query or "").strip()
    if not q:
        return []
    try:
        limit = max(1, min(int(limit), 25))
    except (TypeError, ValueError):
        limit = 10
    q_up = q.upper()
    scored: list[tuple[int, str, dict]] = []
    for row in UNIVERSE:
        score = _match_score(row["symbol"], row["name_en"], row["name_zh"], q, q_up)
        if score is not None:
            scored.append((score, row["symbol"], row))
    scored.sort(key=lambda t: (t[0], t[1]))
    return [
        {
            "symbol": row["symbol"],
            "name": row["name_zh"] or row["name_en"],
            "name_en": row["name_en"],
            "name_zh": row["name_zh"],
            "market": row["market"],
        }
        for _, _, row in scored[:limit]
    ]


def _match_score(sym: str, en: str, zh: str, q: str, q_up: str):
    """Lower score is better; None means no match."""
    sym_alt = sym.replace("-", ".")
    q_alt = q_up.replace(".", "-")
    if sym == q_up or sym == q_alt or sym_alt == q_up:
        return 0
    if sym.startswith(q_up) or sym.startswith(q_alt):
        return 1
    if q in zh or q_up in en.upper() or q.lower() in en.lower():
        return 3
    return None
