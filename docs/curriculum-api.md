# Curriculum / Boost API — 基本面選股入門（隨機練習）

給 **软件工程师** 接教材頁、隨機 MC、合規狀態同 1% 加成道具。

教材／題庫喺 repo `curriculum/fundamentals/`（`lesson.md`、`mc_bank.json`）；Docker image 會 COPY 入去。

## 規則（P1–P3）

| 規則 | 條件 |
|------|------|
| **P1** | 持倉 ticker ∩ 本模組 `universe` ≥ 1 |
| **P2** | 該交集由首次達標起 **連續** 持有 ≥ **7** 日；賣出池內最後一隻 → 計時重置 |
| **P3** | MC 分數 ≥ `passScore`（而家 = **5/7**；每次從題庫 **隨機抽 7 題**） |

**加成發放方式（定稿）**：`POST /api/boost/apply` 成功時，按當下組合 **總權益（USD）× 1%** 一次性撥入 **USD 現金**（`cash` balance）。唔改持倉市值倍率。每用戶每內部 `weekId` 只可領一次。

合規計時存在表 `curriculum_compliance(user_id, week_id, compliant_since)`，成交（`_fill`）後更新。

`universe`：`AAPL MSFT JNJ PG JPM XOM SPY`  
內部 `weekId`（合規／加成／交卷鍵，**唔係**用戶可見標籤）：`week1-fundamentals`  
題庫 `bankId`：`fundamentals-basics`（約 32 題；`drawCount=7`）

**用戶面**：標題用「基本面選股入門」／UI「隨機練習」；**唔顯示**「Week 1」／「Week1」。

每週 MC 排行榜有 `topRewardUsd: 1000`（文案／之後發獎用）；而家 endpoint 只回排名，**未自動**派 $1000。

## Auth

所有下列 endpoint 要已登入（session cookie），同其他 `/api/*` 一樣。未登入 → `401`。

跨站 POST 會被 CSRF middleware 擋（Origin ≠ Host → 403）。

---

## `GET /api/curriculum/week/current`

當前教材模組：課文 + 標的池 + **每次請求從題庫隨機抽 `drawCount` 題**（順序亦隨機）。

**200**

```json
{
  "weekId": "week1-fundamentals",
  "title": "基本面選股入門",
  "lesson": "# 課文：基本面選股入門\n…",
  "lessonPath": "curriculum/fundamentals/lesson.md",
  "universe": ["AAPL", "MSFT", "JNJ", "PG", "JPM", "XOM", "SPY"],
  "passScore": 5,
  "total": 7,
  "drawCount": 7,
  "mode": "random",
  "questions": [
    {
      "id": "f03",
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

- `questions` **每次 GET 重新抽樣**；**唔含** `answer` / `explain`（提交前唔洩答案）。
- `title` / `lesson` **唔含**「Week 1」字樣；`weekId` 只係內部鍵。
- `userStatus.mcScore` = 該模組最佳分數；有任何一次及格 → `mcPassed: true`。

---

## `POST /api/curriculum/week/{week_id}/submit`

Body（按 **題目 id** 交答案；順序無關；最多 `drawCount` 條）：

```json
{ "answers": { "f03": "B", "f11": "A", "f01": "B", "f20": "C", "f07": "B", "f15": "A", "f02": "B" } }
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
    {"id": "f03", "correct": true, "answer": "B", "explain": "…"}
  ],
  "submittedAt": 1730000000.0,
  "submittedAtIso": "2024-…"
}
```

- 計分對照 **完整題庫** 以 `id` 對答案；`total` 永遠係 `drawCount`（7），唔係題庫總數。
- 超過 `drawCount` 條答案 → `400`。
- 提交後先喺 `details` 回正確答案同解釋。可重交；排行榜同 `userStatus` 用 **最佳分數**。

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

**400** 常見：未及格 MC、無合規持股、未滿 7 日、已用過。

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

每人一列（該模組最佳分；同分取較早提交）。

---

## 前端建議流程

1. 教材頁：`GET …/week/current` → 顯示 `lesson` + `universe` + **今次抽到嘅** MC（標「隨機練習」，唔標 Week 1）
2. 交卷：`POST …/submit` → 顯示分數／解釋（按 id 計分）
3. 「再答一次」→ 再 `GET current` 重新抽題
4. 持倉頁：輪詢 `GET /api/portfolio/compliance` →「已持 X 日／可唔可以加成」
5. 達標：`POST /api/boost/apply` → toast 顯示 `amount`
6. （可選）MC 排行：`GET …/leaderboard`

帳戶「重設模擬」會清持倉同 `curriculum_compliance`／`curriculum_boosts`（MC 答題紀錄保留）。
