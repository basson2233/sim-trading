/* 理財戰士 — Smash-style canvas fighter (no HP, % knockback, blast zones) */
(() => {
  const $ = (s) => document.querySelector(s);
  const toast = (msg) => {
    const t = $("#toast");
    t.textContent = msg;
    t.classList.remove("hidden");
    clearTimeout(t._t);
    t._t = setTimeout(() => t.classList.add("hidden"), 2800);
  };

  async function api(path, opts = {}) {
    const r = await fetch(path, {
      credentials: "same-origin",
      headers: { "Content-Type": "application/json", ...(opts.headers || {}) },
      ...opts,
    });
    if (r.status === 401) {
      location.href = "/login";
      throw new Error("請先登入");
    }
    const data = await r.json().catch(() => ({}));
    if (!r.ok) throw new Error(data.detail || r.statusText || "錯誤");
    return data;
  }

  function statBars(el, s) {
    el.innerHTML = ["atk", "def", "spd"]
      .map((k) => {
        const label = { atk: "攻擊", def: "防禦", spd: "速度" }[k];
        const v = s[k] ?? 100;
        const pct = Math.max(0, Math.min(100, Math.round(((v - 100) / 50) * 100)));
        return `<div class="stat-row">
          <span class="label ${k}">${label}</span>
          <div class="bar-track"><div class="bar-fill ${k}" style="width:${pct}%"></div></div>
          <span class="stat-val">${v}</span>
        </div>`;
      })
      .join("");
  }

  function breakdownHtml(s) {
    const rows = (s.breakdown || []).slice(0, 12);
    if (!rows.length) {
      return `<p class="muted">暫無持倉——屬性為基礎 100。買入成長股↑攻擊、銀行／公用↑防禦、ETF／高流動↑速度（每市值 USD 1 萬加 1 點）。</p>`;
    }
    const aff = { atk: "攻擊", def: "防禦", spd: "速度" };
    return `<table><thead><tr><th class="l">代號</th><th>主屬性</th><th>市值 (USD)</th><th>加點</th></tr></thead><tbody>${rows
      .map(
        (r) => {
          const pts = r.points || r.contrib || {};
          const add = Object.values(pts).reduce((a, b) => a + Number(b || 0), 0);
          const mv = r.market_value_usd ?? r.market_value_base ?? 0;
          return `<tr><td class="l">${r.symbol}</td><td>${aff[r.affinity] || r.affinity}</td><td>${Number(mv).toLocaleString()}</td><td>+${add.toFixed(1)}</td></tr>`;
        }
      )
      .join("")}</tbody></table>`;
  }

  // -------------------- Maps (高低差 + 移動第二層) --------------------
  const MAPS = {
    hkex: {
      id: "hkex",
      name: "港交所擂台",
      ticker: "AAPL  ▲   NVDA  ▲   JPM  ▼   SPY  ■",
      bg: { top: "#0b1a33", bottom: "#132844", accent: "#16c784", stars: true, theme: "hkex" },
      blast: { left: -80, right: 1040, top: -120, bottom: 640 },
      spawn: { p1x: 260, p2x: 660, groundY: 430 },
      platforms: [
        { id: "main", x: 100, y: 430, w: 760, h: 28, kind: "main", color: "#334155", accent: "#16c784" },
        { id: "left", x: 160, y: 300, w: 150, h: 16, kind: "static", color: "#475569", accent: "#38bdf8" },
        { id: "right", x: 650, y: 300, w: 150, h: 16, kind: "static", color: "#475569", accent: "#38bdf8" },
        {
          id: "mover",
          x: 380,
          y: 220,
          w: 180,
          h: 16,
          kind: "moving",
          axis: "x",
          min: 220,
          max: 560,
          speed: 1.35,
          color: "#64748b",
          accent: "#fbbf24",
        },
      ],
    },
    wallstreet: {
      id: "wallstreet",
      name: "華爾街夜景",
      ticker: "AAPL  ▲   JPM  ■   SPY  ▲   DJI  ▼",
      bg: { top: "#050814", bottom: "#1a1040", accent: "#a78bfa", stars: true, theme: "wallstreet" },
      blast: { left: -100, right: 1060, top: -140, bottom: 660 },
      spawn: { p1x: 220, p2x: 700, groundY: 450 },
      platforms: [
        { id: "mainL", x: 40, y: 450, w: 320, h: 26, kind: "main", color: "#1e293b", accent: "#f59e0b" },
        { id: "mainR", x: 600, y: 450, w: 320, h: 26, kind: "main", color: "#1e293b", accent: "#f59e0b" },
        { id: "ledgeL", x: 80, y: 320, w: 140, h: 14, kind: "static", color: "#334155", accent: "#c4b5fd" },
        { id: "ledgeR", x: 740, y: 320, w: 140, h: 14, kind: "static", color: "#334155", accent: "#c4b5fd" },
        { id: "midHigh", x: 380, y: 260, w: 200, h: 14, kind: "static", color: "#312e81", accent: "#818cf8" },
        {
          id: "mover",
          x: 300,
          y: 360,
          w: 200,
          h: 16,
          kind: "moving",
          axis: "x",
          min: 200,
          max: 560,
          speed: 1.6,
          color: "#4c1d95",
          accent: "#a78bfa",
        },
      ],
    },
    vault: {
      id: "vault",
      name: "銀行金庫",
      ticker: "VAULT  ■   GOLD  ▲   CASH  ■   SAFE  ▼",
      bg: { top: "#1c1917", bottom: "#44403c", accent: "#d97706", stars: false, theme: "vault" },
      blast: { left: -60, right: 1020, top: -100, bottom: 620 },
      spawn: { p1x: 300, p2x: 620, groundY: 440 },
      platforms: [
        { id: "main", x: 220, y: 440, w: 520, h: 30, kind: "main", color: "#44403c", accent: "#d97706" },
        { id: "lowL", x: 80, y: 360, w: 130, h: 16, kind: "static", color: "#57534e", accent: "#fbbf24" },
        { id: "lowR", x: 750, y: 360, w: 130, h: 16, kind: "static", color: "#57534e", accent: "#fbbf24" },
        { id: "high", x: 380, y: 180, w: 200, h: 14, kind: "static", color: "#78716c", accent: "#fcd34d" },
        {
          id: "mover",
          x: 390,
          y: 280,
          w: 180,
          h: 16,
          kind: "moving",
          axis: "y",
          min: 200,
          max: 340,
          speed: 1.1,
          color: "#a16207",
          accent: "#fde68a",
        },
      ],
    },
  };

  let myStats = null;
  let matchCtx = null; // {mode, player, opponent, difficulty?, mapId}
  let selectedMapId = "hkex";

  function currentMap() {
    return MAPS[selectedMapId] || MAPS.hkex;
  }

  function bindMapPicker() {
    const box = $("#mapPicker");
    if (!box || box._bound) return;
    box._bound = true;
    box.querySelectorAll(".map-option").forEach((btn) => {
      btn.addEventListener("click", () => {
        selectedMapId = btn.dataset.map || "hkex";
        box.querySelectorAll(".map-option").forEach((b) => {
          const on = b.dataset.map === selectedMapId;
          b.classList.toggle("selected", on);
          b.setAttribute("aria-checked", on ? "true" : "false");
        });
      });
    });
  }

  async function loadLobby() {
    const me = await api("/api/auth/me");
    $("#userName").textContent = me.username;
    myStats = await api("/api/fighter/stats");
    $("#tipBanner").textContent = myStats.tip || $("#tipBanner").textContent;
    statBars($("#myStats"), myStats);
    $("#myBreakdown").innerHTML = breakdownHtml(myStats);
    try {
      const h = await api("/api/fighter/history");
      const tb = $("#histTable tbody");
      const rows = h.rows || [];
      if (!rows.length) {
        tb.innerHTML = `<tr><td class="empty" colspan="5">未有對戰記錄</td></tr>`;
      } else {
        tb.innerHTML = rows
          .map((r) => {
            const win =
              r.winner === "player"
                ? '<span class="up">勝</span>'
                : r.winner === "opponent"
                  ? '<span class="down">負</span>'
                  : "和";
            const opp =
              r.player_username.toLowerCase() === me.username.toLowerCase()
                ? r.opponent_username
                : r.player_username;
            const score =
              r.player_username.toLowerCase() === me.username.toLowerCase()
                ? `${r.player_kos}–${r.opponent_kos}`
                : `${r.opponent_kos}–${r.player_kos}`;
            return `<tr><td class="l">${r.created_at_iso || ""}</td><td>${r.mode === "ai" ? "AI" : "同學"}</td><td class="l">${opp}</td><td>${win}</td><td>${score}</td></tr>`;
          })
          .join("");
      }
    } catch (_) {
      /* ignore */
    }
  }

  $("#logoutBtn").onclick = async () => {
    await api("/api/auth/logout", { method: "POST" });
    location.href = "/login";
  };

  const ASSET_VER = "20261015d";
  const CHARACTERS = [
    {
      id: "herta",
      name: "大黑塔",
      tag: "法師・預設",
      portrait: `/static/fighter/sprites/portrait.png?v=${ASSET_VER}`,
    },
  ];
  let selectedCharId = "herta";
  let selectTimer = null;
  let selectLeft = 30;
  let pendingMatchCtx = null;

  function clearSelectTimer() {
    if (selectTimer) {
      clearInterval(selectTimer);
      selectTimer = null;
    }
  }

  function renderCharGrid() {
    const grid = $("#charSelectGrid");
    if (!grid) return;
    grid.innerHTML = CHARACTERS.map((c) => {
      const on = c.id === selectedCharId ? "selected" : "";
      return `<button type="button" class="char-card ${on}" data-char="${c.id}" role="radio" aria-checked="${c.id === selectedCharId}">
        <img src="${c.portrait}" alt="${c.name}" width="120" height="180" draggable="false">
        <div class="char-name">${c.name}</div>
        <div class="char-tag">${c.tag}</div>
      </button>`;
    }).join("");
    grid.querySelectorAll(".char-card").forEach((btn) => {
      btn.onclick = () => {
        selectedCharId = btn.dataset.char || "herta";
        renderCharGrid();
      };
    });
  }

  async function beginFight(ctx) {
    clearSelectTimer();
    const ov = $("#charSelect");
    if (ov) ov.classList.add("hidden");
    ctx.characterId = selectedCharId;
    try {
      const ok = await Game.ensureSprites();
      if (!ok) toast("角色圖片載入未完成，已用備用顯示；請強制重新整理再試");
    } catch (_) {}
    Game.start(ctx);
    Game.refreshVirtPad();
  }

  function openCharSelect(ctx) {
    pendingMatchCtx = ctx;
    matchCtx = ctx;
    selectedMapId = ctx.mapId || selectedMapId || "hkex";
    ctx.mapId = selectedMapId;
    $("#lobby").classList.add("hidden");
    $("#arena").classList.remove("hidden");
    $("#resultOverlay").classList.add("hidden");
    const cs = $("#charSelect");
    if (cs) cs.classList.remove("hidden");
    $("#p1Name").textContent = ctx.player.display_name || ctx.player.username;
    $("#p2Name").textContent = ctx.opponent.display_name || ctx.opponent.username;
    $("#p1Mini").textContent = `攻${ctx.player.atk} 防${ctx.player.def} 速${ctx.player.spd}`;
    $("#p2Mini").textContent = `攻${ctx.opponent.atk} 防${ctx.opponent.def} 速${ctx.opponent.spd}`;
    const map = MAPS[selectedMapId] || MAPS.hkex;
    const label = $("#mapLabel");
    if (label) label.textContent = map.name;
    $("#roundMsg").textContent = "選擇角色…";
    Game.stop();
    Game.refreshVirtPad();
    renderCharGrid();
    selectLeft = 30;
    const secEl = $("#charSelectSec");
    if (secEl) secEl.textContent = String(selectLeft);
    clearSelectTimer();
    selectTimer = setInterval(() => {
      selectLeft -= 1;
      if (secEl) secEl.textContent = String(Math.max(0, selectLeft));
      if (selectLeft <= 0) {
        clearSelectTimer();
        beginFight(pendingMatchCtx || ctx);
      }
    }, 1000);
    // Warm sprites during select
    Game.ensureSprites();
  }

  function showArena(ctx) {
    openCharSelect(ctx);
  }

  const btnConfirmChar = $("#btnConfirmChar");
  if (btnConfirmChar) {
    btnConfirmChar.onclick = () => {
      if (!pendingMatchCtx && !matchCtx) return;
      beginFight(pendingMatchCtx || matchCtx);
    };
  }

  function showLobby() {
    clearSelectTimer();
    pendingMatchCtx = null;
    const cs = $("#charSelect");
    if (cs) cs.classList.add("hidden");
    Game.stop();
    $("#arena").classList.add("hidden");
    $("#lobby").classList.remove("hidden");
    Game.refreshVirtPad();
    loadLobby().catch((e) => toast(e.message));
  }

  $("#btnBack").onclick = showLobby;
  $("#btnToLobby").onclick = showLobby;

  $("#btnAI").onclick = async () => {
    try {
      const diff = $("#aiDiff").value;
      const opp = await api(`/api/fighter/ai?difficulty=${encodeURIComponent(diff)}&mirror=1`);
      showArena({ mode: "ai", player: myStats, opponent: opp, difficulty: diff, mapId: selectedMapId });
    } catch (e) {
      toast(e.message);
    }
  };

  $("#btnClassmate").onclick = async () => {
    const msg = $("#matchMsg");
    msg.textContent = "";
    msg.className = "msg";
    const name = $("#oppName").value.trim();
    if (!name) {
      msg.textContent = "請輸入同學用戶名";
      msg.classList.add("err");
      return;
    }
    try {
      const data = await api("/api/fighter/match", {
        method: "POST",
        body: JSON.stringify({ opponent_username: name }),
      });
      myStats = data.player;
      showArena({
        mode: "classmate",
        player: data.player,
        opponent: data.opponent,
        mapId: selectedMapId,
      });
    } catch (e) {
      msg.textContent = e.message;
      msg.classList.add("err");
    }
  };

  $("#btnRematch").onclick = () => {
    if (!matchCtx) return;
    $("#resultOverlay").classList.add("hidden");
    matchCtx.mapId = selectedMapId || matchCtx.mapId;
    if (matchCtx.mode === "ai") {
      api(`/api/fighter/ai?difficulty=${encodeURIComponent(matchCtx.difficulty || "normal")}&mirror=1`)
        .then((opp) => {
          matchCtx.opponent = opp;
          showArena(matchCtx);
        })
        .catch((e) => toast(e.message));
    } else {
      api("/api/fighter/match", {
        method: "POST",
        body: JSON.stringify({ opponent_username: matchCtx.opponent.username }),
      })
        .then((data) => {
          matchCtx.player = data.player;
          matchCtx.opponent = data.opponent;
          showArena(matchCtx);
        })
        .catch((e) => toast(e.message));
    }
  };

  // -------------------- Game engine --------------------
  const Game = (() => {
    const canvas = $("#game");
    const ctx = canvas.getContext("2d");
    const W = 960,
      H = 540;

    // 大黑塔 action sprites (facing right in source art). Cache-bust so browsers don't keep old JS-era 404s.
    const ASSET_VER = "20261015d";
    const SPRITE_KEYS = ["idle", "walk", "attack", "heavy", "jump", "hurt"];
    const WALK_FRAMES = 6;
    const WALK_FRAME_TICKS = 7; // ~8.5 fps at fixed 60Hz sim
    const SIM_HZ = 60;
    const SIM_DT = 1 / SIM_HZ;
    const MAX_FRAME_DT = 0.05; // 50ms cap — avoid spiral after tab switch
    const sprites = { p1: {}, p2: {} };
    let spritesReady = false;
    let spritesFailed = 0;
    let spritesPromise = null;

    function spriteUrl(file) {
      return `/static/fighter/sprites/${file}?v=${ASSET_VER}`;
    }

    function loadImage(url) {
      return new Promise((resolve) => {
        const tryLoad = (src, isRetry) => {
          const img = new Image();
          img.decoding = "async";
          img.onload = async () => {
            try {
              if (img.decode) await img.decode();
            } catch (_) {}
            resolve(img);
          };
          img.onerror = () => {
            if (!isRetry) {
              tryLoad(src + (src.includes("?") ? "&" : "?") + "r=" + Date.now(), true);
            } else {
              resolve(img); // naturalWidth stays 0
            }
          };
          img.src = src;
        };
        tryLoad(url, false);
      });
    }

    function ensureSprites() {
      if (spritesReady) return Promise.resolve(true);
      if (spritesPromise) return spritesPromise;
      spritesPromise = (async () => {
        spritesFailed = 0;
        const jobs = [];
        for (const key of SPRITE_KEYS) {
          jobs.push(
            loadImage(spriteUrl(`${key}.png`)).then((img) => {
              sprites.p1[key] = img;
              if (!(img && img.naturalWidth > 0)) spritesFailed++;
            })
          );
          jobs.push(
            loadImage(spriteUrl(`${key}_ai.png`)).then((img) => {
              sprites.p2[key] = img;
              if (!(img && img.naturalWidth > 0)) spritesFailed++;
            })
          );
        }
        await Promise.all(jobs);
        spritesReady = SPRITE_KEYS.every(
          (k) => sprites.p1[k] && sprites.p1[k].naturalWidth > 0 && sprites.p2[k] && sprites.p2[k].naturalWidth > 0
        );
        window.__FIGHTER_SPRITES__ = { ready: spritesReady, failed: spritesFailed, sprites };
        return spritesReady;
      })();
      return spritesPromise;
    }
    // Kick off preload immediately
    ensureSprites();

    function pickSpriteKey(f) {
      // 1 idle 2 walk 3 light attack 4 heavy 5 jump 6 hurt
      if (f.hitstun > 0) return "hurt";
      if (f.atkTimer > 0) return f.smash ? "heavy" : "attack";
      if (!f.onGround) return "jump";
      if (Math.abs(f.vx) > 0.35) return "walk";
      return "idle";
    }

    let running = false;
    let raf = 0;
    let keys = {};
    let p1, p2, stocks, roundLock, kosToWin;
    let matchMeta = null;
    let particles = [];
    let aiState = { cool: 0, jumpCool: 0 };
    let mapState = null; // live platforms + blast + spawn
    let tick = 0;
    let lastFrameTs = 0;
    let simAccum = 0;

    function cloneMap(mapId) {
      const src = MAPS[mapId] || MAPS.hkex;
      const platforms = src.platforms.map((p) => {
        const pl = { ...p, ox: p.x, oy: p.y, dir: 1, rider: null };
        if (p.kind === "moving") {
          pl.x = p.x;
          pl.y = p.y;
          pl.dir = 1;
        }
        return pl;
      });
      return {
        id: src.id,
        name: src.name,
        ticker: src.ticker,
        bg: { ...src.bg },
        blast: { ...src.blast },
        spawn: { ...src.spawn },
        platforms,
      };
    }

    function mainFloorY() {
      const mains = mapState.platforms.filter((p) => p.kind === "main");
      if (!mains.length) return mapState.spawn.groundY || 420;
      return Math.min(...mains.map((p) => p.y));
    }

    function fighter(stats, x, facing, color, isAI) {
      const atk = stats.atk || 50,
        def = stats.def || 50,
        spd = stats.spd || 50;
      const gy = mainFloorY();
      return {
        stats,
        x,
        y: gy - 48,
        vx: 0,
        vy: 0,
        w: 36,
        h: 48,
        facing,
        color,
        damage: 0,
        onGround: true,
        onPlat: null,
        jumps: 2,
        atkTimer: 0,
        atkCool: 0,
        hitstun: 0,
        invuln: 0,
        smash: false,
        isAI: !!isAI,
        moveSpd: (3.2 + (spd - 50) * 0.06) * 0.25,
        airSpd: (3.0 + (spd - 50) * 0.05) * 0.25,
        jumpV: -11.2 - (spd - 50) * 0.04,
        weight: 1 + (def - 50) * 0.008,
        knockDealt: 0.85 + (atk - 50) * 0.012,
        knockTaken: 1.15 - (def - 50) * 0.01,
      };
    }

    function resetRoundPositions() {
      const gy = mainFloorY();
      p1.x = mapState.spawn.p1x;
      p1.y = gy - p1.h;
      p1.vx = p1.vy = 0;
      p1.damage = 0;
      p1.facing = 1;
      p1.onGround = true;
      p1.onPlat = null;
      p1.jumps = 2;
      p1.hitstun = 0;
      p1.invuln = 45;
      p1.atkTimer = p1.atkCool = 0;
      p2.x = mapState.spawn.p2x;
      p2.y = gy - p2.h;
      p2.vx = p2.vy = 0;
      p2.damage = 0;
      p2.facing = -1;
      p2.onGround = true;
      p2.onPlat = null;
      p2.jumps = 2;
      p2.hitstun = 0;
      p2.invuln = 45;
      p2.atkTimer = p2.atkCool = 0;
      particles = [];
      updateHud();
    }

    function updateHud() {
      $("#p1Pct").textContent = Math.floor(p1.damage) + "%";
      $("#p2Pct").textContent = Math.floor(p2.damage) + "%";
      $("#p1Stocks").textContent = "●".repeat(stocks.p1) + "○".repeat(Math.max(0, kosToWin - stocks.p1));
      $("#p2Stocks").textContent = "●".repeat(stocks.p2) + "○".repeat(Math.max(0, kosToWin - stocks.p2));
      $("#p1Pct").style.color = dmgColor(p1.damage);
      $("#p2Pct").style.color = dmgColor(p2.damage);
    }

    function dmgColor(d) {
      if (d < 50) return "#fbbf24";
      if (d < 100) return "#fb923c";
      if (d < 150) return "#f87171";
      return "#ef4444";
    }

    function start(meta) {
      stop();
      matchMeta = meta;
      mapState = cloneMap(meta.mapId || selectedMapId || "hkex");
      const label = $("#mapLabel");
      if (label) label.textContent = mapState.name;
      kosToWin = 2;
      stocks = { p1: kosToWin, p2: kosToWin };
      p1 = fighter(meta.player, mapState.spawn.p1x, 1, "#3b82f6", false);
      p2 = fighter(meta.opponent, mapState.spawn.p2x, -1, "#ea3943", true);
      roundLock = 90;
      tick = 0;
      lastFrameTs = 0;
      simAccum = 0;
      $("#roundMsg").textContent = "準備…";
      $("#resultOverlay").classList.add("hidden");
      running = true;
      keys = {};
      aiState = { cool: 0, jumpCool: 0 };
      const pad = $("#virtPad");
      if (pad) pad.querySelectorAll(".virt-btn.pressed").forEach((b) => b.classList.remove("pressed"));
      resetRoundPositions();
      refreshVirtPad();
      loop();
    }

    function stop() {
      running = false;
      if (raf) cancelAnimationFrame(raf);
      raf = 0;
      keys = {};
      updateAttackButtonCooldown();
    }

    function onKey(e, down) {
      const k = e.key;
      if (
        ["ArrowLeft", "ArrowRight", "ArrowUp", "ArrowDown", " ", "z", "Z", "j", "J", "w", "W", "a", "A", "d", "D", "s", "S"].includes(
          k
        )
      ) {
        e.preventDefault();
      }
      keys[k] = down;
      if (down && (k === "z" || k === "Z" || k === " " || k === "j" || k === "J")) {
        tryAttack(p1, keys["ArrowDown"] || keys["s"] || keys["S"]);
      }
      if (down && (k === "ArrowUp" || k === "w" || k === "W")) tryJump(p1);
    }

    window.addEventListener("keydown", (e) => onKey(e, true));
    window.addEventListener("keyup", (e) => onKey(e, false));

    function wantsTouchPad() {
      try {
        return (
          window.matchMedia("(pointer: coarse)").matches ||
          window.matchMedia("(max-width: 900px)").matches ||
          ("ontouchstart" in window && navigator.maxTouchPoints > 0)
        );
      } catch (_) {
        return "ontouchstart" in window;
      }
    }

    function refreshVirtPad() {
      const pad = $("#virtPad");
      if (!pad) return;
      const inArena = !$("#arena").classList.contains("hidden");
      const show = inArena && wantsTouchPad();
      pad.classList.toggle("visible", show);
      document.body.classList.toggle("fighter-touch-playing", show);
      updateAttackButtonCooldown();
    }

    function updateAttackButtonCooldown() {
      const pad = $("#virtPad");
      if (!pad) return;
      const cooling = !!(p1 && (p1.atkCool > 0 || p1.atkTimer > 0));
      pad.querySelectorAll('.virt-btn.action.attack, .virt-btn.action.smash').forEach((btn) => {
        btn.classList.toggle("on-cooldown", cooling);
      });
    }

    function setHeldKey(code, down) {
      keys[code] = !!down;
    }

    function bindVirtPad() {
      const pad = $("#virtPad");
      if (!pad || pad._bound) return;
      pad._bound = true;

      const releaseAll = () => {
        for (const btn of pad.querySelectorAll(".virt-btn")) {
          btn.classList.remove("pressed");
          const k = btn.dataset.key;
          if (k) setHeldKey(k, false);
        }
      };

      const onDown = (btn, e) => {
        if (e.cancelable) e.preventDefault();
        e.stopPropagation();
        btn.classList.add("pressed");
        const key = btn.dataset.key;
        const action = btn.dataset.action;
        if (key) setHeldKey(key, true);
        if (!running || !p1) return;
        if (action === "jump") tryJump(p1);
        if (action === "attack") {
          tryAttack(p1, !!(keys["ArrowDown"] || keys["s"] || keys["S"]));
        }
        if (action === "smash") {
          tryAttack(p1, true);
        }
      };

      const onUp = (btn, e) => {
        if (e && e.cancelable) e.preventDefault();
        btn.classList.remove("pressed");
        const key = btn.dataset.key;
        if (key) setHeldKey(key, false);
      };

      for (const btn of pad.querySelectorAll(".virt-btn")) {
        btn.addEventListener(
          "pointerdown",
          (e) => {
            try {
              btn.setPointerCapture(e.pointerId);
            } catch (_) {}
            onDown(btn, e);
          },
          { passive: false }
        );
        btn.addEventListener("pointerup", (e) => onUp(btn, e), { passive: false });
        btn.addEventListener("pointercancel", (e) => onUp(btn, e), { passive: false });
        btn.addEventListener("lostpointercapture", () => onUp(btn, null), { passive: true });
        btn.addEventListener("contextmenu", (e) => e.preventDefault());
      }

      window.addEventListener("blur", releaseAll);
      document.addEventListener("visibilitychange", () => {
        if (document.hidden) releaseAll();
      });
      window.addEventListener("resize", refreshVirtPad);
      window.addEventListener("orientationchange", refreshVirtPad);
    }

    bindVirtPad();
    refreshVirtPad();

    function tryJump(f) {
      if (f.hitstun > 0) return;
      if (f.jumps > 0) {
        f.vy = f.jumpV * (f.jumps === 2 ? 1 : 0.85);
        f.onGround = false;
        f.onPlat = null;
        f.jumps--;
      }
    }

    function tryAttack(f, smash) {
      if (f.hitstun > 0 || f.atkCool > 0 || f.atkTimer > 0) return;
      f.smash = !!smash;
      // Fixed 60Hz sim: normal 0.5s CD (30f), heavy 5s CD (300f)
      f.atkTimer = smash ? 18 : 12;
      f.atkCool = smash ? 300 : 30;
    }

    function attackBox(f) {
      if (f.atkTimer <= 0) return null;
      const active = f.smash ? f.atkTimer <= 12 && f.atkTimer >= 6 : f.atkTimer <= 8 && f.atkTimer >= 3;
      if (!active) return null;
      const reach = f.smash ? 52 : 80;
      const hx = f.facing > 0 ? f.x + f.w - 4 : f.x - reach + 4;
      return { x: hx, y: f.y + 10, w: reach, h: f.smash ? 36 : 28, smash: f.smash };
    }

    function hit(attacker, defender) {
      if (defender.invuln > 0 || defender.hitstun > 0) return;
      const box = attackBox(attacker);
      if (!box) return;
      if (
        box.x < defender.x + defender.w &&
        box.x + box.w > defender.x &&
        box.y < defender.y + defender.h &&
        box.y + box.h > defender.y
      ) {
        // Light base 8; heavy = 4× light (32). Same ATK multiplier.
        const base = box.smash ? 32 : 8;
        const dmg = base * (0.7 + attacker.stats.atk / 100);
        defender.damage += dmg;
        const kb =
          (0.4 + defender.damage * 0.012) *
          attacker.knockDealt *
          defender.knockTaken *
          (box.smash ? 1.55 : 1) *
          (30 / (defender.weight * 28));
        const angle = box.smash ? -0.85 : -0.55;
        defender.vx = Math.cos(angle) * kb * 14 * attacker.facing;
        defender.vy = Math.sin(angle) * kb * 14;
        defender.hitstun = Math.min(40, 8 + defender.damage * 0.08);
        defender.onGround = false;
        defender.onPlat = null;
        attacker.atkTimer = 0;
        for (let i = 0; i < 8; i++) {
          particles.push({
            x: defender.x + defender.w / 2,
            y: defender.y + defender.h / 2,
            vx: (Math.random() - 0.5) * 8,
            vy: (Math.random() - 0.5) * 8,
            life: 20,
            color: "#fff",
          });
        }
        updateHud();
      }
    }

    function updateMovingPlatforms() {
      for (const pl of mapState.platforms) {
        if (pl.kind !== "moving") {
          pl._dx = 0;
          pl._dy = 0;
          continue;
        }
        const prevX = pl.x;
        const prevY = pl.y;
        const speed = pl.speed || 1.2;
        if (pl.axis === "y") {
          pl.y += speed * pl.dir;
          if (pl.y >= pl.max) {
            pl.y = pl.max;
            pl.dir = -1;
          } else if (pl.y <= pl.min) {
            pl.y = pl.min;
            pl.dir = 1;
          }
        } else {
          pl.x += speed * pl.dir;
          if (pl.x >= pl.max) {
            pl.x = pl.max;
            pl.dir = -1;
          } else if (pl.x <= pl.min) {
            pl.x = pl.min;
            pl.dir = 1;
          }
        }
        pl._dx = pl.x - prevX;
        pl._dy = pl.y - prevY;
      }
    }

    function landOnPlatform(f, pl) {
      f.y = pl.y - f.h;
      f.vy = 0;
      f.onGround = true;
      f.onPlat = pl;
      f.jumps = 2;
    }

    function physics(f) {
      if (f.invuln > 0) f.invuln--;
      if (f.hitstun > 0) f.hitstun--;
      if (f.atkCool > 0) f.atkCool--;
      if (f.atkTimer > 0) f.atkTimer--;

      // ride moving platform before gravity integrate
      if (f.onGround && f.onPlat && f.onPlat.kind === "moving") {
        f.x += f.onPlat._dx || 0;
        f.y += f.onPlat._dy || 0;
      }

      const grav = 0.55;
      f.vy += grav;
      f.x += f.vx;
      f.y += f.vy;
      f.vx *= f.onGround ? 0.75 : 0.92;

      const feet = f.y + f.h;
      let landed = null;
      if (f.vy >= 0) {
        for (const pl of mapState.platforms) {
          if (
            feet >= pl.y &&
            feet <= pl.y + 18 &&
            f.x + f.w > pl.x + 6 &&
            f.x < pl.x + pl.w - 6
          ) {
            // prefer highest (smallest y) platform under feet this frame
            if (!landed || pl.y < landed.y) landed = pl;
          }
        }
      }

      if (landed) {
        landOnPlatform(f, landed);
      } else {
        f.onGround = false;
        f.onPlat = null;
      }
    }


    function resolveBodyCollision(a, b) {
      // Solid bodies: fighters cannot overlap / pass through each other
      const ax2 = a.x + a.w;
      const ay2 = a.y + a.h;
      const bx2 = b.x + b.w;
      const by2 = b.y + b.h;
      if (a.x >= bx2 || ax2 <= b.x || a.y >= by2 || ay2 <= b.y) return;

      const overlapX = Math.min(ax2, bx2) - Math.max(a.x, b.x);
      const overlapY = Math.min(ay2, by2) - Math.max(a.y, b.y);

      if (overlapX < overlapY) {
        const push = overlapX / 2 + 0.01;
        if (a.x + a.w / 2 < b.x + b.w / 2) {
          a.x -= push;
          b.x += push;
        } else {
          a.x += push;
          b.x -= push;
        }
        // Cancel velocity pushing into each other so they block
        if (a.x < b.x) {
          if (a.vx > 0) a.vx = 0;
          if (b.vx < 0) b.vx = 0;
        } else {
          if (a.vx < 0) a.vx = 0;
          if (b.vx > 0) b.vx = 0;
        }
      } else {
        const push = overlapY / 2 + 0.01;
        if (a.y + a.h / 2 < b.y + b.h / 2) {
          a.y -= push;
          b.y += push;
          if (a.vy > 0) a.vy = 0;
          if (b.vy < 0) b.vy = 0;
        } else {
          a.y += push;
          b.y -= push;
          if (b.vy > 0) b.vy = 0;
          if (a.vy < 0) a.vy = 0;
        }
      }
    }

    function stageCenter() {
      const mains = mapState.platforms.filter((p) => p.kind === "main");
      if (!mains.length) return { x: W / 2, y: mainFloorY(), left: 100, right: W - 100 };
      let left = Infinity,
        right = -Infinity,
        y = mains[0].y;
      for (const m of mains) {
        left = Math.min(left, m.x);
        right = Math.max(right, m.x + m.w);
        y = Math.min(y, m.y);
      }
      return { x: (left + right) / 2, y, left, right };
    }

    function controlP1() {
      if (p1.hitstun > 0) return;
      const left = keys["ArrowLeft"] || keys["a"] || keys["A"];
      const right = keys["ArrowRight"] || keys["d"] || keys["D"];
      const spd = p1.onGround ? p1.moveSpd : p1.airSpd;
      if (left) {
        p1.vx = -spd;
        p1.facing = -1;
      }
      if (right) {
        p1.vx = spd;
        p1.facing = 1;
      }
    }

    function controlAI() {
      const f = p2;
      if (f.hitstun > 0) return;
      aiState.cool--;
      aiState.jumpCool--;
      const target = p1;
      const dx = target.x - f.x;
      const diff = (matchMeta.difficulty || "normal").toLowerCase();
      const react = diff === "easy" ? 0.55 : diff === "hard" ? 0.95 : 0.75;
      const spd = f.onGround ? f.moveSpd : f.airSpd;
      const stage = stageCenter();

      if (Math.random() < react) {
        if (Math.abs(dx) > 50) {
          f.vx = Math.sign(dx) * spd;
          f.facing = Math.sign(dx) || f.facing;
        } else {
          f.facing = Math.sign(dx) || f.facing;
          if (aiState.cool <= 0) {
            tryAttack(f, target.damage > 80 && Math.random() < 0.35);
            aiState.cool = diff === "easy" ? 40 : diff === "hard" ? 18 : 28;
          }
        }
      }
      if (f.x < stage.left - 30 || f.x > stage.right + 30 || f.y > stage.y + 50) {
        f.vx = Math.sign(stage.x - f.x) * f.airSpd * 1.1;
        if (aiState.jumpCool <= 0 && f.jumps > 0) {
          tryJump(f);
          aiState.jumpCool = 20;
        }
      } else if (target.y < f.y - 40 && aiState.jumpCool <= 0 && Math.random() < 0.04) {
        tryJump(f);
        aiState.jumpCool = 35;
      }
    }

    function checkKO(f, who) {
      const BLAST = mapState.blast;
      if (f.x + f.w < BLAST.left || f.x > BLAST.right || f.y > BLAST.bottom || f.y + f.h < BLAST.top) {
        if (who === "p1") stocks.p1--;
        else stocks.p2--;
        updateHud();
        particles.push({
          x: Math.max(40, Math.min(W - 40, f.x)),
          y: Math.max(40, Math.min(H - 40, f.y)),
          vx: 0,
          vy: 0,
          life: 40,
          color: "#fbbf24",
          text: "KO!",
        });
        if (stocks.p1 <= 0 || stocks.p2 <= 0) {
          endMatch();
          return true;
        }
        roundLock = 75;
        $("#roundMsg").textContent = "擊飛！";
        resetRoundPositions();
        return true;
      }
      return false;
    }

    async function endMatch() {
      stop();
      const pWin = stocks.p2 <= 0;
      const oWin = stocks.p1 <= 0;
      const winner = pWin && !oWin ? "player" : oWin && !pWin ? "opponent" : "draw";
      const pk = kosToWin - stocks.p2;
      const ok = kosToWin - stocks.p1;
      $("#resultTitle").textContent =
        winner === "player" ? "勝利！" : winner === "opponent" ? "敗北…" : "平手";
      $("#resultDetail").textContent = `比分 ${pk}–${ok}　（先至 ${kosToWin} KO）・${mapState.name}`;
      $("#resultOverlay").classList.remove("hidden");
      $("#roundMsg").textContent = "完場";
      try {
        await api("/api/fighter/result", {
          method: "POST",
          body: JSON.stringify({
            mode: matchMeta.mode,
            opponent_username: matchMeta.opponent.username || matchMeta.opponent.display_name || "AI",
            winner,
            player_kos: pk,
            opponent_kos: ok,
            player_stats: {
              atk: matchMeta.player.atk,
              def: matchMeta.player.def,
              spd: matchMeta.player.spd,
            },
            opponent_stats: {
              atk: matchMeta.opponent.atk,
              def: matchMeta.opponent.def,
              spd: matchMeta.opponent.spd,
            },
            difficulty: matchMeta.difficulty,
          }),
        });
      } catch (_) {
        /* non-fatal */
      }
    }

    function drawBackground() {
      const bg = mapState.bg;
      const g = ctx.createLinearGradient(0, 0, 0, H);
      g.addColorStop(0, bg.top);
      g.addColorStop(1, bg.bottom);
      ctx.fillStyle = g;
      ctx.fillRect(0, 0, W, H);

      if (bg.theme === "hkex") {
        ctx.fillStyle = "rgba(255,255,255,.35)";
        for (let i = 0; i < 40; i++) {
          ctx.fillRect((i * 97) % W, (i * 53) % 260, 2, 2);
        }
        // skyline
        ctx.fillStyle = "rgba(30,58,95,.55)";
        for (let i = 0; i < 12; i++) {
          const bx = 40 + i * 80;
          const bh = 60 + ((i * 37) % 90);
          ctx.fillRect(bx, 280 - bh, 50, bh);
        }
      } else if (bg.theme === "wallstreet") {
        ctx.fillStyle = "rgba(255,255,255,.25)";
        for (let i = 0; i < 50; i++) {
          ctx.fillRect((i * 73) % W, (i * 41) % 240, 2, 2);
        }
        ctx.fillStyle = "rgba(148,163,184,.28)";
        const buildings = [
          [30, 200],
          [120, 260],
          [210, 180],
          [700, 220],
          [790, 280],
          [880, 190],
        ];
        for (const [bx, bh] of buildings) {
          ctx.fillRect(bx, 450 - bh, 70, bh);
          ctx.fillStyle = "rgba(251,191,36,.15)";
          for (let wy = 450 - bh + 10; wy < 440; wy += 18) {
            ctx.fillRect(bx + 10, wy, 8, 8);
            ctx.fillRect(bx + 30, wy, 8, 8);
            ctx.fillRect(bx + 50, wy, 8, 8);
          }
          ctx.fillStyle = "rgba(148,163,184,.28)";
        }
        // moon
        ctx.fillStyle = "rgba(253,224,71,.35)";
        ctx.beginPath();
        ctx.arc(820, 70, 28, 0, Math.PI * 2);
        ctx.fill();
      } else if (bg.theme === "vault") {
        // vault wall rivets
        ctx.fillStyle = "rgba(68,64,60,.8)";
        ctx.fillRect(0, 0, 60, H);
        ctx.fillRect(W - 60, 0, 60, H);
        ctx.fillStyle = "rgba(217,119,6,.25)";
        for (let y = 40; y < H; y += 40) {
          ctx.beginPath();
          ctx.arc(30, y, 6, 0, Math.PI * 2);
          ctx.arc(W - 30, y, 6, 0, Math.PI * 2);
          ctx.fill();
        }
        // door circle
        ctx.strokeStyle = "rgba(251,191,36,.35)";
        ctx.lineWidth = 4;
        ctx.beginPath();
        ctx.arc(W / 2, 200, 70, 0, Math.PI * 2);
        ctx.stroke();
        ctx.strokeStyle = "rgba(251,191,36,.2)";
        ctx.beginPath();
        ctx.arc(W / 2, 200, 40, 0, Math.PI * 2);
        ctx.stroke();
      }

      // blast zone hints
      ctx.strokeStyle = "rgba(234,57,67,.25)";
      ctx.setLineDash([6, 6]);
      ctx.strokeRect(40, 40, W - 80, H - 80);
      ctx.setLineDash([]);
    }

    function drawPlatforms() {
      for (const pl of mapState.platforms) {
        ctx.fillStyle = pl.color || "#334155";
        roundRect(pl.x, pl.y, pl.w, pl.h, pl.kind === "main" ? 8 : 5);
        ctx.fill();
        ctx.fillStyle = pl.accent || "#16c784";
        ctx.fillRect(pl.x + 3, pl.y, pl.w - 6, 4);
        if (pl.kind === "moving") {
          // motion chevrons
          ctx.fillStyle = "rgba(255,255,255,.55)";
          ctx.font = "10px sans-serif";
          const tag = pl.axis === "y" ? "↕" : "↔";
          ctx.fillText(tag, pl.x + pl.w / 2 - 4, pl.y + pl.h - 3);
        }
      }
      // ticker on widest main
      const mains = mapState.platforms.filter((p) => p.kind === "main");
      if (mains.length) {
        const m = mains.reduce((a, b) => (a.w >= b.w ? a : b));
        ctx.fillStyle = "rgba(230,237,243,.5)";
        ctx.font = "11px monospace";
        ctx.fillText(mapState.ticker || "", m.x + 16, m.y + 20);
      }
    }

    function draw() {
      drawBackground();
      drawPlatforms();
      drawFighter(p1);
      drawFighter(p2);

      for (const pt of particles) {
        if (pt.text) {
          ctx.fillStyle = pt.color;
          ctx.font = "bold 28px sans-serif";
          ctx.fillText(pt.text, pt.x, pt.y);
        } else {
          ctx.globalAlpha = pt.life / 20;
          ctx.fillStyle = pt.color;
          ctx.fillRect(pt.x, pt.y, 4, 4);
          ctx.globalAlpha = 1;
        }
      }

      if (roundLock > 30) {
        ctx.fillStyle = "rgba(0,0,0,.35)";
        ctx.fillRect(0, 0, W, H);
        ctx.fillStyle = "#fff";
        ctx.font = "bold 48px sans-serif";
        ctx.textAlign = "center";
        const t = roundLock > 60 ? "準備" : "開始！";
        ctx.fillText(t, W / 2, H / 2);
        ctx.font = "16px sans-serif";
        ctx.fillStyle = "rgba(255,255,255,.85)";
        ctx.fillText(mapState.name, W / 2, H / 2 + 36);
        ctx.textAlign = "left";
      }
    }

    function roundRect(x, y, w, h, r) {
      ctx.beginPath();
      ctx.moveTo(x + r, y);
      ctx.arcTo(x + w, y, x + w, y + h, r);
      ctx.arcTo(x + w, y + h, x, y + h, r);
      ctx.arcTo(x, y + h, x, y, r);
      ctx.arcTo(x, y, x + w, y, r);
      ctx.closePath();
    }

    function drawFighter(f) {
      const blink = f.invuln > 0 && Math.floor(f.invuln / 3) % 2 === 0;
      if (blink) return;

      const set = f.isAI ? sprites.p2 : sprites.p1;
      const key = pickSpriteKey(f);
      const img = set[key] || set.idle;
      const cx = f.x + f.w / 2;
      const feetY = f.y + f.h;
      // Visual taller than hitbox; feet stay on hitbox bottom
      const drawH = 118;
      let drawW = drawH;
      const ok = !!(img && img.complete && img.naturalWidth > 0);
      const isWalkStrip = key === "walk" && ok && img.naturalWidth >= img.naturalHeight * 2;
      let srcX = 0,
        srcY = 0,
        srcW = 0,
        srcH = 0;
      if (ok) {
        if (isWalkStrip) {
          srcW = img.naturalWidth / WALK_FRAMES;
          srcH = img.naturalHeight;
          srcX = (Math.floor(tick / WALK_FRAME_TICKS) % WALK_FRAMES) * srcW;
          srcY = 0;
          drawW = (srcW / srcH) * drawH;
        } else {
          drawW = (img.naturalWidth / img.naturalHeight) * drawH;
        }
      }

      // Soft ground shadow so fighters read clearly on platforms
      ctx.save();
      ctx.fillStyle = "rgba(0,0,0,.35)";
      ctx.beginPath();
      ctx.ellipse(cx, feetY - 2, 22, 6, 0, 0, Math.PI * 2);
      ctx.fill();
      ctx.restore();

      if (ok) {
        ctx.save();
        ctx.translate(cx, feetY);
        ctx.scale(f.facing >= 0 ? 1 : -1, 1);
        if (isWalkStrip) {
          ctx.drawImage(img, srcX, srcY, srcW, srcH, -drawW / 2, -drawH, drawW, drawH);
        } else {
          ctx.drawImage(img, -drawW / 2, -drawH, drawW, drawH);
        }
        ctx.restore();
      } else {
        // brief fallback while loading / if asset missing — kick another preload
        if (!spritesReady) ensureSprites();
        ctx.fillStyle = f.color;
        roundRect(f.x, f.y, f.w, f.h, 6);
        ctx.fill();
      }

      if (f.damage > 60) {
        ctx.strokeStyle = `rgba(251,191,36,${Math.min(0.8, f.damage / 200)})`;
        ctx.lineWidth = 2;
        ctx.strokeRect(f.x - 4, f.y - 8, f.w + 8, f.h + 10);
      }
      // subtle attack arc (hitbox already has FX in attack sprite)
      const box = attackBox(f);
      if (box && !(img && img.complete)) {
        ctx.fillStyle = box.smash ? "rgba(251,191,36,.55)" : "rgba(255,255,255,.4)";
        ctx.fillRect(box.x, box.y, box.w, box.h);
      } else if (box) {
        ctx.strokeStyle = box.smash ? "rgba(251,191,36,.45)" : "rgba(196,181,253,.35)";
        ctx.lineWidth = 1.5;
        ctx.strokeRect(box.x, box.y, box.w, box.h);
      }
      ctx.fillStyle = "rgba(0,0,0,.55)";
      ctx.font = "11px sans-serif";
      const label = f.isAI ? "AI" : "YOU";
      ctx.fillText(label, f.x + f.w / 2 - 10, f.y - 14);
    }

    function simStep() {
      tick++;
      if (roundLock > 0) {
        // still animate platforms during countdown for visual life
        updateMovingPlatforms();
        roundLock--;
        if (roundLock === 30) $("#roundMsg").textContent = "開始！";
        if (roundLock === 0) $("#roundMsg").textContent = "擊飛出界！";
        return;
      }
      updateMovingPlatforms();
      controlP1();
      controlAI();
      physics(p1);
      physics(p2);
      resolveBodyCollision(p1, p2);
      hit(p1, p2);
      hit(p2, p1);
      for (const pt of particles) {
        pt.x += pt.vx;
        pt.y += pt.vy;
        pt.life--;
      }
      particles = particles.filter((p) => p.life > 0);
      updateAttackButtonCooldown();
      if (checkKO(p1, "p1") || checkKO(p2, "p2")) return;
    }

    // Fixed 60Hz simulation driven by real time so 320Hz displays match 60Hz feel.
    function loop(ts) {
      if (!running) return;
      raf = requestAnimationFrame(loop);
      if (typeof ts !== "number") ts = performance.now();
      if (!lastFrameTs) lastFrameTs = ts;
      let dt = (ts - lastFrameTs) / 1000;
      lastFrameTs = ts;
      if (dt > MAX_FRAME_DT) dt = MAX_FRAME_DT;
      if (dt < 0) dt = 0;
      simAccum += dt;
      let steps = 0;
      const maxSteps = 5; // ~83ms catch-up max
      while (simAccum >= SIM_DT && steps < maxSteps && running) {
        simStep();
        simAccum -= SIM_DT;
        steps++;
      }
      if (steps >= maxSteps) simAccum = 0;
      draw();
    }

    return { start, stop, refreshVirtPad, MAPS, ensureSprites, get spritesReady() { return spritesReady; } };
  })();

  // expose map catalog for tests / debugging
  window.__FIGHTER_MAPS__ = MAPS;

  bindMapPicker();
  loadLobby().catch((e) => toast(e.message));
})();
