"use strict";
const $ = (s) => document.querySelector(s);
const $$ = (s) => [...document.querySelectorAll(s)];
const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[c]));
const fmt = (n, d = 2) => n == null || isNaN(n) ? "-" : Number(n).toLocaleString("en-US", {minimumFractionDigits: d, maximumFractionDigits: d});
const fmtPx = (n) => n == null ? "-" : fmt(n, n < 10 ? 3 : 2);
const sign = (n) => (n > 0 ? "+" : "");
const cls = (n) => (n > 0 ? "up" : n < 0 ? "down" : "");
const pct = (n) => n == null ? "-" : `${sign(n)}${fmt(n, 2)}%`;
const tHK = (iso) => iso ? iso.replace("T", " ").slice(0, 19).replace(/\+08:00$/, "") : "-";
const SIDE = {BUY: "買入", SELL: "賣出"}, TYPE = {MARKET: "市價", LIMIT: "限價"};
const STATUS = {FILLED: "已成交", PENDING: "等待成交", CANCELLED: "已取消"};
const QUICK = ["0700.HK", "0005.HK", "9988.HK", "3690.HK", "1810.HK", "AAPL", "TSLA", "NVDA", "MSFT"];
const RANGES = [["1D", "1日"], ["5D", "5日"], ["1M", "1個月"], ["6M", "6個月"], ["1Y", "1年"], ["5Y", "5年"]];

const state = {
  user: null,
  symbol: localStorage.getItem("simSymbol") || "0700.HK",
  quote: null, range: "1M", side: "BUY", type: "MARKET", hist: "trades",
  portfolio: null, chart: null,
};

async function api(path, opts = {}) {
  const res = await fetch(path, {headers: {"Content-Type": "application/json"}, ...opts,
    body: opts.body ? JSON.stringify(opts.body) : undefined});
  const data = await res.json().catch(() => ({}));
  if (res.status === 401 && !opts.noRedirect) { location.href = "/login"; throw new Error("請先登入"); }
  if (!res.ok) throw new Error(data.detail ? (typeof data.detail === "string" ? data.detail : "輸入有誤") : `HTTP ${res.status}`);
  return data;
}
const U = () => "/api/me";

function toast(msg) {
  const t = $("#toast"); t.textContent = msg; t.classList.remove("hidden");
  clearTimeout(toast._t); toast._t = setTimeout(() => t.classList.add("hidden"), 3000);
}

// ---------------------------------------------------------------- session
async function logout() {
  try { await api("/api/auth/logout", {method: "POST"}); } catch {}
  location.href = "/login";
}
function applyMe(me) {
  state.user = me.username;
  state.hasPassword = !!me.has_password;
  state.email = me.email || "";
  $("#userName").textContent = me.username;
  $("#userEmail").textContent = me.email ? "· " + me.email : "· 未設定電郵";
  $("#changePwBtn").textContent = state.hasPassword ? "更改密碼" : "設定密碼";
}
function openPw(show) {
  $("#pwModal").classList.toggle("hidden", !show);
  if (show) {
    $("#pwForm").reset(); $("#pwMsg").textContent = "";
    $("#pwTitle").textContent = state.hasPassword ? "更改密碼" : "設定密碼";
    $("#pwCurRow").classList.toggle("hidden", !state.hasPassword);
    (state.hasPassword ? $("#pwCur") : $("#pwNew")).focus();
  }
}
async function changePw(e) {
  e.preventDefault();
  const m = $("#pwMsg");
  if ($("#pwNew").value !== $("#pwNew2").value) { m.className = "msg err"; m.textContent = "❌ 兩次輸入嘅新密碼唔一樣"; return; }
  const body = {new_password: $("#pwNew").value, new_password_confirm: $("#pwNew2").value};
  if (state.hasPassword) body.current_password = $("#pwCur").value;
  try {
    await api("/api/auth/change-password", {method: "POST", body});
    openPw(false); state.hasPassword = true; $("#changePwBtn").textContent = "更改密碼";
    toast("密碼已更改 ✅");
  } catch (err) { m.className = "msg err"; m.textContent = "❌ " + err.message; }
}
function openEmail(show) {
  $("#emailModal").classList.toggle("hidden", !show);
  if (show) { $("#emailForm").reset(); $("#emMsg").textContent = ""; $("#emEmail").value = state.email || ""; $("#emPw").focus(); }
}
async function changeEmail(e) {
  e.preventDefault();
  const m = $("#emMsg");
  try {
    await api("/api/auth/change-email", {method: "POST", body: {current_password: $("#emPw").value, email: $("#emEmail").value.trim()}});
    state.email = $("#emEmail").value.trim().toLowerCase();
    $("#userEmail").textContent = "· " + state.email;
    openEmail(false); toast("電郵已更改 ✅");
  } catch (err) { m.className = "msg err"; m.textContent = "❌ " + err.message; }
}

// ---------------------------------------------------------------- quote + chart
async function loadSymbol(sym) {
  try {
    const q = await api(`/api/quote?symbol=${encodeURIComponent(sym)}`);
    state.quote = q; state.symbol = q.symbol; localStorage.setItem("simSymbol", q.symbol);
    renderQuote(); updateOrderForm(true); loadChart();
  } catch (e) { toast(e.message); }
}
async function refreshQuote() {
  if (!state.symbol) return;
  try { state.quote = await api(`/api/quote?symbol=${encodeURIComponent(state.symbol)}`); renderQuote(); updateEstimate(); } catch {}
}
function renderQuote() {
  const q = state.quote; if (!q) return;
  const lot = q.market === "HK" ? `・每手 ${q.lot_size} 股${q.lot_size_known ? "" : "（假設）"}` : "";
  $("#quoteHead").innerHTML = `
    <span class="name">${esc(q.name)} <span class="muted">${esc(q.symbol)}</span></span>
    <span class="px ${cls(q.change)}">${fmtPx(q.price)}</span>
    <span class="${cls(q.change)}">${sign(q.change)}${fmtPx(q.change)} (${pct(q.change_pct)})</span>
    <span class="muted">${q.currency}${lot}・${q.source === "yahoo" ? "Yahoo Finance（或有延遲）" : "⚠️ 模擬價格"}</span>`;
  setSourceBadge(q.source);
}
function setSourceBadge(src) {
  const b = $("#sourceBadge");
  b.className = "badge " + (src === "yahoo" ? "live" : "sim");
  b.textContent = src === "yahoo" ? "報價來源：Yahoo Finance（延遲報價）" : "報價來源：模擬價格（離線）";
}
async function loadChart() {
  $("#chartMsg").textContent = "載入中…";
  try {
    const h = await api(`/api/history?symbol=${encodeURIComponent(state.symbol)}&range=${state.range}`);
    state.chart = h; $("#chartMsg").textContent = h.points.length ? "" : "暫時冇圖表數據";
    drawChart();
  } catch (e) { state.chart = null; drawChart(); $("#chartMsg").textContent = e.message; }
}
function drawChart(hoverX) {
  const cv = $("#chart"), ctx = cv.getContext("2d"), dpr = window.devicePixelRatio || 1;
  const W = cv.clientWidth, H = cv.clientHeight;
  cv.width = W * dpr; cv.height = H * dpr; ctx.setTransform(dpr, 0, 0, dpr, 0, 0); ctx.clearRect(0, 0, W, H);
  const h = state.chart; if (!h || !h.points.length) return;
  const pts = h.points, ys = pts.map((p) => p[1]);
  let lo = Math.min(...ys), hi = Math.max(...ys); if (lo === hi) { lo *= 0.99; hi *= 1.01; }
  const pad = (hi - lo) * 0.08; lo -= pad; hi += pad;
  const L = 8, R = 64, T = 10, B = 26, cw = W - L - R, ch = H - T - B;
  const x = (i) => L + (pts.length === 1 ? cw / 2 : (i / (pts.length - 1)) * cw);
  const y = (v) => T + (1 - (v - lo) / (hi - lo)) * ch;
  const base = state.range === "1D" && h.prev_close ? h.prev_close : ys[0];
  const up = ys[ys.length - 1] >= base, col = up ? "#16c784" : "#ea3943";
  ctx.font = "11px sans-serif"; ctx.fillStyle = "#8b97a7"; ctx.strokeStyle = "#263040"; ctx.lineWidth = 1;
  for (let k = 0; k <= 4; k++) {
    const v = lo + ((hi - lo) * k) / 4, yy = y(v);
    ctx.beginPath(); ctx.moveTo(L, yy); ctx.lineTo(L + cw, yy); ctx.stroke();
    ctx.fillText(fmtPx(v), L + cw + 6, yy + 4);
  }
  const intraday = state.range === "1D" || state.range === "5D";
  const lab = (t) => { const d = new Date(t * 1000);
    const o = {timeZone: pts[0] && state.symbol.endsWith(".HK") ? "Asia/Hong_Kong" : "America/New_York"};
    return intraday ? d.toLocaleString("zh-HK", {...o, month: state.range === "5D" ? "numeric" : undefined, day: state.range === "5D" ? "numeric" : undefined, hour: "2-digit", minute: "2-digit", hour12: false})
      : d.toLocaleDateString("zh-HK", {...o, year: state.range === "5Y" ? "numeric" : undefined, month: "numeric", day: "numeric"}); };
  for (let k = 0; k < 5; k++) {
    const i = Math.round((k / 4) * (pts.length - 1)); const s = lab(pts[i][0]);
    const tw = ctx.measureText(s).width; ctx.fillText(s, Math.min(Math.max(x(i) - tw / 2, L), L + cw - tw), H - 8);
  }
  if (state.range === "1D" && h.prev_close) {
    ctx.setLineDash([4, 4]); ctx.strokeStyle = "#8b97a7"; ctx.beginPath();
    ctx.moveTo(L, y(h.prev_close)); ctx.lineTo(L + cw, y(h.prev_close)); ctx.stroke(); ctx.setLineDash([]);
  }
  const g = ctx.createLinearGradient(0, T, 0, T + ch); g.addColorStop(0, up ? "rgba(22,199,132,.28)" : "rgba(234,57,67,.28)"); g.addColorStop(1, "rgba(0,0,0,0)");
  ctx.beginPath(); pts.forEach((p, i) => (i ? ctx.lineTo(x(i), y(p[1])) : ctx.moveTo(x(i), y(p[1]))));
  ctx.strokeStyle = col; ctx.lineWidth = 1.8; ctx.stroke();
  ctx.lineTo(x(pts.length - 1), T + ch); ctx.lineTo(x(0), T + ch); ctx.closePath(); ctx.fillStyle = g; ctx.fill();
  const tip = $("#chartTip");
  if (hoverX == null || hoverX < L || hoverX > L + cw) { tip.classList.add("hidden"); return; }
  const i = Math.round(((hoverX - L) / cw) * (pts.length - 1)), p = pts[i];
  ctx.strokeStyle = "#8b97a7"; ctx.lineWidth = 1; ctx.beginPath(); ctx.moveTo(x(i), T); ctx.lineTo(x(i), T + ch); ctx.stroke();
  ctx.fillStyle = col; ctx.beginPath(); ctx.arc(x(i), y(p[1]), 4, 0, 7); ctx.fill();
  tip.innerHTML = `${esc(lab(p[0]))}<br><b>${fmtPx(p[1])}</b> ${h.currency || ""}`;
  tip.classList.remove("hidden"); tip.style.left = Math.min(x(i) + 10, W - 120) + "px"; tip.style.top = "8px";
}

// ---------------------------------------------------------------- order form
function lot() { return state.quote ? state.quote.lot_size : 1; }
function updateOrderForm(resetQty) {
  const q = state.quote; if (!q) return;
  $("#oSymbol").value = `${q.symbol}  ${q.name}`;
  if (resetQty) $("#oQty").value = q.market === "HK" ? q.lot_size : 1;
  $("#oQty").step = lot(); $("#oQty").min = lot();
  $("#lotHint").textContent = q.market === "HK" ? `港股按手買賣：每手 ${q.lot_size} 股${q.lot_size_known ? "" : "（未知每手股數，假設 100）"}` : "美股最少 1 股";
  if (state.type === "LIMIT" && !$("#oLimit").value) $("#oLimit").value = q.price;
  updateEstimate();
}
function updateEstimate() {
  const q = state.quote; if (!q) return;
  const qty = Number($("#oQty").value) || 0;
  const px = state.type === "LIMIT" ? Number($("#oLimit").value) || 0 : q.price;
  const amt = qty * px, p = state.portfolio;
  const acct = p && p.accounts.find((a) => a.currency === q.currency);
  const pos = p && p.positions.find((x) => x.symbol === q.symbol);
  const lots = q.market === "HK" && q.lot_size ? `（${fmt(qty / q.lot_size, qty % q.lot_size ? 2 : 0)} 手）` : "";
  $("#estimate").innerHTML = `
    <div>預計${state.side === "BUY" ? "金額" : "收入"}：<b>${q.currency} ${fmt(amt)}</b> ${lots}</div>
    <div class="muted">${state.type === "MARKET" ? "以現價" : "以限價"} ${fmtPx(px)} 計・免手續費</div>
    <div class="muted">可用現金：${q.currency} ${acct ? fmt(acct.available) : "-"}　可賣股數：${pos ? fmt(pos.available_qty, 0) : 0}</div>`;
  const b = $("#submitBtn");
  b.textContent = `確認${SIDE[state.side]}`; b.className = "btn big " + (state.side === "BUY" ? "primary" : "sellmode");
}
async function submitOrder(ev) {
  ev.preventDefault();
  const q = state.quote; if (!q) return;
  const body = {symbol: q.symbol, side: state.side, type: state.type, qty: Number($("#oQty").value)};
  if (state.type === "LIMIT") body.limit_price = Number($("#oLimit").value);
  const msg = $("#orderMsg"); $("#submitBtn").disabled = true;
  try {
    const o = await api(`${U()}/orders`, {method: "POST", body});
    msg.className = "msg ok";
    msg.textContent = o.status === "FILLED"
      ? `✅ 已成交：${SIDE[o.side]} ${o.symbol} ${fmt(o.qty, 0)} 股 @ ${fmtPx(o.fill_price)}`
      : `⏳ 限價單已提交，等待成交（${SIDE[o.side]} ${fmt(o.qty, 0)} 股 @ ${fmtPx(o.limit_price)}）`;
    refreshAccount();
  } catch (e) { msg.className = "msg err"; msg.textContent = "❌ " + e.message; }
  finally { $("#submitBtn").disabled = false; }
}

// ---------------------------------------------------------------- account
function renderSummary(p) {
  const t = p.total, fx = p.fx.USDHKD;
  const acctCard = (a) => `<div class="card"><h4>${a.currency === "HKD" ? "港元帳戶（港股）" : "美元帳戶（美股）"}</h4>
    <div class="big">${a.currency} ${fmt(a.equity)}</div>
    <div class="kv"><span>現金</span><span>${fmt(a.cash)}</span><span>可用現金</span><span>${fmt(a.available)}</span>
    <span>持倉市值</span><span>${fmt(a.market_value)}</span>
    <span>未實現盈虧</span><span class="${cls(a.unrealized_pnl)}">${sign(a.unrealized_pnl)}${fmt(a.unrealized_pnl)}</span>
    <span>已實現盈虧</span><span class="${cls(a.realized_pnl)}">${sign(a.realized_pnl)}${fmt(a.realized_pnl)}</span>
    <span>回報率</span><span class="${cls(a.return_pct)}">${pct(a.return_pct)}</span></div></div>`;
  $("#summaryCards").innerHTML = `<div class="card"><h4>總資產（折合港元）</h4>
    <div class="big">HKD ${fmt(t.equity)}</div>
    <div class="kv"><span>總盈虧</span><span class="${cls(t.pnl)}">${sign(t.pnl)}${fmt(t.pnl)}</span>
    <span>總回報率</span><span class="${cls(t.return_pct)}">${pct(t.return_pct)}</span>
    <span>初始資金</span><span>${fmt(t.initial)}</span><span>匯率 USD/HKD</span><span>${fmt(fx, 4)}</span></div></div>` +
    p.accounts.map(acctCard).join("");
}
function renderPositions(p) {
  const rows = p.positions.map((x) => `<tr>
    <td class="l"><span class="sym" data-sym="${esc(x.symbol)}">${esc(x.symbol)}</span></td><td class="l">${esc(x.name)}</td>
    <td>${x.currency}</td><td>${fmt(x.qty, 0)}${x.reserved_qty ? ` <small class="muted">(凍結 ${fmt(x.reserved_qty, 0)})</small>` : ""}</td>
    <td>${fmtPx(x.avg_cost)}</td><td>${fmtPx(x.price)} <small class="${cls(x.day_change_pct)}">${pct(x.day_change_pct)}</small></td>
    <td>${fmt(x.market_value)}</td>
    <td class="${cls(x.unrealized_pnl)}">${sign(x.unrealized_pnl)}${fmt(x.unrealized_pnl)} (${pct(x.unrealized_pnl_pct)})</td>
    <td><button class="btn ghost small" data-sell="${esc(x.symbol)}" data-qty="${x.available_qty}">賣出</button></td></tr>`).join("");
  $("#posTable").innerHTML = `<tr><th class="l">代號</th><th class="l">名稱</th><th>貨幣</th><th>數量</th><th>平均成本</th><th>現價</th><th>市值</th><th>未實現盈虧</th><th></th></tr>` +
    (rows || `<tr><td colspan="9" class="empty">暫時未有持倉，揀隻股票買入試吓！</td></tr>`);
}
function renderOpen(list) {
  const rows = list.map((o) => `<tr><td class="l">#${o.id}</td><td class="l">${tHK(o.created_at_iso)}</td>
    <td class="l"><span class="sym" data-sym="${esc(o.symbol)}">${esc(o.symbol)}</span></td><td><span class="pill ${o.side}">${SIDE[o.side]}</span></td>
    <td>${TYPE[o.type]}</td><td>${fmt(o.qty, 0)}</td><td>${fmtPx(o.limit_price)}</td>
    <td><button class="btn ghost small" data-cancel="${o.id}">取消</button></td></tr>`).join("");
  $("#openTable").innerHTML = `<tr><th class="l">單號</th><th class="l">時間 (HKT)</th><th class="l">代號</th><th>方向</th><th>類型</th><th>數量</th><th>限價</th><th></th></tr>` +
    (rows || `<tr><td colspan="8" class="empty">冇未成交訂單</td></tr>`);
}
async function renderHistory() {
  if (!state.user) return;
  if (state.hist === "trades") {
    const list = await api(`${U()}/trades`);
    const rows = list.map((t) => `<tr><td class="l">${tHK(t.executed_at_iso)}</td>
      <td class="l"><span class="sym" data-sym="${esc(t.symbol)}">${esc(t.symbol)}</span></td><td class="l">${esc(t.name)}</td>
      <td><span class="pill ${t.side}">${SIDE[t.side]}</span></td><td>${fmt(t.qty, 0)}</td><td>${fmtPx(t.price)}</td>
      <td>${t.currency} ${fmt(t.amount)}</td>
      <td class="${cls(t.realized_pnl)}">${t.realized_pnl == null ? "-" : sign(t.realized_pnl) + fmt(t.realized_pnl)}</td>
      <td>${t.price_source === "yahoo" ? "Yahoo" : "模擬"}</td></tr>`).join("");
    $("#histTable").innerHTML = `<tr><th class="l">成交時間 (HKT)</th><th class="l">代號</th><th class="l">名稱</th><th>方向</th><th>數量</th><th>成交價</th><th>金額</th><th>已實現盈虧</th><th>價格來源</th></tr>` +
      (rows || `<tr><td colspan="9" class="empty">暫時未有成交</td></tr>`);
  } else {
    const list = await api(`${U()}/orders`);
    const rows = list.map((o) => `<tr><td class="l">#${o.id}</td><td class="l">${tHK(o.created_at_iso)}</td>
      <td class="l"><span class="sym" data-sym="${esc(o.symbol)}">${esc(o.symbol)}</span></td>
      <td><span class="pill ${o.side}">${SIDE[o.side]}</span></td><td>${TYPE[o.type]}</td><td>${fmt(o.qty, 0)}</td>
      <td>${o.limit_price == null ? "-" : fmtPx(o.limit_price)}</td><td>${o.fill_price == null ? "-" : fmtPx(o.fill_price)}</td>
      <td><span class="pill ${o.status}">${STATUS[o.status]}</span></td><td class="l">${tHK(o.updated_at_iso)}</td></tr>`).join("");
    $("#histTable").innerHTML = `<tr><th class="l">單號</th><th class="l">落單時間 (HKT)</th><th class="l">代號</th><th>方向</th><th>類型</th><th>數量</th><th>限價</th><th>成交價</th><th>狀態</th><th class="l">更新時間</th></tr>` +
      (rows || `<tr><td colspan="10" class="empty">暫時未有訂單</td></tr>`);
  }
}
async function refreshAccount() {
  if (!state.user) return;
  try {
    const [p, open] = await Promise.all([api(`${U()}/portfolio`), api(`${U()}/orders?status=PENDING`)]);
    state.portfolio = p; renderSummary(p); renderPositions(p); renderOpen(open); updateEstimate(); renderHistory();
  } catch (e) { toast(e.message); }
}

// ---------------------------------------------------------------- leaderboard
async function loadLeaderboard() {
  try {
    const lb = await api("/api/leaderboard");
    $("#lbNote").textContent = `以港元為基準貨幣計算：美元資產按 USD/HKD ${fmt(lb.fx.USDHKD, 4)} 折算（初始資金亦用同一匯率折算，所以匯率變動唔會影響回報率）。更新時間：${tHK(lb.as_of)} HKT`;
    const rows = lb.rows.map((r) => `<tr class="rank${r.rank} ${r.username === state.user ? "me" : ""}">
      <td class="l">${r.rank <= 3 ? ["🥇", "🥈", "🥉"][r.rank - 1] : r.rank}</td><td class="l">${esc(r.username)}${r.username === state.user ? "（你）" : ""}</td>
      <td class="${cls(r.return_pct)}"><b>${sign(r.return_pct)}${fmt(r.return_pct, 3)}%</b></td><td>HKD ${fmt(r.equity)}</td>
      <td class="${cls(r.pnl)}">${sign(r.pnl)}${fmt(r.pnl)}</td><td>${r.positions}</td><td>${r.trades}</td></tr>`).join("");
    $("#lbTable").innerHTML = `<tr><th class="l">排名</th><th class="l">用戶</th><th>總回報率</th><th>總資產（折合港元）</th><th>總盈虧 (HKD)</th><th>持倉數</th><th>成交次數</th></tr>` +
      (rows || `<tr><td colspan="7" class="empty">暫時未有用戶</td></tr>`);
  } catch (e) { toast(e.message); }
}

// ---------------------------------------------------------------- tabs / wiring
function showTab(name) {
  $$(".tab").forEach((t) => t.classList.toggle("active", t.dataset.tab === name));
  $("#tab-trade").classList.toggle("hidden", name !== "trade");
  $("#tab-leaderboard").classList.toggle("hidden", name !== "leaderboard");
  if (name === "leaderboard") loadLeaderboard(); else drawChart();
}
function route() { showTab(location.hash === "#leaderboard" || location.pathname === "/leaderboard" ? "leaderboard" : "trade"); }
function seg(id, key, after) {
  $(id).addEventListener("click", (e) => {
    const b = e.target.closest("button"); if (!b) return;
    $$(`${id} button`).forEach((x) => x.classList.toggle("on", x === b)); state[key] = b.dataset.v; after && after();
  });
}
function refreshAll() { refreshAccount(); loadSymbol(state.symbol); }

function init() {
  $("#quickChips").innerHTML = QUICK.map((s) => `<span class="chip" data-sym="${s}">${s}</span>`).join("");
  $("#ranges").innerHTML = RANGES.map(([k, l]) => `<button data-r="${k}" class="${k === state.range ? "on" : ""}">${l}</button>`).join("");
  $("#ranges").addEventListener("click", (e) => { const b = e.target.closest("button"); if (!b) return;
    state.range = b.dataset.r; $$("#ranges button").forEach((x) => x.classList.toggle("on", x === b)); loadChart(); });
  $("#searchForm").addEventListener("submit", (e) => { e.preventDefault(); const v = $("#symbolInput").value.trim(); if (v) loadSymbol(v); });
  document.body.addEventListener("click", async (e) => {
    const t = e.target;
    if (t.dataset.sym) { loadSymbol(t.dataset.sym); window.scrollTo({top: 0, behavior: "smooth"}); }
    if (t.dataset.sell) {
      await loadSymbol(t.dataset.sell); $("#sideSeg button[data-v=SELL]").click(); $("#oQty").value = t.dataset.qty; updateEstimate();
      window.scrollTo({top: 0, behavior: "smooth"});
    }
    if (t.dataset.cancel) {
      try { await api(`${U()}/orders/${t.dataset.cancel}/cancel`, {method: "POST"}); toast("已取消訂單"); refreshAccount(); }
      catch (err) { toast(err.message); }
    }
  });
  seg("#sideSeg", "side", updateEstimate);
  seg("#typeSeg", "type", () => { $("#limitRow").classList.toggle("hidden", state.type !== "LIMIT");
    if (state.type === "LIMIT" && state.quote) $("#oLimit").value = state.quote.price; updateEstimate(); });
  seg("#histSeg", "hist", renderHistory);
  ["#oQty", "#oLimit"].forEach((s) => $(s).addEventListener("input", updateEstimate));
  $("#qtyPlus").onclick = () => { $("#oQty").value = (Number($("#oQty").value) || 0) + lot(); updateEstimate(); };
  $("#qtyMinus").onclick = () => { $("#oQty").value = Math.max(lot(), (Number($("#oQty").value) || 0) - lot()); updateEstimate(); };
  $("#orderForm").addEventListener("submit", submitOrder);
  $("#logoutBtn").onclick = logout;
  $("#changePwBtn").onclick = () => openPw(true);
  $("#pwCancel").onclick = () => openPw(false);
  $("#pwForm").addEventListener("submit", changePw);
  $("#changeEmailBtn").onclick = () => openEmail(true);
  $("#emCancel").onclick = () => openEmail(false);
  $("#emailForm").addEventListener("submit", changeEmail);
  $("#resetBtn").onclick = async () => {
    if (!confirm("確定要重設帳戶？所有持倉、訂單同記錄會被清除，資金會還原至初始金額。")) return;
    try { await api(`${U()}/reset`, {method: "POST"}); toast("帳戶已重設"); refreshAccount(); } catch (e) { toast(e.message); }
  };
  $("#lbRefresh").onclick = loadLeaderboard;
  const cv = $("#chart");
  cv.addEventListener("mousemove", (e) => drawChart(e.offsetX));
  cv.addEventListener("mouseleave", () => drawChart());
  window.addEventListener("resize", () => drawChart());
  window.addEventListener("hashchange", route);
  route();
  api("/api/auth/me").then((me) => { applyMe(me); refreshAll(); });
  setInterval(() => { if (!state.user) return; refreshQuote(); refreshAccount();
    if (!$("#tab-leaderboard").classList.contains("hidden")) loadLeaderboard(); }, 15000);
}
init();
