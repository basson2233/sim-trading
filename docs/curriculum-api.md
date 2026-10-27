# Curriculum / Boost API — Week 1 基本面選股入門

給 **软件工程师** 接教材頁、每週 MC、合規狀態同 1% 加成道具。

教材檔喺 repo `curriculum/week1/`（`lesson.md`、`mc.json`）；Docker image 會 COPY 入去。

## 規則（P1–P3）

| 規則 | 條件 |
|------|------|
| **P1** | 持倉 ticker ∩ 本週 `universe` ≥ 1 |
| **P2** | 該交集由首次達標起 **連續** 持有 ≥ **7** 日；賣出池內最後一隻 → 計時重置 |
| **P3** | 本週 MC 分數 ≥ `passScore`（Week1 = 5/7） |

**加成發放方式（定稿）**：`POST /api/boost/apply` 成功時，按當下組合 **總權益（USD）× 1%** 一次性撥入 **USD 現金**（`cash` balance）。唔改持倉市值倍率。每用戶每 `weekId` 只可領一次。

合規計時存在表 `curriculum_compliance(user_id, week_id, compliant_since)`，成交（`_fill`）後更新。

Week1 `universe`：`AAPL MSFT JNJ PG JPM XOM SPY`  
`weekId`：`week1-fundamentals`

每週 MC 排行榜有 `topRewardUsd: 1000`（文案／之後發獎用）；而家 endpoint 只回排名，**未自動**派 $1000。

## Auth

所有下列 endpoint 要已登入（session cookie），同其他 `/api/*` 一樣。未登入 → `401`。

跨站 POST 會被 CSRF middleware 擋（Origin ≠ Host → 403）。

---

## `GET /api/curriculum/week/current`

當前教材週（而家固定 Week1）。

**200**

```json
{
  "weekId": "week1-fundamentals",
  "title": "基本面選股入門",
  "lesson": "# Week 1 課文：…",
  "lessonPath": "curriculum/week1/lesson.md",
  "universe": ["AAPL", "MSFT", "JNJ", "PG", "JPM", "XOM", "SPY"],
  "passScore": 5,
  "total": 7,
  "questions": [
    {
      "id": "q1",
      "stem": "…",
      "choices": [{"key": "A", "text": "…"}, {"key": "B", "text": "…"}]
    }
  ],
  "compliance": {"P1": "…", "P2": "…", "P3": "…"},
  "userStatus": {
    "mcScore": null,
    "mcPassed": false,
    "submitted": false
  }
}
```

- `questions` **唔含** `answer` / `explain`（提交前唔洩答案）。
- `userStatus.mcScore` = 該週最佳分數；有任何一次及格 → `mcPassed: true`。

---

## `POST /api/curriculum/week/{week_id}/submit`

Body：

```json
{ "answers": { "q1": "B", "q2": "B", "q3": "C", "q4": "B", "q5": "A", "q6": "B", "q7": "B" } }
```

**200**

```json
{
  "weekId": "week1-fundamentals",
  "score": 7,
  "passed": true,
  "total": 7,
  "passScore": 5,
  "details": [
    {"id": "q1", "correct": true, "answer": "B", "explain": "…"}
  ],
  "submittedAt": 1730000000.0,
  "submittedAtIso": "2024-…"
}
```

提交後先喺 `details` 回正確答案同解釋。可重交；排行榜同 `userStatus` 用 **最佳分數**。

未知 `week_id` / 壞 body → `400`。

---

## `GET /api/portfolio/compliance`

**200**

```json
{
  "ok": true,
  "weekId": "week1-fundamentals",
  "universe": ["AAPL", "…"],
  "matchedTickers": ["AAPL"],
  "compliantSince": 1730000000.0,
  "compliantSinceIso": "…",
  "heldDays": 7.12,
  "holdDaysRequired": 7,
  "mcScore": 6,
  "mcPassed": true,
  "mcSubmitted": true,
  "passScore": 5,
  "boosted": false,
  "canBoost": true
}
```

- `ok` = P1∧P2（持滿日數）；**唔包** P3。
- `canBoost` = `mcPassed && ok && !boosted`。

---

## `POST /api/boost/apply`

無 body。

**200**（成功）

```json
{
  "ok": true,
  "credited": true,
  "amount": 10000.0,
  "equityAtCredit": 1000000.0,
  "weekId": "week1-fundamentals",
  "creditedAt": 1730000000.0,
  "creditedAtIso": "…",
  "kind": "cash_credit_pct_equity",
  "pct": 0.01
}
```

**400** 常見：未及格 MC、無合規持股、未滿 7 日、本週已用過。

成功後 `GET /api/me/portfolio` 嘅 USD `cash`／`equity` 會即時反映加成。

---

## `GET /api/curriculum/week/{week_id}/leaderboard`

**200**

```json
{
  "weekId": "week1-fundamentals",
  "rows": [
    {
      "rank": 1,
      "userId": 8,
      "username": "alice",
      "score": 7,
      "passed": true,
      "submittedAt": 1730000000.0,
      "submittedAtIso": "…"
    }
  ],
  "topRewardUsd": 1000,
  "asOf": "…"
}
```

每人一列（該週最佳分；同分取較早提交）。

---

## 前端建議流程

1. 教材頁：`GET …/week/current` → 顯示 `lesson` + `universe` + MC  
2. 交卷：`POST …/submit` → 顯示分數／解釋  
3. 持倉頁：輪詢 `GET /api/portfolio/compliance` →「已持 X 日／可唔可以加成」  
4. 達標：`POST /api/boost/apply` → toast 顯示 `amount`  
5. （可選）MC 排行：`GET …/leaderboard`

帳戶「重設模擬」會清持倉同 `curriculum_compliance`／`curriculum_boosts`（MC 答題紀錄保留）。
