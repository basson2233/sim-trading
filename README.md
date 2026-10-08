# 模擬股票交易平台 (Paper Trading) — v1

網頁版模擬股票交易平台，支援 **港股 (HKD)** 同 **美股 (USD)**，多用戶 + 排行榜，全部用虛擬資金，**唔收手續費**。

## 快速開始

```bash
cd /workspace/sim-trading
./run.sh                 # 第一次會自動建立 .venv 同安裝依賴；之後直接啟動
# 打開 http://localhost:8000  → 未登入會自動轉去 /login，冇帳戶就去 /register 註冊
```

環境變數（可選）：

| 變數 | 預設 | 說明 |
|---|---|---|
| `PORT` / `HOST` | `8000` / `0.0.0.0` | 監聽埠 / 位址 |
| `PRICE_SOURCE` | `auto` | `auto` = 先用 Yahoo，連唔到就自動轉模擬價；`yahoo` = 只用 Yahoo；`sim` = 只用模擬價（離線） |
| `SIM_DB` | `data/sim_trading.db` | SQLite 資料庫路徑 |
| `PENDING_INTERVAL` | `10` | 每幾秒檢查一次限價單是否到價 |
| `COOKIE_SECURE` | `0` | 設成 `1` 會令登入 cookie 加 `Secure`（經 HTTPS 部署時一定要開） |
| `DEV_SHOW_RESET_LINK` | `./run.sh` 預設 `1` | `1` 而且未設定 SMTP 時，忘記密碼嘅回應會帶本機演示用重設連結。正式環境請唔好設，或者設 `0` |
| `APP_BASE_URL` | `http://localhost:8000` | 公開網址，用嚟砌重設連結同 Google redirect URI |
| `SMTP_HOST` `SMTP_PORT` `SMTP_USER` `SMTP_PASSWORD` `SMTP_FROM` | （無） | 五個都設咗先會真係寄重設密碼電郵。`465` 用 SSL，其他埠用 STARTTLS |
| `GOOGLE_CLIENT_ID` `GOOGLE_CLIENT_SECRET` | （無） | 兩個都係空就唔顯示「用 Google 登入」。見下面 |

跑測試：

```bash
.venv/bin/python -m pytest -q
```

## 功能

- **帳戶**：用戶名 + 密碼 + 電郵註冊 / 登入（`/register`、`/login`），新帳戶自動獲發 HKD 1,000,000 + USD 100,000。可以登出、更改密碼、更改電郵、忘記密碼（`/forgot`）。設定咗 Google OAuth 之後可以用 Google 登入。詳見下面「帳戶安全」。
- **報價**：Yahoo Finance chart API（後端代取，報價 cache 15 秒，或有約 15 分鐘延遲）；連唔到時自動用 **模擬隨機漫步價格**，介面會清楚標示「模擬價格」。
- **圖表**：揀股票後顯示價格走勢，可揀 1日 / 5日 / 1個月 / 6個月 / 1年 / 5年，滑鼠移上去睇價格。
- **落單**：市價單、限價單；買入 / 賣出。
  - 市價單即時以現價成交。
  - 限價單如果已經到價就即時成交（以現價，即係唔差過限價）；否則掛單，凍結現金（買）或股份（賣），後台每 10 秒檢查，到價就成交；可以取消。
  - 檢查：現金不足、可賣股數不足、港股每手股數（例如 0700.HK 每手 100、0005.HK 每手 400）、數量要正整數。
- **帳戶**：港元 / 美元兩個獨立現金帳戶；總資產折合港元。
- **持倉**：數量、平均成本、現價、市值、未實現盈虧（金額 + %）。
- **記錄**：成交記錄（含已實現盈虧）、訂單記錄（含狀態）。
- **排行榜**：按總回報率排名，顯示總資產（折合港元）、總盈虧、持倉數、成交次數。
- **重設帳戶**：清除持倉 / 訂單 / 記錄，資金還原。
- **持久化**：SQLite。

## 帳戶安全

- **密碼雜湊**：`hashlib.scrypt`（N=2^14, r=8, p=1），每個用戶獨立 16-byte 隨機 salt，格式 `scrypt$N$r$p$salt$hash`；用 `hmac.compare_digest` 比對。資料庫唔會存明文密碼。
- **規則**：用戶名 2-20 字（中英文、數字、`_`、`-`，唔分大小寫，唔可以重複）；電郵要有效而且唔可以重複（唔分大小寫，存成小寫）；密碼 8-128 字，唔可以同用戶名一樣；註冊要輸入兩次密碼。
- **Session**：登入 / 註冊後發一個 256-bit 隨機 token，放喺 `sim_session` cookie（`HttpOnly`、`SameSite=Lax`、7 日到期；`COOKIE_SECURE=1` 加 `Secure`）。資料庫只存 token 嘅 SHA-256，伺服器端檢查到期時間。登入時會換新 token；登出會喺伺服器刪除 session。
- **授權**：所有交易 / 帳戶 / 報價 / 排行榜 API 都要登入；帳戶 API 一律用 `/api/me/...`，只會處理 session 對應嘅用戶，request 入面寫咩用戶名都唔會理。舊嘅 `/api/u/{username}/...` 已移除。
- **防暴力破解**：同一帳戶連續錯 5 次密碼會鎖 15 分鐘（記錄喺 DB，重啟都有效）；同一 IP 15 分鐘內錯 20 次會暫停登入；同一 IP 每小時最多註冊 10 個帳戶。用戶名唔存在同密碼錯誤顯示同一個訊息，並用假雜湊令回應時間一致。
- **更改密碼**：已有密碼嘅用戶要輸入現有密碼。只用 Google、未設過密碼嘅用戶可以喺帳戶設定直接設第一個密碼（呢個 session 已經用 Google 證明咗身份）；設完之後再改就要舊密碼。改完之後其他裝置嘅 session 會全部失效（目前呢個保持登入）。
- **更改電郵**：登入後撳「更改電郵」，要輸入現有密碼。未有密碼嘅 Google 帳戶要先設定密碼。手動改嘅電郵會標成未驗證。
- **忘記密碼**（`/forgot`）：輸入電郵。無論個電郵有冇登記，回應都係同一句「如果呢個電郵有登記，我哋已經寄出重設連結」，所以唔可以靠佢探測電郵。
  - 只有「有密碼、而且有呢個電郵」嘅帳戶先會出 token。未設定電郵嘅舊帳戶（例如升級前嘅 demo）唔會出 token，要先喺帳戶入面設定電郵。只用 Google、未設密碼嘅帳戶同樣唔出 token（佢哋應該用 Google 登入）；之後喺設定設咗密碼就可以用忘記密碼。
  - Token 係隨機嘅，資料庫只存 SHA-256，30 分鐘過期，用一次就作廢。用咗會登出嗰個用戶所有 session。新密碼喺 `/reset?token=...` 設定。
  - **寄信**：設齊 `SMTP_HOST`、`SMTP_PORT`、`SMTP_USER`、`SMTP_PASSWORD`、`SMTP_FROM` 就會寄一封帶重設連結嘅電郵，回應唔會包含連結。
  - **未設定 SMTP**：唔會寄信。`DEV_SHOW_RESET_LINK=1` 時，回應多一個 `reset_url`，頁面會用黃盒標明「未設定電郵伺服器，以下是本機演示用的重設連結」（`./run.sh` 預設開住，方便本機試）。未設 `DEV_SHOW_RESET_LINK` 就只回嗰句通用訊息，連結寫入 `data/password-resets.log`（有 SMTP 但寄信失敗都會寫入呢度）。
- **用 Google 登入**：伺服器端 OAuth 2.0 authorization-code（唔係淨係前端 token）。`GOOGLE_CLIENT_ID` 係空就唔顯示按鈕，直接打 `/auth/google/start` 會回「未設定 Google 登入」。設定之後登入同註冊頁會出現「用 Google 登入」。Callback 會核對 `state`（CSRF，httpOnly cookie + 伺服器只存 hash、10 分鐘、用一次），再用授權碼換 access token，跟住向 Google userinfo 攞 `email` 同 `sub`：
  - 已有相同 `google_sub` → 登入。
  - 否則，如果有密碼帳戶嘅電郵相同，而且 Google 話 `email_verified` → 連結 `google_sub` 並登入。未驗證就唔連結。
  - 否則開新帳戶：用戶名由電郵 @ 前面衍生（去掉符號、撞名就加數字），冇密碼，電郵寫低，起始資金同其他新用戶一樣，並即時登入（同一個 `sim_session` cookie）。
- **CSRF**：`SameSite=Lax` + JSON API，另外會拒絕 `Origin` 唔係本站嘅寫入請求（403）。Google 用 `state` 參數。

### Google Cloud Console 要做嘅嘢

按鈕只會喺 `GOOGLE_CLIENT_ID` 同 `GOOGLE_CLIENT_SECRET` 都設定咗之後先出現。Redirect URI 係 `{APP_BASE_URL}/auth/google/callback`。預設 `APP_BASE_URL=http://localhost:8000`，所以要登記嘅係：

`http://localhost:8000/auth/google/callback`

喺 Google Cloud Console：Credentials → OAuth client ID → Web application → Authorized redirect URIs，加上面嗰條，然後把 client id / secret 放落環境變數再重啟。


### 舊用戶遷移（v1 → v2）

v1 嘅用戶冇密碼，冇辦法安全咁證明「邊個係邊個」，所以當時升級會刪除冇密碼嘅舊帳戶（備份喺 `data/sim_trading.pre-auth-backup.db`）。而家啟動時只會刪除「冇密碼、冇 Google、又冇電郵」嘅殘留列，**唔會**刪除 Google 帳戶或者已有密碼嘅用戶。電郵 / `google_sub` 用 `ALTER TABLE` 加上去，現有用戶（demo、小明）會保留，只係 `email` 係空，所以用唔到忘記密碼，直到佢哋喺「更改電郵」設定為止。

## 設計決定

- **兩個獨立貨幣帳戶，唔做換匯**：港股只可以用 HKD 買，美股只可以用 USD 買。咁樣最簡單，又唔會有匯率對交易嘅影響。
- **排行榜用港元做基準貨幣**：USD 資產按當前 USD/HKD（Yahoo `HKD=X`，失敗就用 7.8）折算。初始資金都係用同一個匯率折算，所以匯率郁動唔會影響回報率，排名純粹反映交易表現。
- **零手續費**：成交金額 = 價 × 量；平均成本 = 總買入金額 / 股數。
- 已實現盈虧 = 賣出金額 − 平均成本 × 賣出股數（平均成本法）。

## 專案結構

```
app/
  main.py      FastAPI 路由、登入保護、頁面、背景限價單撮合
  auth.py      密碼雜湊、session、忘記密碼、Google OAuth、登入限制
  engine.py    交易引擎（用戶、現金、持倉、訂單、成交、排行榜），SQLite
  quotes.py    YahooFeed / SimFeed / AutoFeed 報價 + 歷史價格
  symbols.py   代號正規化（700 → 0700.HK）、港股每手股數表
static/        login.html、forgot.html、reset.html、index.html / app.js / style.css（純 JS，冇 build step，圖表用 canvas 自己畫）
tests/         pytest：交易引擎、帳戶安全、API
run.sh         一條命令啟動
```

## API 摘要

| Method | Path | 說明 |
|---|---|---|
| POST | `/api/auth/register` `{username, email, password, password_confirm}` | 註冊並登入（設 cookie） |
| POST | `/api/auth/login` `{username, password}` | 登入（設 cookie） |
| POST | `/api/auth/logout` | 登出 |
| GET | `/api/auth/me` | 目前用戶（含電郵、有冇密碼、有冇連結 Google）🔒 |
| GET | `/api/auth/providers` | `{google: true/false}`，登入頁用嚟決定顯示唔顯示 Google 按鈕 |
| POST | `/api/auth/forgot` `{email}` | 申請重設密碼（永遠同一句訊息） |
| POST | `/api/auth/reset` `{token, password, password_confirm}` | 用 token 設新密碼，並登出所有 session |
| POST | `/api/auth/change-password` `{current_password?, new_password, new_password_confirm}` | 更改密碼 🔒（未有密碼就唔使 current） |
| POST | `/api/auth/change-email` `{current_password, email}` | 更改電郵 🔒 |
| GET | `/auth/google/start` | 轉去 Google（未設定 client id 就 400） |
| GET | `/auth/google/callback` | Google 導回；成功就設 session cookie 並轉去 `/` |
| GET | `/api/quote?symbol=700` | 報價（含每手股數、價格來源）🔒 |
| GET | `/api/history?symbol=AAPL&range=1M` | 歷史價格（1D/5D/1M/6M/1Y/5Y）🔒 |
| GET | `/api/me/portfolio` | 帳戶摘要 + 持倉 🔒 |
| POST | `/api/me/orders` `{symbol, side, type, qty, limit_price?}` | 落單 🔒 |
| GET | `/api/me/orders?status=PENDING` | 訂單 🔒 |
| POST | `/api/me/orders/{id}/cancel` | 取消訂單 🔒 |
| GET | `/api/me/trades` | 成交記錄 🔒 |
| POST | `/api/me/reset` | 重設帳戶 🔒 |
| GET | `/api/leaderboard` | 排行榜 🔒 |

🔒 = 要登入（冇有效 session 回 401）。

例子：

```bash
curl -c jar.txt -X POST localhost:8000/api/auth/register -H 'Content-Type: application/json' \
     -d '{"username":"demo","password":"demo-pass-123","password_confirm":"demo-pass-123"}'
curl -b jar.txt -X POST localhost:8000/api/me/orders -H 'Content-Type: application/json' \
     -d '{"symbol":"0700.HK","side":"BUY","type":"MARKET","qty":300}'
curl -b jar.txt localhost:8000/api/me/portfolio
```

## 限制（v1）

- 忘記密碼靠電郵連結，但未設定 SMTP 就唔會真係寄信（見上面）。冇雙重認證；管理員重設仍然可以直接改 DB。
- Google 登入要自己喺 Google Cloud Console 開 OAuth client；未設定環境變數就冇按鈕。
- 每 IP 限制只存喺記憶體（重啟會清零），而且如果放喺 reverse proxy 後面要再設定真實 IP。
- 冇 HTTPS：本機用 HTTP；對外部署要加 HTTPS 同 `COOKIE_SECURE=1`。
- 單一 SQLite 連線 + 全域鎖，啱小型使用；大量用戶要換 PostgreSQL / 連線池。
- 唔理開市時間：休市時市價單都會以最後價成交；Yahoo 報價可能有延遲。
- 冇沽空、冇碎股、冇部分成交；港股價位（tick size）冇檢查。
- 港股每手股數係內置表，未列出嘅股票假設每手 100 股（介面會標示「假設」）。
- 只支援 HKD / USD 報價嘅股票。

## 之後可以加

- 電郵驗證信、比賽模式（指定時段、重設全部人）
- 交易時段 + 收市後掛單、止蝕 / 止賺單、碎股、沽空
- 自選股清單、搜尋股票名稱（自動完成）
- 資產走勢圖（每日快照）、更多指標（MA、成交量）
- 可選手續費 / 印花稅、換匯功能
