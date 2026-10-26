# Admin API — 用戶刪除 / privacy wipe

受保護嘅後台 API，畀管理員按 **user id** 查詢同刪除帳戶，並清晒該用戶所有相關數據（隱私）。

> 前端 `/admin` 頁由 **软件工程师** 負責；呢份文件係後端合約。
>
> 需要 Railway（或本地）環境變數 `ADMIN_API_KEY`。未設定／空白 → admin 停用（503）。

## Auth

所有 `/api/admin/*` 都要帶 header：

```
X-Admin-Key: <ADMIN_API_KEY>
```

- 用 `hmac.compare_digest` 做 constant-time 比對。
- Key 未設定 → `503` `{ "detail": "admin disabled" }`
- Key 錯 → `401` `{ "detail": "unauthorized" }`

唔好喺前端寫死 key；admin 頁應由操作者輸入或經安全渠道注入。

## Endpoints

### `GET /api/admin/users/{user_id}`

隱私安全嘅用戶摘要（**唔會**回傳 email / password / google_sub）。

**200**

```json
{
  "id": 42,
  "username": "u753396",
  "created_at": 1730000000.0,
  "has_google": true,
  "has_email": true
}
```

**404** — 用戶唔存在。

### `DELETE /api/admin/users/{user_id}`

1. 用 id 搵 username  
2. `RoomStore.purge_user(username)` — 踢走所有房間座位（包括 fighting），best-effort 關 WebSocket，並 broadcast 剩餘玩家  
3. DB wipe：positions / orders / trades / cash / sessions / password_resets / fighter_matches（作為 player 或 opponent）／ users 列  

**200**

```json
{
  "ok": true,
  "id": 42,
  "username": "u753396",
  "deleted": true
}
```

`username` 係刪除前嘅公開名稱，方便 log／UI 確認。

**404** — 用戶唔存在（第二次刪同一 id 亦係 404）。

## 房間記憶體

`app.state.rooms`（`RoomStore`）係 process 內 in-memory。刪除時會：

- 離開該用戶所在嘅所有房間（reuse `leave`；房空則移除）
- 收集其 WebSocket，background close（code `4401`）
- 若仲有同伴，broadcast 更新後嘅 room view

單 worker（Railway/uvicorn）先夠用；多 worker 要 Redis 之後再傾。

## 同舊 one-shot env 嘅關係

Startup 仍然支援 `DELETE_USER_USERNAME`[+`DELETE_USER_EMAIL`] one-shot（redeploy 後記得 unset）。正式後台請用呢個 Admin API。
