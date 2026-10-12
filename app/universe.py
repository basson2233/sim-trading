"""Built-in starter universe for stock-code autocomplete (港股藍籌 + 美股大型股)."""
from __future__ import annotations

from .symbols import market_of

# (symbol, English name, Chinese name). UI prefers Chinese name.
_UNIVERSE: list[tuple[str, str, str]] = [
    ("0001.HK", "CK Hutchison", "長和"),
    ("0002.HK", "CLP Holdings", "中電控股"),
    ("0003.HK", "HK & China Gas", "香港中華煤氣"),
    ("0005.HK", "HSBC Holdings", "匯豐控股"),
    ("0006.HK", "Power Assets", "電能實業"),
    ("0011.HK", "Hang Seng Bank", "恒生銀行"),
    ("0016.HK", "Sun Hung Kai Properties", "新鴻基地產"),
    ("0027.HK", "Galaxy Entertainment", "銀河娛樂"),
    ("0066.HK", "MTR Corporation", "港鐵公司"),
    ("0175.HK", "Geely Automobile", "吉利汽車"),
    ("0241.HK", "Alibaba Health", "阿里健康"),
    ("0267.HK", "CITIC", "中信股份"),
    ("0288.HK", "WH Group", "萬洲國際"),
    ("0386.HK", "Sinopec", "中國石油化工股份"),
    ("0388.HK", "Hong Kong Exchanges", "香港交易所"),
    ("0669.HK", "Techtronic Industries", "創科實業"),
    ("0688.HK", "China Overseas", "中國海外發展"),
    ("0700.HK", "Tencent Holdings", "騰訊控股"),
    ("0762.HK", "China Unicom", "中國聯通"),
    ("0823.HK", "Link REIT", "領展房產基金"),
    ("0857.HK", "PetroChina", "中國石油股份"),
    ("0868.HK", "Xinyi Glass", "信義玻璃"),
    ("0883.HK", "CNOOC", "中國海洋石油"),
    ("0939.HK", "China Construction Bank", "建設銀行"),
    ("0941.HK", "China Mobile", "中國移動"),
    ("0960.HK", "Longfor Group", "龍湖集團"),
    ("0968.HK", "Xinyi Solar", "信義光能"),
    ("0981.HK", "SMIC", "中芯國際"),
    ("0992.HK", "Lenovo Group", "聯想集團"),
    ("1024.HK", "Kuaishou Technology", "快手"),
    ("1044.HK", "Hengan International", "恒安國際"),
    ("1088.HK", "China Shenhua", "中國神華"),
    ("1093.HK", "CSPC Pharmaceutical", "石藥集團"),
    ("1109.HK", "China Resources Land", "華潤置地"),
    ("1177.HK", "Sino Biopharmaceutical", "中國生物製藥"),
    ("1211.HK", "BYD Company", "比亞迪股份"),
    ("1299.HK", "AIA Group", "友邦保險"),
    ("1378.HK", "China Hongqiao", "中國宏橋"),
    ("1398.HK", "ICBC", "工商銀行"),
    ("1810.HK", "Xiaomi Corporation", "小米集團"),
    ("1876.HK", "Budweiser APAC", "百威亞太"),
    ("1928.HK", "Sands China", "金沙中國"),
    ("1929.HK", "Chow Tai Fook", "周大福"),
    ("2015.HK", "Li Auto", "理想汽車"),
    ("2020.HK", "ANTA Sports", "安踏體育"),
    ("2269.HK", "Wuxi Biologics", "藥明生物"),
    ("2313.HK", "Shenzhou International", "申洲國際"),
    ("2318.HK", "Ping An Insurance", "中國平安"),
    ("2319.HK", "Mengniu Dairy", "蒙牛乳業"),
    ("2331.HK", "Li Ning", "李寧"),
    ("2382.HK", "Sunny Optical", "舜宇光學"),
    ("2388.HK", "BOC Hong Kong", "中銀香港"),
    ("2628.HK", "China Life", "中國人壽"),
    ("2688.HK", "ENN Energy", "新奧能源"),
    ("2800.HK", "Tracker Fund of Hong Kong", "盈富基金"),
    ("2823.HK", "iShares A50", "安碩A50"),
    ("2828.HK", "Hang Seng China Enterprises", "恒生中國企業"),
    ("2899.HK", "Zijin Mining", "紫金礦業"),
    ("3690.HK", "Meituan", "美團"),
    ("3968.HK", "China Merchants Bank", "招商銀行"),
    ("3988.HK", "Bank of China", "中國銀行"),
    ("6618.HK", "JD Health", "京東健康"),
    ("6862.HK", "Haidilao", "海底撈"),
    ("9618.HK", "JD.com", "京東集團"),
    ("9626.HK", "Bilibili", "嗶哩嗶哩"),
    ("9888.HK", "Baidu", "百度集團"),
    ("9901.HK", "New Oriental", "新東方"),
    ("9961.HK", "Trip.com", "攜程集團"),
    ("9988.HK", "Alibaba Group", "阿里巴巴"),
    ("9999.HK", "NetEase", "網易"),
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
    """Match built-in symbols for autocomplete.

    Matches code prefix (07→0700.HK, AAP→AAPL) and English/Chinese name substring.
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
    if sym.endswith(".HK"):
        code = sym[:-3]
        digits = q_up[:-3] if q_up.endswith(".HK") else q_up
        digits = digits.replace(".", "")
        if digits.isdigit():
            if code.startswith(digits):
                return 1
            if len(digits) <= 4 and code == digits.zfill(4):
                return 1
            stripped_q = digits.lstrip("0")
            stripped_c = code.lstrip("0")
            if stripped_q and len(digits) >= 2 and stripped_c.startswith(stripped_q):
                return 2
    if q in zh or q_up in en.upper() or q.lower() in en.lower():
        return 3
    return None
