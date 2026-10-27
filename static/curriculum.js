"use strict";
/* Curriculum / random-practice UI — uses /api/curriculum/* when available;
   falls back to static bank (sample N) + local scoring.
   Depends on app.js globals: $, $$, esc, api, toast, state, loadSymbol, refreshAccount */

const CURRICULUM = {
  weekId: "week1-fundamentals", // internal API id only; never shown as "Week 1"
  base: "/static/curriculum/week1",
  bankUrl: "/static/curriculum/mc_bank_fundamentals.json",
  lessonUrl: "/static/curriculum/lesson.md",
  lessonMd: null,
  bank: null,        // full question bank when static
  mc: null,          // active draw / API public shape
  answersKey: null,  // only from static bank (has answer/explain)
  pane: "lesson",
  lastSubmit: null,
  fromApi: false,
  displayTitle: "隨機練習",
};

function mdToHtml(md) {
  const lines = String(md || "").replace(/\r\n/g, "\n").split("\n");
  const out = [];
  let i = 0;
  let inUl = false, inOl = false;

  const closeLists = () => {
    if (inUl) { out.push("</ul>"); inUl = false; }
    if (inOl) { out.push("</ol>"); inOl = false; }
  };
  const inline = (s) => esc(s)
    .replace(/\*\*(.+?)\*\*/g, "<strong>$1</strong>")
    .replace(/`([^`]+)`/g, "<code>$1</code>");

  while (i < lines.length) {
    const line = lines[i];
    if (/^\|/.test(line) && i + 1 < lines.length && /^\|?\s*-/.test(lines[i + 1])) {
      closeLists();
      const rows = [];
      while (i < lines.length && /^\|/.test(lines[i])) {
        if (!/^\|?\s*-/.test(lines[i])) rows.push(lines[i]);
        i++;
      }
      if (rows.length) {
        const cells = (row) => row.replace(/^\|/, "").replace(/\|$/, "").split("|").map((c) => c.trim());
        const head = cells(rows[0]);
        out.push("<table><thead><tr>" + head.map((c) => `<th>${inline(c)}</th>`).join("") + "</tr></thead><tbody>");
        for (let r = 1; r < rows.length; r++) {
          out.push("<tr>" + cells(rows[r]).map((c) => `<td>${inline(c)}</td>`).join("") + "</tr>");
        }
        out.push("</tbody></table>");
      }
      continue;
    }
    if (/^###\s+/.test(line)) { closeLists(); out.push(`<h3>${inline(line.replace(/^###\s+/, ""))}</h3>`); i++; continue; }
    if (/^##\s+/.test(line)) { closeLists(); out.push(`<h2>${inline(line.replace(/^##\s+/, ""))}</h2>`); i++; continue; }
    if (/^#\s+/.test(line)) { closeLists(); out.push(`<h1>${inline(line.replace(/^#\s+/, ""))}</h1>`); i++; continue; }
    if (/^[-*]\s+/.test(line)) {
      if (inOl) { out.push("</ol>"); inOl = false; }
      if (!inUl) { out.push("<ul>"); inUl = true; }
      out.push(`<li>${inline(line.replace(/^[-*]\s+/, "").replace(/^\[[ xX]\]\s*/, ""))}</li>`);
      i++; continue;
    }
    if (/^\d+\.\s+/.test(line)) {
      if (inUl) { out.push("</ul>"); inUl = false; }
      if (!inOl) { out.push("<ol>"); inOl = true; }
      out.push(`<li>${inline(line.replace(/^\d+\.\s+/, ""))}</li>`);
      i++; continue;
    }
    if (/^\s*$/.test(line)) { closeLists(); i++; continue; }
    closeLists();
    out.push(`<p>${inline(line)}</p>`);
    i++;
  }
  closeLists();
  return out.join("\n");
}

function shuffleInPlace(arr) {
  for (let i = arr.length - 1; i > 0; i--) {
    const j = Math.floor(Math.random() * (i + 1));
    const t = arr[i];
    arr[i] = arr[j];
    arr[j] = t;
  }
  return arr;
}

function shuffleCopy(arr) {
  return shuffleInPlace(arr.slice());
}

function sampleQuestions(bankQs, n) {
  const pool = shuffleCopy(bankQs || []);
  const count = Math.min(Math.max(1, n || 7), pool.length || 0);
  return pool.slice(0, count);
}

function applyDrawFromBank() {
  const bank = CURRICULUM.bank;
  if (!bank) return;
  const drawN = bank.drawCount || 7;
  const qs = sampleQuestions(bank.questions || [], drawN);
  CURRICULUM.mc = {
    weekId: CURRICULUM.weekId, // keep internal compliance key
    title: bank.title || "基本面選股入門",
    passScore: bank.passScore || 5,
    total: qs.length,
    drawCount: drawN,
    universe: bank.universe || [],
    compliance: bank.compliance,
    questions: qs,
    mode: "random",
    userStatus: (CURRICULUM.mc && CURRICULUM.mc.userStatus) || {},
  };
  CURRICULUM.answersKey = Object.fromEntries(
    (bank.questions || []).map((q) => [q.id, { answer: q.answer, explain: q.explain }])
  );
}

function reshuffleActiveQuestions() {
  if (CURRICULUM.bank && !CURRICULUM.fromApi) {
    applyDrawFromBank();
    return;
  }
  if (CURRICULUM.mc && Array.isArray(CURRICULUM.mc.questions)) {
    CURRICULUM.mc.questions = shuffleCopy(CURRICULUM.mc.questions);
  }
}

function attemptKey() {
  const user = (state && state.user) || "anon";
  return `simCurriculumAttempt:${user}:${CURRICULUM.weekId}`;
}

function loadLocalAttempt() {
  try {
    const raw = localStorage.getItem(attemptKey());
    return raw ? JSON.parse(raw) : null;
  } catch { return null; }
}

function saveLocalAttempt(data) {
  try { localStorage.setItem(attemptKey(), JSON.stringify(data)); } catch {}
}

async function loadStaticBundle() {
  let lessonMd = "";
  let bank = null;

  const lessonTries = [CURRICULUM.lessonUrl, `${CURRICULUM.base}/lesson.md`];
  for (const url of lessonTries) {
    try {
      const mdRes = await fetch(url);
      if (mdRes.ok) { lessonMd = await mdRes.text(); break; }
    } catch {}
  }

  const bankTries = [
    CURRICULUM.bankUrl,
    "/static/curriculum/fundamentals/mc_bank.json",
  ];
  for (const url of bankTries) {
    try {
      const bankRes = await fetch(url);
      if (bankRes.ok) { bank = await bankRes.json(); break; }
    } catch {}
  }

  if (!bank) {
    const mcRes = await fetch(`${CURRICULUM.base}/mc.json`);
    if (!mcRes.ok) throw new Error("無法載入本地教材／題庫");
    const mc = await mcRes.json();
    bank = {
      bankId: mc.weekId || CURRICULUM.weekId,
      title: mc.title,
      drawCount: mc.total || (mc.questions || []).length || 7,
      passScore: mc.passScore || 5,
      universe: mc.universe || [],
      compliance: mc.compliance,
      questions: mc.questions || [],
    };
  }

  if (!lessonMd) throw new Error("無法載入本地教材");

  CURRICULUM.lessonMd = lessonMd;
  CURRICULUM.bank = bank;
  CURRICULUM.fromApi = false;
  applyDrawFromBank();
}

async function fetchCurriculum() {
  // Prefer live API (strips answers); fall back to static bank for offline / pre-deploy.
  try {
    const data = await api("/api/curriculum/week/current");
    CURRICULUM.fromApi = true;
    CURRICULUM.weekId = data.weekId || CURRICULUM.weekId;
    CURRICULUM.lessonMd = data.lesson || "";
    const qs = shuffleCopy(data.questions || []);
    CURRICULUM.mc = {
      weekId: data.weekId,
      title: data.title,
      passScore: data.passScore,
      total: data.total != null ? data.total : qs.length,
      universe: data.universe || [],
      compliance: data.compliance,
      questions: qs,
      userStatus: data.userStatus || {},
    };
    CURRICULUM.answersKey = null;
    CURRICULUM.bank = null;
    if (!CURRICULUM.lessonMd) {
      for (const url of [CURRICULUM.lessonUrl, `${CURRICULUM.base}/lesson.md`]) {
        try {
          const mdRes = await fetch(url);
          if (mdRes.ok) { CURRICULUM.lessonMd = await mdRes.text(); break; }
        } catch {}
      }
    }
    return;
  } catch (e) {
    /* API missing or error → static */
  }
  await loadStaticBundle();
}

function renderUniverseChips(matched) {
  const uni = (CURRICULUM.mc && CURRICULUM.mc.universe) || [];
  const held = new Set(
    (matched && matched.length)
      ? matched.map((s) => String(s).toUpperCase())
      : ((state.portfolio && state.portfolio.positions) || []).map((p) => String(p.symbol).toUpperCase())
  );
  $("#learnUniverseChips").innerHTML = uni.map((s) => {
    const on = held.has(String(s).toUpperCase());
    return `<span class="chip ${on ? "held" : "in-pool"}" data-learn-sym="${esc(s)}" title="${on ? "你持有中" : "撳去交易"}">${esc(s)}${on ? " ✓" : ""}</span>`;
  }).join("") || `<span class="muted">未有標的池</span>`;
}

function showLearnPane(name) {
  CURRICULUM.pane = name;
  $$("#learnSubtabs button").forEach((b) => b.classList.toggle("on", b.dataset.learn === name));
  $("#learnLesson").classList.toggle("hidden", name !== "lesson");
  $("#learnMc").classList.toggle("hidden", name !== "mc");
  $("#learnStatus").classList.toggle("hidden", name !== "status");
  if (name === "status") renderCompliancePanel();
}

function renderLesson() {
  $("#learnTitle").textContent = CURRICULUM.displayTitle;
  $("#learnWeekBadge").textContent = (CURRICULUM.mc && CURRICULUM.mc.title) || "基本面選股入門";
  $("#learnLesson").innerHTML = mdToHtml(CURRICULUM.lessonMd);
  renderUniverseChips();
}

function currentAttemptView() {
  if (CURRICULUM.lastSubmit) return CURRICULUM.lastSubmit;
  const local = loadLocalAttempt();
  if (local) return local;
  const us = CURRICULUM.mc && CURRICULUM.mc.userStatus;
  if (us && us.submitted) {
    return { score: us.mcScore, passed: !!us.mcPassed, total: CURRICULUM.mc.total, source: "server-status" };
  }
  return null;
}

function renderMcForm() {
  const mc = CURRICULUM.mc;
  const prev = currentAttemptView();
  const hasDetails = !!(prev && prev.details && prev.details.length);
  const locked = hasDetails;
  let html = "";

  if (prev && prev.score != null) {
    const pass = !!prev.passed;
    html += `<div class="mc-result ${pass ? "pass" : "fail"}">
      <b>${pass ? "及格" : "未及格"}</b>　得分 ${prev.score} / ${mc.total || prev.total}（及格線 ≥${mc.passScore || 5}）
      ${prev.at ? `<div class="muted" style="margin-top:4px">提交：${esc(prev.at)}</div>` : ""}
      <div class="muted" style="margin-top:4px">${CURRICULUM.fromApi
        ? "已交伺服器計分"
        : `本地隨機練習（題庫抽 ${mc.total || 7} 題）`}</div>
      <div style="margin-top:8px"><button type="button" class="btn ghost small" id="mcRetryBtn">再答一次</button></div>
    </div>`;
  }

  html += `<form id="mcForm">`;
  (mc.questions || []).forEach((q, idx) => {
    const detail = hasDetails ? (prev.details.find((d) => d.id === q.id) || {}) : null;
    const picked = prev && prev.answers ? prev.answers[q.id] : null;
    let qCls = "mc-q";
    if (detail) qCls += detail.correct ? " correct" : " wrong";
    html += `<div class="${qCls}" data-qid="${esc(q.id)}"><h4>${idx + 1}. ${esc(q.stem)}</h4>`;
    (q.choices || []).forEach((c) => {
      const checked = picked === c.key ? "checked" : "";
      const dis = locked ? "disabled" : "";
      html += `<label class="mc-choice"><input type="radio" name="${esc(q.id)}" value="${esc(c.key)}" ${checked} ${dis}>
        <span><b>${esc(c.key)}.</b> ${esc(c.text)}</span></label>`;
    });
    if (detail && (detail.answer || detail.explain)) {
      html += `<div class="mc-explain"><b>正確：${esc(detail.answer || "")}</b>　${esc(detail.explain || "")}</div>`;
    }
    html += `</div>`;
  });

  if (!locked) {
    html += `<button class="btn primary" type="submit">提交答卷</button>
      <p class="muted small-text" style="margin-top:8px">${CURRICULUM.fromApi
        ? "交卷會寫入伺服器（可重交；排行榜取最佳分）。每次進入會打亂題序。"
        : "後端未上線時喺本機計分；每次「再答一次」會重新抽題。成績存 localStorage。"}</p>`;
  }
  html += `</form>`;
  $("#learnMc").innerHTML = html;

  const form = $("#mcForm");
  if (form && !locked) {
    form.addEventListener("submit", onMcSubmit);
  }
  const retry = $("#mcRetryBtn");
  if (retry) {
    retry.onclick = async () => {
      CURRICULUM.lastSubmit = null;
      try { localStorage.removeItem(attemptKey()); } catch {}
      // API: re-GET for a fresh server-side draw; static: re-sample from bank
      if (CURRICULUM.fromApi) {
        try {
          await fetchCurriculum();
          renderLesson();
        } catch (err) {
          toast(err.message || "無法重新抽題");
          reshuffleActiveQuestions();
        }
      } else {
        reshuffleActiveQuestions();
      }
      renderMcForm();
      updateSideSummary();
    };
  }
}

async function onMcSubmit(e) {
  e.preventDefault();
  const form = e.target;
  const mc = CURRICULUM.mc;
  const answers = {};
  let missing = 0;
  (mc.questions || []).forEach((q) => {
    const el = form.querySelector(`input[name="${q.id}"]:checked`);
    if (!el) missing++;
    else answers[q.id] = el.value;
  });
  if (missing) { toast(`仲有 ${missing} 題未答`); return; }

  let payload;
  if (CURRICULUM.fromApi) {
    try {
      const res = await api(`/api/curriculum/week/${encodeURIComponent(CURRICULUM.weekId)}/submit`, {
        method: "POST",
        body: { answers },
      });
      payload = {
        weekId: res.weekId || CURRICULUM.weekId,
        score: res.score,
        passed: res.passed,
        total: res.total,
        passScore: res.passScore,
        details: res.details || [],
        answers,
        at: res.submittedAtIso || new Date().toLocaleString("zh-HK", { timeZone: "Asia/Hong_Kong" }),
        source: "api",
      };
    } catch (err) {
      toast(err.message);
      return;
    }
  } else {
    let score = 0;
    const details = [];
    (mc.questions || []).forEach((q) => {
      const ok = answers[q.id] === q.answer;
      if (ok) score++;
      details.push({ id: q.id, correct: ok, answer: q.answer, explain: q.explain });
    });
    payload = {
      weekId: mc.weekId,
      score,
      passed: score >= (mc.passScore || 5),
      total: mc.total || (mc.questions || []).length,
      passScore: mc.passScore,
      details,
      answers,
      at: new Date().toLocaleString("zh-HK", { timeZone: "Asia/Hong_Kong" }),
      source: "local",
    };
  }

  CURRICULUM.lastSubmit = payload;
  saveLocalAttempt(payload);
  if (CURRICULUM.mc.userStatus) {
    CURRICULUM.mc.userStatus.submitted = true;
    CURRICULUM.mc.userStatus.mcScore = payload.score;
    CURRICULUM.mc.userStatus.mcPassed = payload.passed;
  }
  toast(payload.passed ? `及格！${payload.score}/${payload.total}` : `未及格：${payload.score}/${payload.total}`);
  renderMcForm();
  updateSideSummary();
}

async function fetchCompliance() {
  try {
    return await api("/api/portfolio/compliance");
  } catch {
    return null;
  }
}

function clientCompliance() {
  const uni = new Set(((CURRICULUM.mc && CURRICULUM.mc.universe) || []).map((s) => String(s).toUpperCase()));
  const positions = (state.portfolio && state.portfolio.positions) || [];
  const matched = positions
    .filter((p) => uni.has(String(p.symbol).toUpperCase()) && Number(p.qty) > 0)
    .map((p) => String(p.symbol).toUpperCase());
  const attempt = currentAttemptView();
  return {
    source: "client",
    ok: matched.length >= 1,
    matchedTickers: matched,
    heldDays: null,
    holdDaysRequired: 7,
    mcPassed: !!(attempt && attempt.passed),
    mcScore: attempt ? attempt.score : null,
    canBoost: false,
    boosted: false,
    note: "後端合規 API 稍後接駁／未部署；已持天數暫時未知。",
  };
}

async function renderCompliancePanel() {
  const box = $("#learnStatus");
  const mc = CURRICULUM.mc;
  box.innerHTML = `<p class="muted">載入合規狀態…</p>`;

  let comp = await fetchCompliance();
  const apiMissing = !comp;
  if (!comp) comp = clientCompliance();

  const attempt = currentAttemptView();
  const mcPass = comp.mcPassed != null ? !!comp.mcPassed : !!(attempt && attempt.passed);
  const mcScore = comp.mcScore != null ? comp.mcScore : (attempt && attempt.score);
  const heldOk = !!comp.ok && (comp.matchedTickers || []).length > 0;
  const days = comp.heldDays;
  const need = comp.holdDaysRequired || 7;
  const daysOk = days != null && days >= need;
  const daysLabel = days == null
    ? `<span class="comp-wait">後端未提供持倉天數</span>`
    : `<span class="${daysOk ? "comp-ok" : "comp-no"}">${Number(days).toFixed(1)} / ${need} 日</span>`;

  const canBoost = !!comp.canBoost;
  const boosted = !!comp.boosted;
  const matched = (comp.matchedTickers || []).join(", ") || "—";

  box.innerHTML = `
    <div class="panel" style="margin:0;background:#0b0f14">
      <h3 style="margin-top:0">合規檢查（P1–P3）</h3>
      ${apiMissing ? `<p class="muted small-text">後端合規 API 未回應；顯示持倉 ∩ 標的池粗略狀態。</p>` : ""}
      <div class="comp-row"><span>標的池</span><span>${esc((mc.universe || comp.universe || []).join(" · "))}</span></div>
      <div class="comp-row"><span>P3 小測及格（≥${mc.passScore || 5}/${mc.total || 7}）</span>
        <span class="${mcPass ? "comp-ok" : "comp-no"}">${mcPass ? `已及格${mcScore != null ? `（${mcScore}）` : ""}` : (mcScore != null ? `未及格（${mcScore}）` : "未提交")}</span></div>
      <div class="comp-row"><span>P1 持倉 ∩ 池</span>
        <span class="${heldOk ? "comp-ok" : "comp-no"}">${heldOk ? `有：${esc(matched)}` : "未持有池內股票"}</span></div>
      <div class="comp-row"><span>P2 已持天數</span>${daysLabel}</div>
      <div class="comp-row"><span>加成狀態</span>
        <span class="${boosted ? "comp-ok" : "comp-wait"}">${boosted ? "已領取" : (canBoost ? "可以領取" : "未達標")}</span></div>
      <div style="margin-top:14px">
        <button type="button" class="btn primary" id="boostBtn">使用 1% 收益加成</button>
        <p class="muted small-text" id="boostHint" style="margin-top:8px"></p>
      </div>
    </div>`;

  const hint = $("#boostHint");
  const btn = $("#boostBtn");
  if (boosted) {
    btn.disabled = true;
    hint.textContent = "已經用過加成。";
  } else if (canBoost) {
    btn.disabled = false;
    hint.textContent = "達標：會按總權益 1% 一次過撥入 USD 現金。";
    btn.onclick = applyBoost;
  } else {
    btn.disabled = true;
    const bits = [];
    if (!mcPass) bits.push("先完成小測及格");
    if (!heldOk) bits.push("買入並持有標的池內至少 1 隻");
    if (days == null && !apiMissing) bits.push("等候持倉日數累積");
    else if (days == null) bits.push("部署後端合規／加成 API");
    else if (!daysOk) bits.push(`仲要持有約 ${(need - days).toFixed(1)} 日`);
    hint.textContent = "加成未開放：" + bits.join("；") + "。";
  }

  updateSideSummary(comp, attempt);
  renderUniverseChips(comp.matchedTickers);
}

async function applyBoost() {
  const btn = $("#boostBtn");
  if (btn) btn.disabled = true;
  try {
    const res = await api("/api/boost/apply", { method: "POST" });
    toast(`加成成功：+USD ${Number(res.amount).toLocaleString("en-US", { maximumFractionDigits: 2 })}`);
    if (typeof refreshAccount === "function") await refreshAccount();
    await renderCompliancePanel();
  } catch (e) {
    toast(e.message);
    await renderCompliancePanel();
  }
}

function updateSideSummary(comp, attempt) {
  attempt = attempt || currentAttemptView();
  const el = $("#learnSideSummary");
  if (!el) return;
  const mcPass = comp && comp.mcPassed != null ? !!comp.mcPassed : !!(attempt && attempt.passed);
  const score = comp && comp.mcScore != null ? comp.mcScore : (attempt && attempt.score);
  const held = ((comp && comp.matchedTickers) || []).join(", ") || "無";
  const days = comp && comp.heldDays != null ? `${Number(comp.heldDays).toFixed(1)} 日` : "—";
  el.innerHTML = `
    <div><b>小測</b>：${mcPass ? `<span class="comp-ok">及格${score != null ? ` ${score}` : ""}</span>` : `<span class="comp-no">${score != null ? "未及格" : "未提交"}</span>`}</div>
    <div><b>池內持倉</b>：${esc(held)}</div>
    <div><b>已持天數</b>：${esc(days)}</div>
    <div class="muted" style="margin-top:6px">加成 = 小測及格 + 池內持股滿 7 日</div>`;
}

async function loadLearnTab() {
  try {
    if (typeof refreshAccount === "function" && state.user) {
      try { await refreshAccount(); } catch {}
    }
    await fetchCurriculum();
    if (!CURRICULUM.lastSubmit) {
      const local = loadLocalAttempt();
      if (local && local.details) CURRICULUM.lastSubmit = local;
    }
    renderLesson();
    renderMcForm();
    showLearnPane(CURRICULUM.pane || "lesson");
    const comp = (await fetchCompliance()) || clientCompliance();
    updateSideSummary(comp, currentAttemptView());
    if (CURRICULUM.pane === "status") renderCompliancePanel();
  } catch (e) {
    $("#learnLesson").innerHTML = `<p class="msg err">載入失敗：${esc(e.message)}</p>`;
    toast(e.message);
  }
}

function wireCurriculum() {
  const sub = $("#learnSubtabs");
  if (sub) {
    sub.addEventListener("click", (e) => {
      const b = e.target.closest("button[data-learn]");
      if (!b) return;
      showLearnPane(b.dataset.learn);
    });
  }
  document.body.addEventListener("click", (e) => {
    const chip = e.target.closest("[data-learn-sym]");
    if (!chip) return;
    const sym = chip.getAttribute("data-learn-sym");
    if (!sym) return;
    location.hash = "#trade";
    if (typeof loadSymbol === "function") loadSymbol(sym);
    window.scrollTo({ top: 0, behavior: "smooth" });
  });
}

wireCurriculum();
if (location.hash === "#learn" || location.pathname === "/learn") {
  loadLearnTab();
}
