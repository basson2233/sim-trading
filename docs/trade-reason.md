# 交易理由（reason）— Order / Trade API

給 **软件工程师**：下單可選填交易理由；亦可事後新增／修改／清空。

## `POST /api/me/orders` — 落單時（**可選**）

現有欄位不變，**新增可選** `reason`：

| 欄位 | 類型 | 必填 | 說明 |
|------|------|------|------|
| `symbol` | string | ✓ | 美股代號 |
| `side` | string | ✓ | `BUY` / `SELL` |
| `type` | string | | `MARKET`（預設）或 `LIMIT` |
| `qty` | number | ✓ | 正整數股數 |
| `limit_price` | number | 限價單時 | 限價 |
| **`reason`** | string | 否 | 交易理由；可省略、跳過、或空白 |

### 驗證（落單同 PATCH 共用）

- 缺省／`null`／`""`／純空白 → **接受**，存成 `null`（唔會 400）
- 有內容 → trim 前後空白
- trim 後超過 **500** 字 → **400** `{"detail":"交易理由唔可以超過 500 字"}`

### 請求例子（有理由）

```json
{
  "symbol": "AAPL",
  "side": "BUY",
  "type": "MARKET",
  "qty": 10,
  "reason": "基本面練習：買入標的池內蘋果"
}
```

唔帶 `reason`、或 `"reason": ""` 都一樣可以成交。

### 成功回應

訂單物件帶 `reason`（未填時為 `null`）。

限價單之後成交時，`trades.reason` 會複製落單時嘅 `orders.reason`。

---

## 事後改理由

### `PATCH /api/me/orders/{order_id}/reason`

改自己嘅訂單理由；同時同步所有關聯 `trades`。

```json
{ "reason": "事後補寫：跟住財報買入" }
```

- 空白／省略 → 清空（存 `null`）
- 唔係自己嘅單 → **400** `{"detail":"搵唔到呢張訂單"}`
- 成功 → 回更新後嘅 **order** 物件

### `PATCH /api/me/trades/{trade_id}/reason`

改自己嘅成交理由；同時 mirror 去父訂單。

```json
{ "reason": "補寫成交理由" }
```

- 規則同上；成功 → 回更新後嘅 **trade** 物件

---

## 讀取歷史

以下每筆都有 `reason`（未填／已清空為 `null`）：

- `GET /api/me/orders`（可加 `?status=PENDING`）
- `GET /api/me/trades`
- `GET /api/users/{username}/view` → `trades[]`

## FE 建議

- 落單彈窗：**可跳過**；有填就 trim 後一齊 POST
- 訂單／成交列表可提供「編輯理由」→ 打對應 `PATCH`
- 超過 500 字用 `detail` 顯示錯誤
