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

  const ASSET_VER = "20261018s";
  const CHARACTERS = [
    {
      id: "herta",
      name: "大黑塔",
      tag: "法師・預設",
      portrait: `/static/fighter/sprites/herta/portrait.png?v=${ASSET_VER}`,
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
    const fallbackPortrait = `/static/fighter/sprites/portrait.png?v=${ASSET_VER}`;
    grid.innerHTML = CHARACTERS.map((c) => {
      const on = c.id === selectedCharId ? "selected" : "";
      return `<button type="button" class="char-card ${on}" data-char="${c.id}" role="radio" aria-checked="${c.id === selectedCharId}">
        <img src="${c.portrait}" alt="${c.name}" width="120" height="180" draggable="false" onerror="this.onerror=null;this.src='${fallbackPortrait}'">
        <div class="char-name">${c.name}</div>
        <div class="char-tag">${c.tag}</div>
      </button>`;
    }).join("");
    grid.querySelectorAll(".char-card").forEach((btn) => {
      btn.onclick = () => {
        selectedCharId = btn.dataset.char || "herta";
        renderCharGrid();
        Game.ensureSprites(selectedCharId);
      };
    });
  }

  async function beginFight(ctx) {
    clearSelectTimer();
    const ov = $("#charSelect");
    if (ov) ov.classList.add("hidden");
    ctx.characterId = selectedCharId;
    try {
      const ok = await Game.ensureSprites(selectedCharId);
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
    Game.ensureSprites(selectedCharId);
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

    // Action sprites (facing right in source art). Cache-bust so browsers don't keep old JS-era 404s.
    const ASSET_VER = "20261018s";
    const SPRITE_KEYS = [
      "idle",
      "walk",
      "run",
      "attack1",
      "attack2",
      "attack3",
      "crouch_attack",
      "aerial_attack",
      "heavy",
      "jump",
      "hurt",
    ];
    // Until new art lands, map missing keys to legacy attack.png (or closest).
    const SPRITE_FALLBACK = {
      attack1: "attack",
      attack2: "attack",
      attack3: "attack",
      crouch_attack: "attack",
      aerial_attack: "attack",
    };
    const WALK_FRAMES = 6;
    const WALK_FRAME_TICKS = 7; // ~8.5 fps at fixed 60Hz sim
    const RUN_FRAMES = 9;
    const RUN_FRAME_TICKS = 6; // 10 fps at 60Hz — smooth loop for 9-frame run
    const HEAVY_FRAMES = 4;
    const ATTACK_FRAMES = 3; // light combo sheets are 3-frame horizontal strips
    const LIGHT_ATK_DURATION = 18; // 0.3s @60Hz — 3 frames × 6 ticks
    const CROUCH_ATK_FRAMES = 4; // crouch strip: windup + mid + impact + hold
    const CROUCH_CHAR_FRAME_TICKS = 30; // 0.5s per char frame — frames 1–3 = 1.5s total
    const CROUCH_FX_START = 3 * CROUCH_CHAR_FRAME_TICKS; // after frame 3 finishes (elapsed 90)
    const CROUCH_FX_DURATION = 60; // VFX alone 1s @60Hz
    const CROUCH_ATK_DURATION = CROUCH_FX_START + CROUCH_FX_DURATION; // 150: 1.5s strip then 1s FX
    const CROUCH_AERIAL_ATK_DURATION = 36; // aerial stays 0.6s — 3 frames × 0.2s
    const CROUCH_FX_SIDE = 288; // square VFX/hitbox: 3× prior crouch reach (96)
    const CROUCH_FX_AHEAD = 2; // place FX center ~2 character widths ahead of front
    const HEAVY_ATK_FRAMES = 180; // 3s at 60Hz — 4 frames × ~45 ticks; laser in last phase
    const HEAVY_LASER_FRAMES = 60; // last 1s: beam active + drawn from character front
    const HEAVY_REACH = 2000; // off-map horizontal beam
    const SIM_HZ = 60;
    const SIM_DT = 1 / SIM_HZ;
    const MAX_FRAME_DT = 0.05; // 50ms cap — avoid spiral after tab switch
    const STAMINA_MAX = 100;
    const STAMINA_REGEN_PER_SEC = 20; // full bar in 5s when idle
    const STAMINA_COST_NORMAL = 20;
    const STAMINA_COST_CROUCH = 50; // crouch attack stamina
    const STAMINA_COST_HEAVY = 99;
    const COMBO_WINDOW_FRAMES = 36;
    const RUN_TAP_WINDOW_MS = 300; // double-tap ←/→ or A/D within 0.3s to run
    const RUN_SPD_MULT = 1.85; // run vs walk speed // 0.6s at 60Hz to chain next hit
    const sprites = { p1: {}, p2: {} };
    let spritesReady = false;
    let spritesFailed = 0;
    let spritesPromise = null;
    let spritesCharId = null;

    function spriteUrl(charId, file) {
      return `/static/fighter/sprites/${charId}/${file}?v=${ASSET_VER}`;
    }

    function flatSpriteUrl(file) {
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

    async function loadSpriteWithFallback(charId, fileBase) {
      // Prefer /sprites/{id}/{file}; fall back to flat /sprites/{file} (herta legacy).
      let img = await loadImage(spriteUrl(charId, fileBase));
      if (img && img.naturalWidth > 0) return img;
      img = await loadImage(flatSpriteUrl(fileBase));
      if (img && img.naturalWidth > 0) return img;
      // Last resort: legacy attack art for new attack keys
      const stem = fileBase.replace(/_ai\.png$/, "").replace(/\.png$/, "");
      const fb = SPRITE_FALLBACK[stem];
      if (fb) {
        const ai = fileBase.includes("_ai");
        const fbFile = ai ? `${fb}_ai.png` : `${fb}.png`;
        img = await loadImage(spriteUrl(charId, fbFile));
        if (img && img.naturalWidth > 0) return img;
        img = await loadImage(flatSpriteUrl(fbFile));
      }
      return img;
    }

    function ensureSprites(charId) {
      const id = charId || selectedCharId || "herta";
      if (spritesReady && spritesCharId === id) return Promise.resolve(true);
      // Reload when character changes
      if (spritesCharId !== id) {
        spritesPromise = null;
        spritesReady = false;
      }
      if (spritesPromise) return spritesPromise;
      spritesCharId = id;
      spritesPromise = (async () => {
        spritesFailed = 0;
        const jobs = [];
        for (const key of SPRITE_KEYS) {
          jobs.push(
            loadSpriteWithFallback(id, `${key}.png`).then((img) => {
              sprites.p1[key] = img;
              if (!(img && img.naturalWidth > 0)) spritesFailed++;
            })
          );
          jobs.push(
            loadSpriteWithFallback(id, `${key}_ai.png`).then((img) => {
              sprites.p2[key] = img;
              if (!(img && img.naturalWidth > 0)) spritesFailed++;
            })
          );
        }
        await Promise.all(jobs);
        // Also keep legacy "attack" alias pointing at attack1 for any leftover refs
        sprites.p1.attack = sprites.p1.attack1;
        sprites.p2.attack = sprites.p2.attack1;
        // Separate unidirectional laser beam (from character front → off-map)
        const laserImg = await loadSpriteWithFallback(id, "heavy_laser_beam.png");
        sprites.p1.heavy_laser = laserImg;
        sprites.p2.heavy_laser = laserImg;
        if (!(laserImg && laserImg.naturalWidth > 0)) {
          const full = await loadSpriteWithFallback(id, "heavy_laser.png");
          sprites.p1.heavy_laser = full;
          sprites.p2.heavy_laser = full;
        }
        // Separate crouch-attack VFX overlay (not part of character strip)
        const crouchFx = await loadSpriteWithFallback(id, "crouch_fx.png");
        sprites.p1.crouch_fx = crouchFx;
        sprites.p2.crouch_fx = crouchFx;
        spritesReady = SPRITE_KEYS.every(
          (k) => sprites.p1[k] && sprites.p1[k].naturalWidth > 0 && sprites.p2[k] && sprites.p2[k].naturalWidth > 0
        );
        window.__FIGHTER_SPRITES__ = { ready: spritesReady, failed: spritesFailed, sprites, charId: id };
        return spritesReady;
      })();
      return spritesPromise;
    }
    // Kick off preload immediately (default herta)
    ensureSprites("herta");

    function pickSpriteKey(f) {
      if (f.hitstun > 0) return "hurt";
      if (f.atkTimer > 0) {
        if (f.atkKind && SPRITE_KEYS.includes(f.atkKind)) return f.atkKind;
        return f.smash ? "heavy" : "attack1";
      }
      if (!f.onGround) return "jump";
      if (f.running && Math.abs(f.vx) > 0.5) return "run";
      if (Math.abs(f.vx) > 0.35) return "walk";
      return "idle";
    }

    let running = false;
    let raf = 0;
    let keys = {};
    let lastMoveTap = { dir: 0, t: 0 }; // double-tap run: dir -1|1, t = performance.now()
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
        atkDuration: 0,
        atkCool: 0, // unused (kept for compat); stamina gates attacks now
        atkKind: null, // attack1|attack2|attack3|crouch_attack|aerial_attack|heavy
        atkConnected: false, // heavy laser hits once per swing
        smash: false,
        stamina: STAMINA_MAX,
        comboStep: 0, // 0 = next light is attack1
        comboWindow: 0,
        crouching: false,
        running: false,
        runDir: 0,
        hitstun: 0,
        invuln: 0,
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
      p1.atkDuration = 0;
      p1.atkKind = null;
      p1.atkConnected = false;
      p1.smash = false;
      p1.stamina = STAMINA_MAX;
      p1.comboStep = 0;
      p1.comboWindow = 0;
      p1.crouching = false;
      p1.running = false;
      p1.runDir = 0;
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
      p2.atkDuration = 0;
      p2.atkKind = null;
      p2.atkConnected = false;
      p2.smash = false;
      p2.stamina = STAMINA_MAX;
      p2.comboStep = 0;
      p2.comboWindow = 0;
      p2.crouching = false;
      p2.running = false;
      p2.runDir = 0;
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
      updateStaminaHud();
    }

    function updateStaminaHud() {
      const setBar = (fillId, textId, f) => {
        const fill = document.getElementById(fillId);
        const txt = document.getElementById(textId);
        if (!f) return;
        const pct = Math.max(0, Math.min(100, (f.stamina / STAMINA_MAX) * 100));
        if (fill) fill.style.width = pct + "%";
        if (txt) txt.textContent = Math.floor(f.stamina);
      };
      setBar("p1StamFill", "p1StamVal", p1);
      setBar("p2StamFill", "p2StamVal", p2);
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
      ensureSprites(meta.characterId || selectedCharId || "herta");
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

    function moveDirFromKey(k) {
      if (k === "ArrowLeft" || k === "a" || k === "A") return -1;
      if (k === "ArrowRight" || k === "d" || k === "D") return 1;
      return 0;
    }

    function noteMoveTap(dir) {
      if (!dir || !p1) return;
      const now = performance.now();
      if (lastMoveTap.dir === dir && now - lastMoveTap.t <= RUN_TAP_WINDOW_MS) {
        p1.running = true;
        p1.runDir = dir;
        p1.facing = dir;
      }
      lastMoveTap = { dir, t: now };
    }

    function stopRunIfNeeded(dirHeldLeft, dirHeldRight) {
      if (!p1 || !p1.running) return;
      // Opposite direction cancels run
      if ((p1.runDir < 0 && dirHeldRight) || (p1.runDir > 0 && dirHeldLeft)) {
        p1.running = false;
        p1.runDir = 0;
        return;
      }
      // Release of run direction cancels
      if ((p1.runDir < 0 && !dirHeldLeft) || (p1.runDir > 0 && !dirHeldRight)) {
        p1.running = false;
        p1.runDir = 0;
      }
    }

    function onKey(e, down) {
      const k = e.key;
      if (
        [
          "ArrowLeft",
          "ArrowRight",
          "ArrowUp",
          "ArrowDown",
          " ",
          "z",
          "Z",
          "j",
          "J",
          "k",
          "K",
          "w",
          "W",
          "a",
          "A",
          "d",
          "D",
          "s",
          "S",
        ].includes(k)
      ) {
        e.preventDefault();
      }
      keys[k] = down;
      if (!running || !p1) return;
      const md = moveDirFromKey(k);
      if (down && md) noteMoveTap(md);
      if (!down && md && p1.running && p1.runDir === md) {
        p1.running = false;
        p1.runDir = 0;
      }
      if (down && (k === "z" || k === "Z" || k === " " || k === "j" || k === "J")) {
        tryAttack(p1, false); // light / crouch / aerial (context from stance)
      }
      if (down && (k === "k" || k === "K")) {
        tryAttack(p1, true); // heavy
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
      const busy = !!(p1 && p1.atkTimer > 0);
      const lowLight = !!(p1 && p1.stamina < STAMINA_COST_NORMAL);
      const lowHeavy = !!(p1 && p1.stamina < STAMINA_COST_HEAVY);
      pad.querySelectorAll(".virt-btn.action.attack").forEach((btn) => {
        btn.classList.toggle("on-cooldown", busy || lowLight);
      });
      pad.querySelectorAll(".virt-btn.action.smash").forEach((btn) => {
        btn.classList.toggle("on-cooldown", busy || lowHeavy);
      });
    }

    function setHeldKey(code, down) {
      const was = !!keys[code];
      keys[code] = !!down;
      if (!running || !p1) return;
      const md = moveDirFromKey(code);
      if (down && !was && md) noteMoveTap(md);
      if (!down && md && p1.running && p1.runDir === md) {
        p1.running = false;
        p1.runDir = 0;
      }
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
          tryAttack(p1, false);
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

    function tryAttack(f, heavy) {
      if (!f || f.hitstun > 0 || f.atkTimer > 0) return false;

      // Heavy (K / 重攻擊鍵) — ground preferred; still allow in air as smash aerial
      if (heavy) {
        if (f.stamina < STAMINA_COST_HEAVY) return false;
        f.stamina -= STAMINA_COST_HEAVY;
        f.smash = true;
        f.atkKind = "heavy";
        f.atkTimer = HEAVY_ATK_FRAMES; // 3s heavy sequence (laser last 1s)
        f.atkConnected = false;
        f.atkCool = 0;
        f.comboStep = 0;
        f.comboWindow = 0;
        updateStaminaHud();
        updateAttackButtonCooldown();
        return true;
      }

      // Aerial light
      if (!f.onGround) {
        if (f.stamina < STAMINA_COST_NORMAL) return false;
        f.stamina -= STAMINA_COST_NORMAL;
        f.smash = false;
        f.atkKind = "aerial_attack";
        f.atkTimer = CROUCH_AERIAL_ATK_DURATION; // 3 frames × 0.2s
        f.atkDuration = f.atkTimer;
        f.atkCool = 0;
        f.comboStep = 0;
        f.comboWindow = 0;
        updateStaminaHud();
        updateAttackButtonCooldown();
        return true;
      }

      // Crouch light (hold ↓ / S on ground) — read keys too so same-frame ↓+Z works
      const holdDown = !f.isAI && (keys["ArrowDown"] || keys["s"] || keys["S"]);
      if (f.onGround && (f.crouching || holdDown)) {
        if (f.stamina < STAMINA_COST_CROUCH) return false;
        f.stamina -= STAMINA_COST_CROUCH;
        f.smash = false;
        f.atkKind = "crouch_attack";
        f.atkTimer = CROUCH_ATK_DURATION; // frames 1–3 then 1s VFX (after frame 3)
        f.atkDuration = f.atkTimer;
        f.atkConnected = false; // one connect; keep full 3s anim + VFX
        f.atkCool = 0;
        f.comboStep = 0;
        f.comboWindow = 0;
        updateStaminaHud();
        updateAttackButtonCooldown();
        return true;
      }

      if (f.stamina < STAMINA_COST_NORMAL) return false;

      // Standing 3-hit combo
      f.stamina -= STAMINA_COST_NORMAL;
      if (f.comboWindow <= 0) f.comboStep = 0;
      f.comboStep = Math.min(3, (f.comboStep || 0) + 1);
      f.smash = false;
      f.atkKind = "attack" + f.comboStep;
      // 3-frame strip per swing; finisher slightly longer so recovery frame reads
      f.atkTimer = f.comboStep === 3 ? 21 : LIGHT_ATK_DURATION;
      f.atkDuration = f.atkTimer;
      f.atkCool = 0;
      f.comboWindow = 0; // re-armed when this swing ends
      updateStaminaHud();
      updateAttackButtonCooldown();
      return true;
    }

    function attackBox(f) {
      if (f.atkTimer <= 0) return null;
      const kind = f.atkKind || (f.smash ? "heavy" : "attack1");
      let active = false;
      let reach = 72;
      let hy = f.y + 10;
      let hh = 28;
      let smash = false;
      if (kind === "heavy") {
        // Laser active in final phase (last HEAVY_LASER_FRAMES of 180)
        active = f.atkTimer <= HEAVY_LASER_FRAMES && f.atkTimer >= 1;
        reach = HEAVY_REACH; // thin beam from front to off-map
        hy = f.y + 16;
        hh = 22;
        smash = true;
      } else if (kind === "aerial_attack") {
        // 3×0.2s strip; hit active from frame 2 onward (not frame 1)
        // atkTimer counts down from 36: frame2+ when atkTimer <= 24
        active = f.atkTimer <= 24 && f.atkTimer >= 1;
        reach = 86;
        hy = f.y + 4;
        hh = 36;
      } else if (kind === "crouch_attack") {
        // Big square hit only while separate VFX plays (after frame 3, 1s)
        const elapsed = (f.atkDuration || CROUCH_ATK_DURATION) - f.atkTimer;
        active =
          elapsed >= CROUCH_FX_START &&
          elapsed < CROUCH_FX_START + CROUCH_FX_DURATION &&
          f.atkTimer >= 1;
        // Square 3× prior reach (96→288), center ~2 char widths ahead of front
        reach = CROUCH_FX_SIDE;
        hh = CROUCH_FX_SIDE;
        const ahead = CROUCH_FX_AHEAD * f.w;
        const cx = f.facing > 0 ? f.x + f.w + ahead : f.x - ahead;
        hy = f.y + f.h - CROUCH_FX_SIDE * 0.85;
        f._crouchFxCx = cx;
      } else if (kind === "attack2") {
        // Middle third of strip (frame 2 / slash)
        active = f.atkTimer <= 12 && f.atkTimer >= 7;
        reach = 84;
        hh = 30;
      } else if (kind === "attack3") {
        active = f.atkTimer <= 14 && f.atkTimer >= 8;
        reach = 92;
        hh = 32;
      } else {
        // attack1 — thrust active on frame 2
        active = f.atkTimer <= 12 && f.atkTimer >= 7;
        reach = 80;
      }
      if (!active) return null;
      let hx;
      if (kind === "crouch_attack" && f._crouchFxCx != null) {
        hx = f._crouchFxCx - reach / 2;
      } else {
        hx = f.facing > 0 ? f.x + f.w - 4 : f.x - reach + 4;
      }
      return { x: hx, y: hy, w: reach, h: hh, smash, kind };
    }

    function hit(attacker, defender) {
      if (defender.invuln > 0 || defender.hitstun > 0) return;
      const box = attackBox(attacker);
      if (!box) return;
      // Heavy laser / crouch: one connect per swing (animation keeps playing)
      if ((box.smash || box.kind === "crouch_attack") && attacker.atkConnected) return;
      if (
        box.x < defender.x + defender.w &&
        box.x + box.w > defender.x &&
        box.y < defender.y + defender.h &&
        box.y + box.h > defender.y
      ) {
        // Light base 8 (combo3 = 10); heavy = 5× light (40). Same ATK multiplier.
        const base = box.smash ? 40 : box.kind === "attack3" ? 10 : box.kind === "aerial_attack" ? 9 : 8;
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
        if (box.smash) {
          attacker.atkConnected = true;
          // Keep heavy animation running full HEAVY_ATK_FRAMES (3s)
        } else if (attacker.atkKind === "crouch_attack") {
          attacker.atkConnected = true; // one hit; keep 3s strip + VFX playing
        } else if (attacker.atkKind === "attack1" || attacker.atkKind === "attack2") {
          attacker.comboWindow = COMBO_WINDOW_FRAMES;
          attacker.atkTimer = 0;
          attacker.atkKind = null;
          attacker.smash = false;
        } else {
          attacker.comboStep = 0;
          attacker.comboWindow = 0;
          attacker.atkTimer = 0;
          attacker.atkKind = null;
          attacker.smash = false;
        }
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

      const wasAtk = f.atkTimer > 0;
      if (f.atkTimer > 0) f.atkTimer--;
      if (wasAtk && f.atkTimer <= 0) {
        // Open combo window after light standing hits 1–2; reset after finisher / specials
        if (f.atkKind === "attack1" || f.atkKind === "attack2") {
          f.comboWindow = COMBO_WINDOW_FRAMES;
        } else {
          f.comboStep = 0;
          f.comboWindow = 0;
        }
        f.atkKind = null;
        f.smash = false;
        f.atkConnected = false;
      }
      if (f.comboWindow > 0) {
        f.comboWindow--;
        if (f.comboWindow <= 0) f.comboStep = 0;
      }

      // Stamina regen when not mid-swing (~20/sec → full in 5s)
      if (f.atkTimer <= 0 && f.stamina < STAMINA_MAX) {
        f.stamina = Math.min(STAMINA_MAX, f.stamina + STAMINA_REGEN_PER_SEC * SIM_DT);
      }

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
      // Root during heavy cast (3s) — facing stays locked
      if (p1.atkTimer > 0 && p1.atkKind === "heavy") return;
      const down = keys["ArrowDown"] || keys["s"] || keys["S"];
      p1.crouching = !!(p1.onGround && down && p1.atkTimer <= 0);
      const left = keys["ArrowLeft"] || keys["a"] || keys["A"];
      const right = keys["ArrowRight"] || keys["d"] || keys["D"];
      if (p1.crouching) {
        // Hold stance while crouching — still allow turn
        p1.running = false;
        p1.runDir = 0;
        if (left) p1.facing = -1;
        if (right) p1.facing = 1;
        return;
      }
      stopRunIfNeeded(!!left, !!right);
      // Run momentum persists in air (jump from run keeps run speed until land/cancel)
      const base = p1.onGround ? p1.moveSpd : p1.airSpd;
      const spd = p1.running ? p1.moveSpd * RUN_SPD_MULT : base;
      if (left) {
        p1.vx = -spd;
        p1.facing = -1;
      }
      if (right) {
        p1.vx = spd;
        p1.facing = 1;
      }
      if (!left && !right && p1.running) {
        p1.running = false;
        p1.runDir = 0;
      }
    }

    function controlAI() {
      const f = p2;
      if (f.hitstun > 0) return;
      if (f.atkTimer > 0 && f.atkKind === "heavy") return;
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
            const wantHeavy = target.damage > 80 && Math.random() < 0.28 && f.stamina >= STAMINA_COST_HEAVY;
            tryAttack(f, wantHeavy);
            aiState.cool = diff === "easy" ? 36 : diff === "hard" ? 14 : 24;
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

    function drawHeavyLaser(f) {
      if (f.atkKind !== "heavy" || f.atkTimer <= 0 || f.atkTimer > HEAVY_LASER_FRAMES) return;
      const set = f.isAI ? sprites.p2 : sprites.p1;
      const img = set.heavy_laser;
      if (!(img && img.complete && img.naturalWidth > 0)) return;
      const box = attackBox(f);
      // Origin at character front (chest), beam extends facing direction off-map
      const originX = f.facing > 0 ? f.x + f.w - 2 : f.x + 2;
      const originY = f.y + f.h * 0.42;
      const beamLen = HEAVY_REACH;
      const beamH = 56;
      ctx.save();
      ctx.globalCompositeOperation = "lighter";
      ctx.translate(originX, originY);
      ctx.scale(f.facing >= 0 ? 1 : -1, 1);
      // Soft pulse while laser is active
      const t = 1 - f.atkTimer / HEAVY_LASER_FRAMES;
      const pulse = 0.85 + 0.15 * Math.sin(t * Math.PI * 6);
      ctx.globalAlpha = 0.55 + 0.35 * pulse;
      ctx.drawImage(img, 0, -beamH / 2, beamLen, beamH);
      ctx.globalAlpha = 0.35 * pulse;
      ctx.drawImage(img, 0, -beamH * 0.7, beamLen, beamH * 1.4);
      ctx.restore();
      // Optional: thin debug-free hit feel — skip stroke for smash when laser art is up
      void box;
    }

    function drawCrouchFx(f) {
      // Separate VFX: only AFTER character frame 3 finishes, then alone for 1s
      if (f.atkKind !== "crouch_attack" || f.atkTimer <= 0) return;
      const dur = f.atkDuration || CROUCH_ATK_DURATION;
      const elapsed = Math.max(0, dur - f.atkTimer);
      if (elapsed < CROUCH_FX_START || elapsed >= CROUCH_FX_START + CROUCH_FX_DURATION) return;
      const set = f.isAI ? sprites.p2 : sprites.p1;
      const img = set.crouch_fx;
      if (!(img && img.complete && img.naturalWidth > 0)) return;
      const ahead = CROUCH_FX_AHEAD * f.w;
      const side = CROUCH_FX_SIDE;
      const cx = f.facing > 0 ? f.x + f.w + ahead : f.x - ahead;
      const feetY = f.y + f.h;
      const top = feetY - side * 0.85;
      const localT = (elapsed - CROUCH_FX_START) / CROUCH_FX_DURATION; // 0→1 over the 1s
      let alpha = 0.95;
      if (localT < 0.1) alpha = 0.3 + 0.65 * (localT / 0.1);
      else if (localT > 0.8) alpha = 0.95 * (1 - (localT - 0.8) / 0.2);
      const pulse = 0.92 + 0.08 * Math.sin(localT * Math.PI * 4);
      ctx.save();
      ctx.globalCompositeOperation = "lighter";
      ctx.globalAlpha = alpha * pulse;
      ctx.drawImage(img, cx - side / 2, top, side, side);
      ctx.globalAlpha = alpha * 0.35 * pulse;
      ctx.drawImage(img, cx - side * 0.55, top - side * 0.05, side * 1.1, side * 1.1);
      ctx.restore();
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
      const isRunKey = key === "run";
      let drawW = drawH;
      const ok = !!(img && img.complete && img.naturalWidth > 0);
      const isWalkStrip = key === "walk" && ok && img.naturalWidth >= img.naturalHeight * 2;
      const isRunStrip = isRunKey && ok && img.naturalWidth >= img.naturalHeight * 2;
      // Single-frame run fallback still gets a light bob; multi-frame strip does not
      const runBob = isRunKey && !isRunStrip ? Math.sin(tick / 3.5) * 3.5 : 0;
      const isHeavyStrip =
        key === "heavy" && ok && img.naturalWidth >= img.naturalHeight * 2 && f.atkTimer > 0;
      const isLightStrip =
        (key === "attack1" ||
          key === "attack2" ||
          key === "attack3" ||
          key === "crouch_attack" ||
          key === "aerial_attack") &&
        ok &&
        f.atkTimer > 0; // always 3-frame L→R strips — crop by frameIdx, never draw whole sheet
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
        } else if (isRunStrip) {
          srcW = img.naturalWidth / RUN_FRAMES;
          srcH = img.naturalHeight;
          srcX = (Math.floor(tick / RUN_FRAME_TICKS) % RUN_FRAMES) * srcW;
          srcY = 0;
          drawW = (srcW / srcH) * drawH;
        } else if (isHeavyStrip) {
          srcW = img.naturalWidth / HEAVY_FRAMES;
          srcH = img.naturalHeight;
          const elapsed = Math.max(0, HEAVY_ATK_FRAMES - f.atkTimer);
          const frameIdx = Math.min(
            HEAVY_FRAMES - 1,
            Math.floor(elapsed / (HEAVY_ATK_FRAMES / HEAVY_FRAMES))
          );
          srcX = frameIdx * srcW;
          srcY = 0;
          // Laser frame is wide — keep aspect; slightly larger draw for beam readability
          drawW = (srcW / srcH) * drawH;
        } else if (isLightStrip) {
          const stripFrames = key === "crouch_attack" ? CROUCH_ATK_FRAMES : ATTACK_FRAMES;
          srcW = img.naturalWidth / stripFrames;
          srcH = img.naturalHeight;
          const dur = f.atkDuration || LIGHT_ATK_DURATION;
          const elapsed = Math.max(0, dur - f.atkTimer);
          let frameIdx;
          if (key === "crouch_attack") {
            // Frames 1–3 at CROUCH_CHAR_FRAME_TICKS; frame 4 holds through post-frame3 VFX
            frameIdx = Math.min(
              CROUCH_ATK_FRAMES - 1,
              Math.floor(elapsed / CROUCH_CHAR_FRAME_TICKS)
            );
          } else {
            frameIdx = Math.min(
              stripFrames - 1,
              Math.floor(elapsed / (dur / stripFrames))
            );
          }
          srcX = frameIdx * srcW;
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
        const dy = -drawH + runBob; // bob only for single-frame run fallback
        if (isWalkStrip || isRunStrip || isHeavyStrip || isLightStrip) {
          ctx.drawImage(img, srcX, srcY, srcW, srcH, -drawW / 2, dy, drawW, drawH);
        } else {
          ctx.drawImage(img, -drawW / 2, dy, drawW, drawH);
        }
        ctx.restore();
      } else {
        // brief fallback while loading / if asset missing — kick another preload
        if (!spritesReady) ensureSprites();
        ctx.fillStyle = f.color;
        roundRect(f.x, f.y, f.w, f.h, 6);
        ctx.fill();
      }

      // Heavy laser beam from character front → off-map (last HEAVY_LASER_FRAMES)
      drawHeavyLaser(f);
      // Crouch purple energy VFX ~2 char widths ahead (separate overlay)
      drawCrouchFx(f);

      if (f.damage > 60) {
        ctx.strokeStyle = `rgba(251,191,36,${Math.min(0.8, f.damage / 200)})`;
        ctx.lineWidth = 2;
        ctx.strokeRect(f.x - 4, f.y - 8, f.w + 8, f.h + 10);
      }
      // subtle attack arc (skip smash — laser art covers it)
      const box = attackBox(f);
      if (box && box.smash) {
        // laser visual only
      } else if (box && !(img && img.complete)) {
        ctx.fillStyle = "rgba(255,255,255,.4)";
        ctx.fillRect(box.x, box.y, box.w, box.h);
      } else if (box && box.kind === "crouch_attack") {
        // VFX art covers the square — skip debug stroke
      } else if (box) {
        ctx.strokeStyle = "rgba(196,181,253,.35)";
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
      updateStaminaHud();
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
