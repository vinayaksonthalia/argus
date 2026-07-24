/* story-builder.js — lays out a 4-panel character strip on the 1600x840 canvas.
   Authoring helper; its content is inlined into each repo's 05-the-story.html.
   Depends on sketch.js (Sketch.*) and character.js (Character.draw). */
(function () {
  const NS = "http://www.w3.org/2000/svg";
  const PX = [50, 439, 828, 1217];     // panel left edges
  const PW = 333, PY = 150, PH = 500;   // panel geometry
  const CX = PX.map(x => x + PW / 2);    // panel centers

  function el(cls, html, css) {
    const d = document.createElement("div");
    d.className = cls; d.innerHTML = html;
    if (css) d.style.cssText = css;
    document.body.appendChild(d);
    return d;
  }

  // subtle comic-panel frame — four wobbly gray sides, corners left open
  function frame(i) {
    const x = PX[i], y = PY, w = PW, h = PH, g = 10, o = { color: "var(--gray)", width: 1.8, jit: 1.1, opacity: 0.85 };
    Sketch.line(x + g, y, x + w - g, y, { ...o, seed: 200 + i });
    Sketch.line(x + w, y + g, x + w, y + h - g, { ...o, seed: 210 + i });
    Sketch.line(x + w - g, y + h, x + g, y + h, { ...o, seed: 220 + i });
    Sketch.line(x, y + h - g, x, y + g, { ...o, seed: 230 + i });
  }

  // number badge, top-left of a panel
  function badge(i, n) {
    const bx = PX[i] + 30, by = PY + 30, accent = getAccent();
    Sketch.circle(bx, by, 17, { color: accent, width: 2.6, seed: 300 + i, jit: 1.0 });
    el("badge", String(n), `left:${bx - 20}px; top:${by - 22}px; width:40px; text-align:center;`);
  }

  function getAccent() { return getComputedStyle(document.body).getPropertyValue("--accent").trim() || "var(--red)"; }

  // headline + caption text for a panel
  function headline(i, txt) { el("phead", txt, `left:${PX[i]}px; top:${PY + 14}px; width:${PW}px; text-align:center;`); }
  function caption(i, txt) { el("pcap", txt, `left:${PX[i] + 12}px; top:${PY + PH - 95}px; width:${PW - 24}px; text-align:center;`); }

  // a subtle hand-drawn card frame (4 wobbly sides, corners left open)
  function cardFrame(left, top, w, h, col, seed) {
    const g = 9, o = { color: col, width: 1.8, jit: 0.9, opacity: 0.55 };
    Sketch.line(left + g, top, left + w - g, top, { ...o, seed: seed });
    Sketch.line(left + w, top + g, left + w, top + h - g, { ...o, seed: seed + 1 });
    Sketch.line(left + w - g, top + h, left + g, top + h, { ...o, seed: seed + 2 });
    Sketch.line(left, top + h - g, left, top + g, { ...o, seed: seed + 3 });
  }

  // a screen/card .box — returns the element so caller can size/fill it
  function screen(i, html, topOff, w, h, klass, frameCol) {
    w = w || 250; h = h || 108; topOff = topOff == null ? 58 : topOff;
    const left = PX[i] + (PW - w) / 2, top = PY + topOff;
    const d = el("box screen " + (klass || ""), html, `left:${left}px; top:${top}px; width:${w}px; height:${h}px;`);
    cardFrame(left, top, w, h, frameCol || getAccent(), 500 + i * 4);
    return { el: d, left, top, w, h, right: left + w, bottom: top + h, cx: left + w / 2, cy: top + h / 2 };
  }

  // sequence arrow in a gutter between panel i and i+1, at height y
  function seqArrow(i, y) {
    const x1 = PX[i] + PW + 6, x2 = PX[i + 1] - 6, accent = getAccent();
    Sketch.arrow(x1, y, x2, y, { color: accent, width: 2.8, seed: 400 + i, jit: 1.0, head: 13 });
  }

  window.Story = {
    PX, PW, PY, PH, CX, el, frame, badge, headline, caption, screen, seqArrow, getAccent,
    // draw the character centered in panel i, sitting in the lower zone
    character(i, pose, opts) {
      opts = opts || {};
      const svg = Sketch.overlay();
      Character.draw(svg, CX[i] + (opts.dx || 0), (opts.cy || (PY + 245)), { pose, scale: opts.scale || 1.0, accent: getAccent(), seed: opts.seed || 7, flip: opts.flip, noSymbol: opts.noSymbol });
    }
  };
})();
