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
        const v = s[k] ?? 50;
        const pct = Math.round(((v - 30) / 69) * 100);
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
      return `<p class="muted">暫無持倉——屬性接近基礎值。買入成長股↑攻擊、銀行／公用↑防禦、ETF／高流動↑速度。</p>`;
    }
    const aff = { atk: "攻擊", def: "防禦", spd: "速度" };
    return `<table><thead><tr><th class="l">代號</th><th>主屬性</th><th>市值比重</th></tr></thead><tbody>${rows
      .map(
        (r) =>
          `<tr><td class="l">${r.symbol}</td><td>${aff[r.affinity] || r.affinity}</td><td>${(r.weight * 100).toFixed(1)}%</td></tr>`
      )
      .join("")}</tbody></table>`;
  }

  let myStats = null;
  let matchCtx = null; // {mode, player, opponent, difficulty?}

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

  function showArena(ctx) {
    matchCtx = ctx;
    $("#lobby").classList.add("hidden");
    $("#arena").classList.remove("hidden");
    $("#resultOverlay").classList.add("hidden");
    $("#p1Name").textContent = ctx.player.display_name || ctx.player.username;
    $("#p2Name").textContent = ctx.opponent.display_name || ctx.opponent.username;
    $("#p1Mini").textContent = `攻${ctx.player.atk} 防${ctx.player.def} 速${ctx.player.spd}`;
    $("#p2Mini").textContent = `攻${ctx.opponent.atk} 防${ctx.opponent.def} 速${ctx.opponent.spd}`;
    Game.start(ctx);
  }

  function showLobby() {
    Game.stop();
    $("#arena").classList.add("hidden");
    $("#lobby").classList.remove("hidden");
    loadLobby().catch((e) => toast(e.message));
  }

  $("#btnBack").onclick = showLobby;
  $("#btnToLobby").onclick = showLobby;

  $("#btnAI").onclick = async () => {
    try {
      const diff = $("#aiDiff").value;
      const opp = await api(`/api/fighter/ai?difficulty=${encodeURIComponent(diff)}&mirror=1`);
      showArena({ mode: "ai", player: myStats, opponent: opp, difficulty: diff });
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
      showArena({ mode: "classmate", player: data.player, opponent: data.opponent });
    } catch (e) {
      msg.textContent = e.message;
      msg.classList.add("err");
    }
  };

  $("#btnRematch").onclick = () => {
    if (!matchCtx) return;
    $("#resultOverlay").classList.add("hidden");
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
    const GROUND_Y = 420;
    const PLATFORM = { x: 120, y: GROUND_Y, w: 720, h: 28 };
    const BLAST = { left: -80, right: W + 80, top: -120, bottom: H + 100 };

    let running = false;
    let raf = 0;
    let keys = {};
    let p1, p2, stocks, roundLock, kosToWin;
    let matchMeta = null;
    let particles = [];
    let aiState = { cool: 0, jumpCool: 0 };

    function fighter(stats, x, facing, color, isAI) {
      const atk = stats.atk || 50,
        def = stats.def || 50,
        spd = stats.spd || 50;
      return {
        stats,
        x,
        y: GROUND_Y - 48,
        vx: 0,
        vy: 0,
        w: 36,
        h: 48,
        facing,
        color,
        damage: 0,
        onGround: true,
        jumps: 2,
        atkTimer: 0,
        atkCool: 0,
        hitstun: 0,
        invuln: 0,
        smash: false,
        isAI: !!isAI,
        // derived
        moveSpd: 3.2 + (spd - 50) * 0.06,
        airSpd: 3.0 + (spd - 50) * 0.05,
        jumpV: -11.2 - (spd - 50) * 0.04,
        weight: 1 + (def - 50) * 0.008,
        knockDealt: 0.85 + (atk - 50) * 0.012,
        knockTaken: 1.15 - (def - 50) * 0.01,
      };
    }

    function resetRoundPositions() {
      p1.x = 280;
      p1.y = GROUND_Y - 48;
      p1.vx = p1.vy = 0;
      p1.damage = 0;
      p1.facing = 1;
      p1.onGround = true;
      p1.jumps = 2;
      p1.hitstun = 0;
      p1.invuln = 45;
      p1.atkTimer = p1.atkCool = 0;
      p2.x = 640;
      p2.y = GROUND_Y - 48;
      p2.vx = p2.vy = 0;
      p2.damage = 0;
      p2.facing = -1;
      p2.onGround = true;
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
      const dot = (n) => "●".repeat(n) + "○".repeat(Math.max(0, kosToWin - n));
      // stocks remaining
      $("#p1Stocks").textContent = "●".repeat(stocks.p1) + "○".repeat(Math.max(0, kosToWin - stocks.p1));
      $("#p2Stocks").textContent = "●".repeat(stocks.p2) + "○".repeat(Math.max(0, kosToWin - stocks.p2));
      // color by damage
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
      kosToWin = 2;
      stocks = { p1: kosToWin, p2: kosToWin };
      p1 = fighter(meta.player, 280, 1, "#3b82f6", false);
      p2 = fighter(meta.opponent, 640, -1, "#ea3943", true);
      roundLock = 90; // countdown frames
      $("#roundMsg").textContent = "準備…";
      $("#resultOverlay").classList.add("hidden");
      running = true;
      keys = {};
      aiState = { cool: 0, jumpCool: 0 };
      resetRoundPositions();
      loop();
    }

    function stop() {
      running = false;
      if (raf) cancelAnimationFrame(raf);
      raf = 0;
    }

    function onKey(e, down) {
      const k = e.key;
      if (["ArrowLeft", "ArrowRight", "ArrowUp", "ArrowDown", " ", "z", "Z", "j", "J", "w", "W", "a", "A", "d", "D", "s", "S"].includes(k)) {
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

    function tryJump(f) {
      if (f.hitstun > 0) return;
      if (f.jumps > 0) {
        f.vy = f.jumpV * (f.jumps === 2 ? 1 : 0.85);
        f.onGround = false;
        f.jumps--;
      }
    }

    function tryAttack(f, smash) {
      if (f.hitstun > 0 || f.atkCool > 0 || f.atkTimer > 0) return;
      f.smash = !!smash;
      f.atkTimer = smash ? 18 : 12;
      f.atkCool = smash ? 28 : 18;
    }

    function attackBox(f) {
      if (f.atkTimer <= 0) return null;
      const active = f.smash ? f.atkTimer <= 12 && f.atkTimer >= 6 : f.atkTimer <= 8 && f.atkTimer >= 3;
      if (!active) return null;
      const reach = f.smash ? 52 : 40;
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
        const base = box.smash ? 14 : 8;
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

    function physics(f) {
      if (f.invuln > 0) f.invuln--;
      if (f.hitstun > 0) f.hitstun--;
      if (f.atkCool > 0) f.atkCool--;
      if (f.atkTimer > 0) f.atkTimer--;

      const grav = 0.55;
      f.vy += grav;
      f.x += f.vx;
      f.y += f.vy;
      f.vx *= f.onGround ? 0.75 : 0.92;

      // platform
      const feet = f.y + f.h;
      if (
        f.vy >= 0 &&
        feet >= PLATFORM.y &&
        feet <= PLATFORM.y + 18 &&
        f.x + f.w > PLATFORM.x + 8 &&
        f.x < PLATFORM.x + PLATFORM.w - 8
      ) {
        f.y = PLATFORM.y - f.h;
        f.vy = 0;
        f.onGround = true;
        f.jumps = 2;
      } else if (feet > PLATFORM.y + 4) {
        f.onGround = false;
      }
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
      // recover toward stage
      if (f.x < PLATFORM.x - 20 || f.x > PLATFORM.x + PLATFORM.w + 20 || f.y > GROUND_Y + 40) {
        const mid = PLATFORM.x + PLATFORM.w / 2;
        f.vx = Math.sign(mid - f.x) * f.airSpd * 1.1;
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
      $("#resultDetail").textContent = `比分 ${pk}–${ok}　（先至 ${kosToWin} KO）`;
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

    function draw() {
      // sky
      const g = ctx.createLinearGradient(0, 0, 0, H);
      g.addColorStop(0, "#0b1a33");
      g.addColorStop(1, "#132844");
      ctx.fillStyle = g;
      ctx.fillRect(0, 0, W, H);

      // stars
      ctx.fillStyle = "rgba(255,255,255,.35)";
      for (let i = 0; i < 40; i++) {
        const sx = (i * 97) % W,
          sy = (i * 53) % 280;
        ctx.fillRect(sx, sy, 2, 2);
      }

      // blast zone hints
      ctx.strokeStyle = "rgba(234,57,67,.25)";
      ctx.setLineDash([6, 6]);
      ctx.strokeRect(40, 40, W - 80, H - 80);
      ctx.setLineDash([]);

      // platform
      ctx.fillStyle = "#334155";
      roundRect(PLATFORM.x, PLATFORM.y, PLATFORM.w, PLATFORM.h, 8);
      ctx.fill();
      ctx.fillStyle = "#16c784";
      ctx.fillRect(PLATFORM.x + 4, PLATFORM.y, PLATFORM.w - 8, 5);
      // ticker flair
      ctx.fillStyle = "rgba(230,237,243,.5)";
      ctx.font = "12px monospace";
      ctx.fillText("0700  ▲   AAPL  ▲   0005  ▼   SPY  ■", PLATFORM.x + 24, PLATFORM.y + 20);

      drawFighter(p1);
      drawFighter(p2);

      // particles
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
      // body
      ctx.fillStyle = f.color;
      roundRect(f.x, f.y, f.w, f.h, 6);
      ctx.fill();
      // face / direction
      ctx.fillStyle = "#fff";
      const ey = f.y + 14;
      const ex = f.facing > 0 ? f.x + 22 : f.x + 6;
      ctx.fillRect(ex, ey, 6, 6);
      // damage aura
      if (f.damage > 60) {
        ctx.strokeStyle = `rgba(251,191,36,${Math.min(0.8, f.damage / 200)})`;
        ctx.lineWidth = 2;
        ctx.strokeRect(f.x - 2, f.y - 2, f.w + 4, f.h + 4);
      }
      // attack flash
      const box = attackBox(f);
      if (box) {
        ctx.fillStyle = box.smash ? "rgba(251,191,36,.55)" : "rgba(255,255,255,.4)";
        ctx.fillRect(box.x, box.y, box.w, box.h);
      }
      // name tag
      ctx.fillStyle = "rgba(0,0,0,.45)";
      ctx.font = "11px sans-serif";
      const label = f.isAI ? "AI" : "YOU";
      ctx.fillText(label, f.x + 4, f.y - 6);
    }

    function loop() {
      if (!running) return;
      raf = requestAnimationFrame(loop);
      if (roundLock > 0) {
        roundLock--;
        if (roundLock === 30) $("#roundMsg").textContent = "開始！";
        if (roundLock === 0) $("#roundMsg").textContent = "擊飛出界！";
        draw();
        return;
      }
      controlP1();
      controlAI();
      physics(p1);
      physics(p2);
      hit(p1, p2);
      hit(p2, p1);
      for (const pt of particles) {
        pt.x += pt.vx;
        pt.y += pt.vy;
        pt.life--;
      }
      particles = particles.filter((p) => p.life > 0);
      if (checkKO(p1, "p1") || checkKO(p2, "p2")) {
        draw();
        return;
      }
      draw();
    }

    return { start, stop };
  })();

  loadLobby().catch((e) => toast(e.message));
})();
