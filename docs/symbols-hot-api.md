# Hot symbols API（快捷代號按成交額排序）

給 **软件工程师**：下方 quick-pick chips 可改跟 **當日成交額**（`price × regularMarketVolume`）由高到低排。

教學提示（UI 小字）：**「活躍≠推薦」**。

---

## `GET /api/symbols/hot`

需登入（同 `/api/quote`）。

| Query | 必填 | 說明 |
|-------|------|------|
| `symbols` | 否 | 逗號分隔代號；省略則用預設 QUICK：`AAPL,TSLA,NVDA,MSFT,GOOGL,AMZN,META,JPM,SPY` |

### 回應

```json
{
  "symbols": [
    {
      "symbol": "NVDA",
      "price": 150.0,
      "volume": 200000000,
      "dollarVolume": 30000000000.0,
      "session": "RTH",
      "price_source": "regular"
    }
  ]
}
```

| 欄位 | 說明 |
|------|------|
| `price` | 顯示用報價（延長時段可能係 pre/post；同 `/api/quote`） |
| `volume` | Yahoo `regularMarketVolume`（股數）；冇量則 `null` |
| `dollarVolume` | `price × volume`；冇量則 `null` |
| `session` / `price_source` | 同報價 API |

排序：`dollarVolume` **DESC**。冇 `volume` 嘅代號排喺後面（唔亂編排名）。無效／未知代號會跳過。

### FE 建議

1. 進頁或每 **幾分鐘** 輪詢一次（Yahoo quote TTL ~15s；唔使秒級）
2. 用回傳順序重排 chip；未有量時維持原 QUICK 順序即可
3. 旁加「活躍≠推薦」小字

---

## `GET /api/quote` 新增欄位

| 欄位 | 說明 |
|------|------|
| `volume` | `regularMarketVolume`（可 `null`） |
| `dollarVolume` | `price × volume`（可 `null`） |
