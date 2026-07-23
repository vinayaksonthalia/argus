/* sketch.js — tiny hand-drawn rendering engine for the explainer illustrations.
   No external deps. Deterministic (seeded) wobble so renders are reproducible. */
(function () {
  const NS = "http://www.w3.org/2000/svg";

  function mulberry32(a) {
    return function () {
      a |= 0; a = (a + 0x6D2B79F5) | 0;
      let t = Math.imul(a ^ (a >>> 15), 1 | a);
      t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t;
      return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
    };
  }
  function hashStr(s) {
    let h = 2166136261;
    for (let i = 0; i < s.length; i++) { h ^= s.charCodeAt(i); h = Math.imul(h, 16777619); }
    return h >>> 0;
  }

  // Smooth jittered path through sampled points (quadratic through midpoints).
  function jitterPath(pts, rand, jit) {
    const off = pts.map(p => [p[0] + (rand() - 0.5) * 2 * jit, p[1] + (rand() - 0.5) * 2 * jit]);
    let d = `M ${off[0][0].toFixed(1)} ${off[0][1].toFixed(1)}`;
    for (let i = 1; i < off.length - 1; i++) {
      const mx = (off[i][0] + off[i + 1][0]) / 2, my = (off[i][1] + off[i + 1][1]) / 2;
      d += ` Q ${off[i][0].toFixed(1)} ${off[i][1].toFixed(1)} ${mx.toFixed(1)} ${my.toFixed(1)}`;
    }
    const L = off[off.length - 1];
    d += ` L ${L[0].toFixed(1)} ${L[1].toFixed(1)}`;
    return d;
  }

  function sampleRoundRect(x, y, w, h, r, step) {
    const pts = [];
    function line(x1, y1, x2, y2) {
      const len = Math.hypot(x2 - x1, y2 - y1);
      const n = Math.max(2, Math.round(len / step));
      for (let i = 0; i < n; i++) { const t = i / n; pts.push([x1 + (x2 - x1) * t, y1 + (y2 - y1) * t]); }
    }
    function arc(cx, cy, a0, a1) {
      const n = 5;
      for (let i = 0; i < n; i++) { const t = a0 + (a1 - a0) * (i / n); pts.push([cx + r * Math.cos(t), cy + r * Math.sin(t)]); }
    }
    line(x + r, y, x + w - r, y); arc(x + w - r, y + r, -Math.PI / 2, 0);
    line(x + w, y + r, x + w, y + h - r); arc(x + w - r, y + h - r, 0, Math.PI / 2);
    line(x + w - r, y + h, x + r, y + h); arc(x + r, y + h - r, Math.PI / 2, Math.PI);
    line(x, y + h - r, x, y + r); arc(x + r, y + r, Math.PI, 1.5 * Math.PI);
    pts.push([pts[0][0], pts[0][1]], [pts[1][0], pts[1][1]]);
    return pts;
  }

  function sampleCircle(cx, cy, r, step) {
    const n = Math.max(10, Math.round((2 * Math.PI * r) / step));
    const pts = [];
    for (let i = 0; i <= n + 1; i++) {
      const t = (i / n) * 2 * Math.PI - Math.PI / 2;
      pts.push([cx + r * Math.cos(t), cy + r * Math.sin(t)]);
    }
    return pts;
  }

  function mkPath(svg, d, opts) {
    const p = document.createElementNS(NS, "path");
    p.setAttribute("d", d);
    p.setAttribute("fill", opts.fill || "none");
    p.setAttribute("stroke", opts.color || "var(--ink)");
    p.setAttribute("stroke-width", opts.width || 2.4);
    p.setAttribute("stroke-linecap", "round");
    p.setAttribute("stroke-linejoin", "round");
    if (opts.dash) p.setAttribute("stroke-dasharray", opts.dash);
    if (opts.opacity) p.setAttribute("opacity", opts.opacity);
    svg.appendChild(p);
    return p;
  }

  function overlay() {
    let svg = document.getElementById("sk-overlay");
    if (!svg) {
      svg = document.createElementNS(NS, "svg");
      svg.id = "sk-overlay";
      svg.setAttribute("width", "1600"); svg.setAttribute("height", "840");
      svg.style.cssText = "position:absolute;inset:0;pointer-events:none;overflow:visible;z-index:1;";
      document.body.appendChild(svg);
    }
    return svg;
  }

  // Draw a double-stroke wobbly border INSIDE an element (so it rotates with it).
  function boxBorder(el) {
    const w = el.offsetWidth, h = el.offsetHeight;
    const seed = hashStr(el.id || el.textContent.slice(0, 24) || "box") + (parseInt(el.dataset.seed || "0", 10));
    const color = el.classList.contains("red") ? "var(--red)" : "var(--ink)";
    const wd = parseFloat(el.dataset.stroke || (el.classList.contains("thick") ? 3.4 : 2.4));
    const r = parseFloat(el.dataset.radius || 14);
    const svg = document.createElementNS(NS, "svg");
    svg.setAttribute("width", w); svg.setAttribute("height", h);
    svg.style.cssText = "position:absolute;inset:0;overflow:visible;pointer-events:none;";
    const m = 3; // inset margin
    const r1 = mulberry32(seed), r2 = mulberry32(seed + 77);
    mkPath(svg, jitterPath(sampleRoundRect(m, m, w - 2 * m, h - 2 * m, r, 16), r1, 1.6), { color, width: wd });
    mkPath(svg, jitterPath(sampleRoundRect(m + 1.5, m + 1, w - 2 * m - 2, h - 2 * m - 2, r, 22), r2, 2.2), { color, width: wd * 0.55, opacity: 0.75 });
    el.style.position = el.style.position || "absolute";
    el.insertBefore(svg, el.firstChild);
  }

  function anchorPoint(el, side, offset) {
    const b = el.getBoundingClientRect();
    const o = offset || 0;
    switch (side) {
      case "left": return [b.left - 4, b.top + b.height / 2 + o];
      case "right": return [b.right + 4, b.top + b.height / 2 + o];
      case "top": return [b.left + b.width / 2 + o, b.top - 4];
      case "bottom": return [b.left + b.width / 2 + o, b.bottom + 4];
      case "topleft": return [b.left + b.width * 0.22 + o, b.top - 4];
      case "topright": return [b.left + b.width * 0.78 + o, b.top - 4];
      case "bottomleft": return [b.left + b.width * 0.22 + o, b.bottom + 4];
      case "bottomright": return [b.left + b.width * 0.78 + o, b.bottom + 4];
    }
  }

  let arrowSeed = 5;
  function arrow(x1, y1, x2, y2, opts) {
    opts = opts || {};
    const svg = overlay();
    const rand = mulberry32(opts.seed || (arrowSeed += 13));
    const dx = x2 - x1, dy = y2 - y1, len = Math.hypot(dx, dy) || 1;
    const nx = -dy / len, ny = dx / len;
    const bow = opts.curve || 0;
    const cx = (x1 + x2) / 2 + nx * bow, cy = (y1 + y2) / 2 + ny * bow;
    const n = Math.max(8, Math.round(len / 20));
    const pts = [];
    for (let i = 0; i <= n; i++) {
      const t = i / n, a = 1 - t;
      pts.push([a * a * x1 + 2 * a * t * cx + t * t * x2, a * a * y1 + 2 * a * t * cy + t * t * y2]);
    }
    const color = opts.color || "var(--ink)";
    const width = opts.width || 2.6;
    mkPath(svg, jitterPath(pts, rand, opts.jit != null ? opts.jit : 1.4),
      { color, width, dash: opts.dotted ? "0.5 9" : null });
    // hand-drawn arrowhead from the true end-tangent
    const p2 = pts[n], p1 = pts[n - 1];
    const ang = Math.atan2(p2[1] - p1[1], p2[0] - p1[0]);
    const hl = opts.head || 15;
    for (const da of [0.5, -0.5]) {
      const hx = p2[0] - hl * Math.cos(ang + da) + (rand() - 0.5) * 2;
      const hy = p2[1] - hl * Math.sin(ang + da) + (rand() - 0.5) * 2;
      mkPath(svg, `M ${p2[0].toFixed(1)} ${p2[1].toFixed(1)} L ${hx.toFixed(1)} ${hy.toFixed(1)}`, { color, width });
    }
  }

  function connect(fromSel, toSel, opts) {
    opts = opts || {};
    const a = document.querySelector(fromSel), b = document.querySelector(toSel);
    const [x1, y1] = anchorPoint(a, opts.from || "right", opts.fromOffset);
    const [x2, y2] = anchorPoint(b, opts.to || "left", opts.toOffset);
    arrow(x1, y1, x2, y2, opts);
  }

  function underline(sel, opts) {
    opts = opts || {};
    const el = document.querySelector(sel);
    const b = el.getBoundingClientRect();
    const y = b.bottom + (opts.gap || 4);
    const rand = mulberry32(hashStr(sel) + 3);
    const n = Math.max(4, Math.round(b.width / 30));
    const pts = [];
    for (let i = 0; i <= n; i++) pts.push([b.left + (b.width * i) / n, y]);
    mkPath(overlay(), jitterPath(pts, rand, 2), { color: opts.color || "var(--ink)", width: opts.width || 3 });
  }

  function circle(cx, cy, r, opts) {
    opts = opts || {};
    const rand = mulberry32(opts.seed || hashStr(cx + "," + cy));
    const d1 = jitterPath(sampleCircle(cx, cy, r, 12), rand, opts.jit != null ? opts.jit : 1.4);
    mkPath(overlay(), d1, { color: opts.color || "var(--ink)", width: opts.width || 2.4, fill: opts.fill || "none" });
    if (opts.double) {
      mkPath(overlay(), jitterPath(sampleCircle(cx, cy, r - 2, 15), mulberry32((opts.seed || 1) + 9), 1.8),
        { color: opts.color || "var(--ink)", width: (opts.width || 2.4) * 0.55, opacity: 0.75 });
    }
  }

  function line(x1, y1, x2, y2, opts) {
    opts = opts || {};
    const rand = mulberry32(opts.seed || (arrowSeed += 7));
    const len = Math.hypot(x2 - x1, y2 - y1);
    const n = Math.max(4, Math.round(len / 24));
    const pts = [];
    for (let i = 0; i <= n; i++) pts.push([x1 + ((x2 - x1) * i) / n, y1 + ((y2 - y1) * i) / n]);
    mkPath(overlay(), jitterPath(pts, rand, opts.jit != null ? opts.jit : 1.6),
      { color: opts.color || "var(--ink)", width: opts.width || 2.4, dash: opts.dotted ? "0.5 9" : null });
  }

  function init() {
    document.querySelectorAll(".box").forEach(boxBorder);
    overlay();
  }

  window.Sketch = { init, connect, arrow, underline, circle, line, overlay, anchorPoint };
})();
