# Curriculum UI（前端）

導航 **教材／學習** → `#learn`。實作：`static/curriculum.js` + `static/index.html` 內 `#tab-learn`。

## 內容來源

1. **優先** `GET /api/curriculum/week/current`（見 `docs/curriculum-api.md`）
2. **後備** 靜態檔（offline／API 未部署）：
   - `/static/curriculum/week1/lesson.md`
   - `/static/curriculum/week1/mc.json`（含 answer，僅本地計分用）
3. 後端教材權威目錄：`curriculum/week1/`（同內容；Dockerfile COPY）

## 前端行為

| 子頁 | 行為 |
|------|------|
| 課文 | Markdown→HTML；右側標的池 chip → 跳 `#trade` 載入代號 |
| 每週 MC | API 模式：`POST /api/curriculum/week/{weekId}/submit`；否則本地對 `answer` 計分。及格線 `passScore`（5/7）。提交後顯示 explain。可重答。localStorage 備份：`simCurriculumAttempt:<user>:<weekId>` |
| 合規／加成 | `GET /api/portfolio/compliance`；失敗則用持倉 ∩ universe（無持倉天數）。`canBoost` 時啟用掣 → `POST /api/boost/apply`；否則 disabled + 說明 |

## 對接 API（同 curriculum-api.md）

- `GET /api/curriculum/week/current`
- `POST /api/curriculum/week/{week_id}/submit`
- `GET /api/portfolio/compliance`
- `POST /api/boost/apply`
- （可選）`GET /api/curriculum/week/{week_id}/leaderboard` — UI 尚未做排行區塊

## P1–P3

- P1 holdings ∩ universe ≥ 1（Week1：AAPL MSFT JNJ PG JPM XOM SPY）
- P2 連續 ≥ 7 日
- P3 MC ≥ passScore
