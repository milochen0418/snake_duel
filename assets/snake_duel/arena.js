// Snake Duel's arena. The server sends the board once a step, as JSON in the canvas's
// data-frame; this draws it, gliding the snakes from one step to the next, with where each AI
// snake is heading, the food and a little burst when something is eaten or someone crashes. It
// also turns swipes on the board and the on-screen pad into arrow keys (the page's key listener
// sends those to the server), and keeps the arrow keys from scrolling the page while the arena is
// shown.
(() => {
  "use strict";

  // Each snake's colours, by its id (the page uses the same ones: snake_duel/views.py).
  const COLORS = {
    you: { light: "#fde68a", body: "#f59e0b", dark: "#92400e" },
    ai1: { light: "#a5f3fc", body: "#22d3ee", dark: "#155e75" },
    ai2: { light: "#ddd6fe", body: "#a78bfa", dark: "#5b21b6" },
    ai3: { light: "#d9f99d", body: "#a3e635", dark: "#3f6212" },
    ai4: { light: "#fbcfe8", body: "#f472b6", dark: "#9d174d" },
  };
  const ARROWS = new Set(["ArrowUp", "ArrowDown", "ArrowLeft", "ArrowRight"]);
  const GLIDE = 0.55; // of a step: how long a snake takes to slide into its next cell
  const GOLD_LASTS = 8; // seconds, as the server keeps it

  let canvas = null;
  let ctx = null;
  let raw = "";
  let cur = null;
  let prev = null; // the step before, by snake id
  let at = 0;
  let effects = [];
  let cssW = 0;
  let cssH = 0;
  let dpr = 1;

  const lerp = (a, b, t) => a + (b - a) * t;
  const near = (a, b) => Math.abs(a[0] - b[0]) + Math.abs(a[1] - b[1]) === 1;
  const colors = (id) => COLORS[id] || COLORS.ai1;
  const alpha = (hex, a) => {
    const n = parseInt(hex.slice(1), 16);
    return `rgba(${n >> 16}, ${(n >> 8) & 255}, ${n & 255}, ${a})`;
  };

  function attach() {
    const el = document.getElementById("arena");
    if (el !== canvas) {
      canvas = el;
      ctx = el ? el.getContext("2d") : null;
      raw = "";
      cur = prev = null;
      effects = [];
    }
    return !!canvas;
  }

  function take(text) {
    if (!text || text === raw) return;
    raw = text;
    let next;
    try {
      next = JSON.parse(text);
    } catch (e) {
      return;
    }
    // Glide only from the step just before (a new match starts again at 0).
    prev = cur && next.t === cur.t + 1 ? Object.fromEntries(cur.snakes.map((s) => [s.id, s])) : null;
    cur = next;
    at = performance.now();
    for (const fx of next.fx || []) burst(fx);
  }

  function fit() {
    const w = canvas.clientWidth;
    const h = Math.round((w * cur.h) / cur.w);
    const ratio = window.devicePixelRatio || 1;
    if (w !== cssW || h !== cssH || ratio !== dpr) {
      cssW = w;
      cssH = h;
      dpr = ratio;
      canvas.style.height = h + "px";
      canvas.width = Math.round(w * dpr);
      canvas.height = Math.round(h * dpr);
    }
    return w / cur.w;
  }

  // ------------------------------------------------------------ effects

  function burst(fx) {
    const [x, y] = fx.cell;
    const now = performance.now();
    if (fx.kind === "eat" || fx.kind === "crash") {
      const color = fx.kind === "crash" ? "#fb7185" : fx.food === "gold" ? "#fde047" : colors(fx.who).body;
      const parts = [];
      for (let i = 0; i < 14; i++) {
        const a = (Math.PI * 2 * i) / 14 + Math.random() * 0.4;
        const v = 1.2 + Math.random() * 1.6;
        parts.push({ vx: Math.cos(a) * v, vy: Math.sin(a) * v });
      }
      const text = fx.kind === "crash" ? "−3" : "+" + fx.points;
      effects.push({ kind: "burst", x, y, born: now, life: 700, color, parts, text, textColor: fx.kind === "crash" ? "#fda4af" : color });
    } else if (fx.kind === "back") {
      effects.push({ kind: "ring", x, y, born: now, life: 900, color: colors(fx.who).light });
    } else if (fx.kind === "gold") {
      effects.push({ kind: "ring", x, y, born: now, life: 900, color: "#fde047" });
    } else if (fx.kind === "gone") {
      effects.push({ kind: "ring", x, y, born: now, life: 500, color: "#64748b" });
    }
  }

  function drawEffects(cell, now) {
    effects = effects.filter((e) => now - e.born < e.life);
    for (const e of effects) {
      const k = (now - e.born) / e.life;
      const cx = (e.x + 0.5) * cell;
      const cy = (e.y + 0.5) * cell;
      ctx.globalAlpha = 1 - k;
      if (e.kind === "burst") {
        ctx.fillStyle = e.color;
        for (const p of e.parts) {
          ctx.beginPath();
          ctx.arc(cx + p.vx * k * cell, cy + p.vy * k * cell, cell * 0.09 * (1 - k * 0.5), 0, Math.PI * 2);
          ctx.fill();
        }
        ctx.font = `bold ${Math.round(cell * 0.62)}px ui-sans-serif, system-ui, sans-serif`;
        ctx.textAlign = "center";
        ctx.textBaseline = "middle";
        ctx.fillStyle = e.textColor;
        ctx.fillText(e.text, cx, cy - k * cell * 1.3 - cell * 0.4);
      } else {
        ctx.strokeStyle = e.color;
        ctx.lineWidth = Math.max(1.5, cell * 0.08);
        ctx.beginPath();
        ctx.arc(cx, cy, cell * (0.4 + k * 1.2), 0, Math.PI * 2);
        ctx.stroke();
      }
    }
    ctx.globalAlpha = 1;
  }

  // ------------------------------------------------------------ the board

  function drawGround(cell) {
    ctx.fillStyle = "#0b1220";
    ctx.fillRect(0, 0, cssW, cssH);
    ctx.fillStyle = "rgba(148, 163, 184, 0.05)";
    for (let y = 0; y < cur.h; y++) {
      for (let x = y % 2; x < cur.w; x += 2) ctx.fillRect(x * cell, y * cell, cell, cell);
    }
    ctx.strokeStyle = "rgba(148, 163, 184, 0.35)";
    ctx.lineWidth = 2;
    ctx.strokeRect(1, 1, cssW - 2, cssH - 2);
  }

  function drawAims(cell, now) {
    for (const { id, aim, way } of cur.aims || []) {
      const c = colors(id);
      ctx.fillStyle = alpha(c.light, 0.35);
      for (const [x, y] of way || []) {
        ctx.beginPath();
        ctx.arc((x + 0.5) * cell, (y + 0.5) * cell, Math.max(1.5, cell * 0.08), 0, Math.PI * 2);
        ctx.fill();
      }
      ctx.save();
      ctx.strokeStyle = alpha(c.light, 0.9);
      ctx.lineWidth = Math.max(1.5, cell * 0.07);
      ctx.setLineDash([cell * 0.18, cell * 0.14]);
      ctx.lineDashOffset = -now / 60;
      ctx.beginPath();
      ctx.arc((aim[0] + 0.5) * cell, (aim[1] + 0.5) * cell, cell * 0.62, 0, Math.PI * 2);
      ctx.stroke();
      ctx.restore();
    }
  }

  function star(cx, cy, r) {
    ctx.beginPath();
    for (let i = 0; i < 10; i++) {
      const a = -Math.PI / 2 + (Math.PI * i) / 5;
      const rr = i % 2 ? r * 0.45 : r;
      ctx.lineTo(cx + Math.cos(a) * rr, cy + Math.sin(a) * rr);
    }
    ctx.closePath();
  }

  function drawFood(cell, now) {
    const since = (now - at) / 1000;
    for (const f of cur.food) {
      const cx = (f.x + 0.5) * cell;
      const cy = (f.y + 0.5) * cell;
      if (f.k === "gold") {
        const ttl = Math.max(0, f.ttl - since);
        if (ttl < 2.5 && Math.floor(now / 160) % 2) continue; // blinks before it goes
        const pulse = 1 + 0.08 * Math.sin(now / 140);
        ctx.save();
        ctx.shadowColor = "#facc15";
        ctx.shadowBlur = cell * 0.6;
        ctx.fillStyle = "#fde047";
        star(cx, cy, cell * 0.44 * pulse);
        ctx.fill();
        ctx.restore();
        ctx.strokeStyle = "rgba(253, 224, 71, 0.7)";
        ctx.lineWidth = Math.max(1.5, cell * 0.06);
        ctx.beginPath();
        ctx.arc(cx, cy, cell * 0.56, -Math.PI / 2, -Math.PI / 2 + (Math.PI * 2 * ttl) / GOLD_LASTS);
        ctx.stroke();
      } else {
        const r = cell * 0.34;
        const g = ctx.createRadialGradient(cx - r * 0.35, cy - r * 0.35, r * 0.1, cx, cy, r);
        g.addColorStop(0, "#fda4af");
        g.addColorStop(0.45, "#f43f5e");
        g.addColorStop(1, "#9f1239");
        ctx.fillStyle = g;
        ctx.beginPath();
        ctx.arc(cx, cy + cell * 0.04, r, 0, Math.PI * 2);
        ctx.fill();
        ctx.fillStyle = "#4ade80";
        ctx.beginPath();
        ctx.ellipse(cx + cell * 0.1, cy - r - cell * 0.02, cell * 0.12, cell * 0.06, -0.6, 0, Math.PI * 2);
        ctx.fill();
      }
      // the letter the AI calls it by
      ctx.font = `600 ${Math.max(9, Math.round(cell * 0.36))}px ui-monospace, monospace`;
      ctx.textAlign = "right";
      ctx.textBaseline = "bottom";
      ctx.fillStyle = "rgba(226, 232, 240, 0.85)";
      ctx.fillText(f.l, (f.x + 1) * cell - cell * 0.04, (f.y + 1) * cell + cell * 0.02);
    }
  }

  function points(s, ps, t) {
    const pts = s.body.map((c) => [c[0] + 0.5, c[1] + 0.5]);
    if (ps && ps.body.length && t < 1 && near(ps.body[0], s.body[0])) {
      const ph = ps.body[0];
      const h = s.body[0];
      pts[0] = [lerp(ph[0], h[0], t) + 0.5, lerp(ph[1], h[1], t) + 0.5];
      const pt = ps.body[ps.body.length - 1];
      const ct = s.body[s.body.length - 1];
      if (near(pt, ct)) pts.push([lerp(pt[0], ct[0], t) + 0.5, lerp(pt[1], ct[1], t) + 0.5]);
    }
    return pts;
  }

  function drawSnake(s, cell, t) {
    if (!s.body.length) return;
    const c = colors(s.id);
    const pts = points(s, prev && prev[s.id], t);
    const line = (width, color) => {
      ctx.strokeStyle = color;
      ctx.lineWidth = width;
      ctx.lineCap = "round";
      ctx.lineJoin = "round";
      ctx.beginPath();
      pts.forEach(([x, y], i) => (i ? ctx.lineTo(x * cell, y * cell) : ctx.moveTo(x * cell, y * cell)));
      if (pts.length === 1) ctx.lineTo(pts[0][0] * cell + 0.01, pts[0][1] * cell);
      ctx.stroke();
    };
    line(cell * 0.78, c.dark);
    line(cell * 0.62, c.body);
    line(cell * 0.16, c.light + "88");
    // the head, looking the way it goes
    const [hx, hy] = pts[0];
    const [dx, dy] = { up: [0, -1], down: [0, 1], left: [-1, 0], right: [1, 0] }[s.dir] || [1, 0];
    ctx.fillStyle = c.body;
    ctx.strokeStyle = c.dark;
    ctx.lineWidth = Math.max(1, cell * 0.06);
    ctx.beginPath();
    ctx.arc(hx * cell, hy * cell, cell * 0.43, 0, Math.PI * 2);
    ctx.fill();
    ctx.stroke();
    for (const side of [-1, 1]) {
      const ex = (hx + dx * 0.16 - dy * side * 0.2) * cell;
      const ey = (hy + dy * 0.16 + dx * side * 0.2) * cell;
      ctx.fillStyle = "#f8fafc";
      ctx.beginPath();
      ctx.arc(ex, ey, cell * 0.12, 0, Math.PI * 2);
      ctx.fill();
      ctx.fillStyle = "#0f172a";
      ctx.beginPath();
      ctx.arc(ex + dx * cell * 0.05, ey + dy * cell * 0.05, cell * 0.06, 0, Math.PI * 2);
      ctx.fill();
    }
  }

  function drawNames(cell) {
    // Before the start: which snake is whose.
    for (const s of cur.snakes) {
      if (!s.body.length) continue;
      const [x, y] = s.body[0];
      ctx.font = `bold ${Math.round(cell * 0.5)}px ui-sans-serif, system-ui, sans-serif`;
      ctx.textAlign = "center";
      ctx.textBaseline = "bottom";
      ctx.fillStyle = colors(s.id).light;
      ctx.fillText(s.n, (x + 0.5) * cell, (y - 0.15) * cell);
    }
  }

  function draw(now) {
    take(canvas.dataset.frame || "");
    if (!cur) return;
    const cell = fit();
    const t = prev ? Math.min(1, (now - at) / (cur.ms * GLIDE)) : 1;
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    drawGround(cell);
    drawAims(cell, now);
    drawFood(cell, now);
    // the person's snake on top
    for (const s of cur.snakes) if (s.id !== "you") drawSnake(s, cell, t);
    for (const s of cur.snakes) if (s.id === "you") drawSnake(s, cell, t);
    if (["warmup", "countdown"].includes(canvas.dataset.phase)) drawNames(cell);
    drawEffects(cell, now);
  }

  function loop(now) {
    requestAnimationFrame(loop);
    if (attach() && ctx) draw(now);
  }
  requestAnimationFrame(loop);

  // ------------------------------------------------------------ input

  function press(key) {
    window.dispatchEvent(new KeyboardEvent("keydown", { key, bubbles: true }));
  }

  window.addEventListener(
    "keydown",
    (e) => {
      if (!ARROWS.has(e.key) || !document.getElementById("arena")) return;
      const t = e.target;
      if (t && t.closest && t.closest("input, textarea, select, [contenteditable=true]")) return;
      e.preventDefault();
    },
    { capture: true },
  );

  document.addEventListener("pointerdown", (e) => {
    const button = e.target.closest && e.target.closest("[data-key]");
    if (!button) return;
    e.preventDefault();
    press(button.dataset.key);
  });

  let touch = null;
  document.addEventListener(
    "touchstart",
    (e) => {
      touch = e.target === canvas && e.touches.length === 1 ? { x: e.touches[0].clientX, y: e.touches[0].clientY } : null;
    },
    { passive: true },
  );
  document.addEventListener(
    "touchmove",
    (e) => {
      if (!touch || e.touches.length !== 1) return;
      const dx = e.touches[0].clientX - touch.x;
      const dy = e.touches[0].clientY - touch.y;
      if (Math.max(Math.abs(dx), Math.abs(dy)) < 22) return;
      press(Math.abs(dx) > Math.abs(dy) ? (dx > 0 ? "ArrowRight" : "ArrowLeft") : dy > 0 ? "ArrowDown" : "ArrowUp");
      // a new swipe can start from here without lifting the finger
      touch = { x: e.touches[0].clientX, y: e.touches[0].clientY };
    },
    { passive: true },
  );
  document.addEventListener("touchend", () => (touch = null), { passive: true });
})();
