# Curriculum UI（前端）

導航 **教材／學習** → `#learn`。實作：`static/curriculum.js` + `static/index.html` 內 `#tab-learn`。

用戶可見標題：**隨機練習**（唔顯示 Week 1／本週編號）。內部仍可呼叫 `/api/curriculum/week/*`。

## 內容來源

1. **優先** `GET /api/curriculum/week/current`（見 `docs/curriculum-api.md`）— 回傳題目後前端再 **shuffle 題序**
2. **後備** 靜態題庫（**publicOnly**：只有 stem／choices，**無 answer／explain**；判分必須走 API）：
   - `/static/curriculum/lesson.md`
   - `/static/curriculum/mc_bank_fundamentals.json`（大題庫 metadata；每次抽 `drawCount`（預設 7）題）
   - 舊路徑 fallback：`/static/curriculum/week1/lesson.md`、`mc.json`
3. 完整答案庫只在後端 `curriculum/fundamentals/`（Dockerfile COPY；唔掛 `/static`）

## 前端行為

| 子頁 | 行為 |
|------|------|
| 課文 | Markdown→HTML；右側標的池 chip → 跳 `#trade` 載入代號 |
| 小測 | API：`POST /api/curriculum/week/{weekId}/submit`（唯一判分路徑）。靜態後備無答案鍵。及格線 `passScore`（5/7）。每次作答／「再答一次」會重新抽／打亂題目。localStorage：`simCurriculumAttempt:<user>:<weekId>` |
| 合規／加成 | `GET /api/portfolio/compliance`；失敗則用持倉 ∩ universe（無持倉天數）。`canBoost` 時啟用掣 → `POST /api/boost/apply` |

## 對接 API（同 curriculum-api.md）

- `GET /api/curriculum/week/current`
- `POST /api/curriculum/week/{week_id}/submit`
- `GET /api/portfolio/compliance`
- `POST /api/boost/apply`

## P1–P3

- P1 holdings ∩ universe ≥ 1（AAPL MSFT JNJ PG JPM XOM SPY）
- P2 連續 ≥ 7 日
- P3 小測 ≥ passScore
