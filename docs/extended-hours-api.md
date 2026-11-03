# 盤前／盤後（Extended Hours）API

給 **软件工程师**：美股模擬盤支援 **PRE + AFTER** 延長時段限價；**唔支援** 24h 夜盤／期貨 overnight。

教學提示文案（前端頂欄／下單）：**「非常規交易時段，價格同成交可能較差」**。

## Session 時鐘（美東 `America/New_York`）

| Session | 時間（ET，半開區間） | 下單 |
|---------|----------------------|------|
| `PRE` | 04:00–09:30 | 只限價 `LIMIT` |
| `RTH` | 09:30–16:00 | 市價 + 限價（同舊） |
| `AFTER` | 16:00–20:00 | 只限價 `LIMIT` |
| `CLOSED` | 其餘＋週末 | 拒市價；限價可排隊等下一段開市 |

`overnight_supported` 永遠係 `false`。

---

## `GET /api/market/session`

需登入。

```json
{
  "session": "PRE",
  "exchange_tz": "America/New_York",
  "server_time_et": "2026-11-03T08:15:00-05:00",
  "extended_hours_supported": true,
  "overnight_supported": false
}
```

FE：頂欄顯示 `session`；`PRE`／`AFTER` 時禁用市價、顯示風險提示。

---

## `GET /api/quote?symbol=AAPL`

既有欄位外，新增：

| 欄位 | 說明 |
|------|------|
| `session` | 報價當下時段 `PRE`／`RTH`／`AFTER`／`CLOSED` |
| `price_source` | `extended`（Yahoo pre/post 價）／`regular`／`regular_fallback`（延長時段冇獨立價時用日盤價）／`simulated` |
| `source` | 數據源：`yahoo`／`simulated`／`test`（同舊） |

盤前優先 `preMarketPrice`，盤後優先 `postMarketPrice`；冇就 fallback 日盤價並標 `regular_fallback`。

---

## `POST /api/me/orders`

| 欄位 | 必填 | 說明 |
|------|------|------|
| …既有 | | `symbol`／`side`／`type`／`qty`／`limit_price`／`reason` |
| `session` | 否 | 傳 `"extended"` 強制延長時段規則（只接受 `LIMIT`）；省略則跟即時 `GET /api/market/session` |

### 規則

- `PRE`／`AFTER`（或 `session=extended`）：`type=MARKET` → **400**，訊息說明只接受限價
- `CLOSED`：`MARKET` → **400**；`LIMIT` → 接受，`status=PENDING`（排隊，唔即時撮合）
- `RTH`：行為同舊（市價即時成交；限價可即時或掛單）

成功回應訂單物件帶：

- `session`：落單當下時段標籤
- `price_source`：所用報價來源標記

成交 `GET /api/me/trades` 同樣有 `session`（成交當下時段）。

---

## 撮合

- 只在 `PRE`／`RTH`／`AFTER` 跑 `process_pending`
- `CLOSED` 唔撮合（掛單留到下一段）
- 延長時段用延長報價（或 `regular_fallback`）對限價，規則同日盤（買：市價 ≤ 限價；賣：市價 ≥ 限價）

---

## FE 建議

1. 輪詢或進頁打 `GET /api/market/session`
2. `PRE`／`AFTER`／`CLOSED`：市價按鈕 disable；只開限價
3. 顯示「非常規交易時段，價格同成交可能較差」
4. 訂單／成交列表加時段標籤（`session`）
5. `overnight`／夜盤 UI 顯示「暫未支援」即可
