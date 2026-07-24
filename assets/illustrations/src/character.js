/* character.js — "Pager", the recurring on-call engineer.
   A small hand-drawn sketch figure that stars in the story flowcharts.
   Same seeded-wobble treatment as sketch.js, pure SVG, no deps.

   Consistency contract: face, hair and proportions are FIXED. Only the
   eyes / brows / mouth / arms / prop / floating symbol change per pose,
   so the same person recurs across every panel.

   Usage:  Character.draw(svg, cx, cy, { pose, scale, accent, seed, flip })
   Poses:  exhausted paged frustrated puzzled curious focused
           determined aha relieved happy confident asleep
*/
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

  // quadratic-through-midpoints jitter, identical spirit to sketch.js
  function jitter(pts, rand, jit) {
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

  function path(svg, d, o) {
    o = o || {};
    const p = document.createElementNS(NS, "path");
    p.setAttribute("d", d);
    p.setAttribute("fill", o.fill || "none");
    p.setAttribute("stroke", o.color === null ? "none" : (o.color || "var(--ink)"));
    p.setAttribute("stroke-width", o.width || 2.6);
    p.setAttribute("stroke-linecap", "round");
    p.setAttribute("stroke-linejoin", "round");
    if (o.dash) p.setAttribute("stroke-dasharray", o.dash);
    if (o.opacity != null) p.setAttribute("opacity", o.opacity);
    svg.appendChild(p);
    return p;
  }

  function textNode(svg, x, y, str, o) {
    o = o || {};
    const t = document.createElementNS(NS, "text");
    t.setAttribute("x", x.toFixed(1)); t.setAttribute("y", y.toFixed(1));
    t.setAttribute("fill", o.color || "var(--ink)");
    t.setAttribute("font-size", o.size || 30);
    t.setAttribute("text-anchor", o.anchor || "middle");
    t.setAttribute("font-family", o.family || '"Marker Felt","Chalkboard SE",cursive');
    if (o.rotate) t.setAttribute("transform", `rotate(${o.rotate} ${x.toFixed(1)} ${y.toFixed(1)})`);
    t.textContent = str;
    svg.appendChild(t);
    return t;
  }

  function circlePts(cx, cy, r, n, a0, a1) {
    a0 = a0 == null ? 0 : a0; a1 = a1 == null ? Math.PI * 2 : a1;
    const pts = [];
    for (let i = 0; i <= n; i++) { const t = a0 + (a1 - a0) * (i / n); pts.push([cx + r * Math.cos(t), cy + r * Math.sin(t)]); }
    return pts;
  }

  // ---- pose table -----------------------------------------------------
  // eyes/brows/mouth are feature names; hands are LOCAL [x,y] targets;
  // prop / symbol add meaning. Everything else (head, hair) is fixed.
  const POSES = {
    exhausted:  { eyes: "tired",  brows: "worried",  mouth: "frown",  arms: "laptop", symbol: "zzz",  tilt: 6 },
    paged:      { eyes: "wide",   brows: "raised",   mouth: "open",   arms: "phone",  symbol: "alert",tilt: -2 },
    frustrated: { eyes: "annoyed",brows: "angry",    mouth: "wavy",   arms: "laptop", symbol: "grr",  tilt: 3 },
    puzzled:    { eyes: "squint", brows: "quizzical",mouth: "small",  arms: "chin",   symbol: "q",    tilt: 4 },
    curious:    { eyes: "dots",   brows: "raised",   mouth: "small",  arms: "chin",   symbol: "q2",   tilt: -3 },
    focused:    { eyes: "dots",   brows: "flat",     mouth: "flat",   arms: "laptop", symbol: null,   tilt: 1 },
    determined: { eyes: "dots",   brows: "flat",     mouth: "flat",   arms: "point",  symbol: null,   tilt: -2 },
    aha:        { eyes: "wide",   brows: "raised",   mouth: "open",   arms: "up",     symbol: "bulb", tilt: -4 },
    relieved:   { eyes: "happy",  brows: "raised",   mouth: "smile",  arms: "relaxed",symbol: "phew", tilt: 0 },
    happy:      { eyes: "happy",  brows: "raised",   mouth: "bigsmile",arms:"thumbs",  symbol: null,   tilt: -2 },
    confident:  { eyes: "dots",   brows: "flat",     mouth: "smile",  arms: "relaxed",symbol: null,   tilt: -2 },
    asleep:     { eyes: "closed", brows: "flat",     mouth: "small",  arms: "rest",   symbol: "zzz",  tilt: 10 },
  };

  function draw(svg, cx, cy, opts) {
    opts = opts || {};
    const s = opts.scale || 1;
    const seed = opts.seed || 7;
    const flip = opts.flip ? -1 : 1;
    const ink = opts.ink || "var(--ink)";
    const accent = opts.accent || "var(--red)";
    const skin = opts.paper || "var(--paper)";
    const pose = POSES[opts.pose] || POSES.focused;
    const tilt = (pose.tilt || 0);

    // group so we can rotate the whole upper body slightly (body language)
    const g = document.createElementNS(NS, "svg");
    g.setAttribute("x", 0); g.setAttribute("y", 0);
    g.setAttribute("overflow", "visible");
    g.style.overflow = "visible";
    svg.appendChild(g);
    // local->page mapping with flip + slight tilt about head center
    const rad = tilt * Math.PI / 180;
    const cosT = Math.cos(rad), sinT = Math.sin(rad);
    function P(lx, ly) {
      const fx = lx * flip;
      const rx = fx * cosT - ly * sinT;
      const ry = fx * sinT + ly * cosT;
      return [cx + rx * s, cy + ry * s];
    }
    function stroke(localPts, o) {
      o = o || {};
      const r = mulberry32((o.seed || 0) + seed);
      path(g, jitter(localPts.map(p => P(p[0], p[1])), r, (o.jit != null ? o.jit : 1.2) * s), { color: o.color, width: (o.width || 2.6) * s, fill: o.fill, opacity: o.opacity, dash: o.dash });
    }
    function dot(lx, ly, lr, o) {
      o = o || {};
      const r = mulberry32((o.seed || 0) + seed + 3);
      path(g, jitter(circlePts(0, 0, lr, 12).map(p => P(lx + p[0], ly + p[1])), r, 0.7 * s), { color: o.color || ink, width: (o.width || 2.2) * s, fill: o.fill || ink });
    }
    function W(v) { return v * s; }

    const R = 30;            // head radius (local)
    const HCY = 0;           // head center y (local origin-ish)

    // ---------- floating symbol bubble (drawn first, sits behind) ------
    if (!opts.noSymbol) drawSymbol(pose.symbol);

    // ---------- torso / shirt ------------------------------------------
    const shL = [-30, 50], shR = [30, 50];
    const torso = [
      [-9, 40], [-22, 46], [shL[0], shL[1]], [-30, 82], [-26, 108],
      [0, 114], [26, 108], [30, 82], [shR[0], shR[1]], [22, 46], [9, 40]
    ];
    stroke(torso, { seed: 40, jit: 1.3, width: 2.7 });
    // collar V
    stroke([[-9, 40], [0, 50], [9, 40]], { seed: 44, jit: 0.8, width: 2.4 });
    // accent lanyard / badge — the on-call identity, in project accent
    stroke([[-6, 48], [-3, 70]], { seed: 46, color: accent, width: 2.2, jit: 0.7 });
    stroke([[3, 48], [1, 72]], { seed: 47, color: accent, width: 2.2, jit: 0.7 });
    dot(-1, 74, 5, { color: accent, fill: accent, seed: 48 });

    // ---------- neck ----------------------------------------------------
    stroke([[-8, 28], [-8, 41]], { seed: 50, jit: 0.6, width: 2.4 });
    stroke([[8, 28], [8, 41]], { seed: 51, jit: 0.6, width: 2.4 });

    // ---------- arms + prop (behind head if raised) --------------------
    drawArms(pose.arms);

    // ---------- head (fill paper so arms/torso don't show through) -----
    stroke(circlePts(0, HCY, R, 26), { seed: 10, jit: 1.0, width: 2.9, fill: skin });

    // ---------- hair — messy mop on the upper arc (FIXED) --------------
    // base fringe line, dipping onto the forehead
    stroke([[-27, -12], [-19, -21], [-8, -24], [2, -20], [12, -24], [21, -20], [28, -11]], { seed: 20, jit: 1.1, width: 2.6 });
    // a fringe strand sweeping across the forehead (reads as hair, not spikes)
    stroke([[-19, -18], [-8, -12], [4, -14]], { seed: 21, jit: 0.8, width: 2.2, opacity: 0.9 });
    // uneven tufts poking up — varied heights so it's a messy mop
    const tufts = [
      [[-22, -18], [-25, -30], [-15, -23]],
      [[-11, -23], [-7, -37], [0, -25]],
      [[1, -22], [7, -34], [12, -23]],
      [[13, -23], [21, -31], [24, -19]],
      [[-26, -12], [-33, -19], [-27, -8]],
      [[24, -14], [31, -18], [27, -8]],
    ];
    tufts.forEach((t, i) => stroke(t, { seed: 23 + i, jit: 1.0, width: 2.5 }));

    // ---------- face features ------------------------------------------
    drawBrows(pose.brows);
    drawEyes(pose.eyes);
    drawMouth(pose.mouth);

    // =====================================================================
    function drawEyes(kind) {
      const lx = -11, rx = 11, ey = -2;
      if (kind === "dots") { dot(lx, ey, 3.4, { seed: 60 }); dot(rx, ey, 3.4, { seed: 61 }); }
      else if (kind === "wide") {
        stroke(circlePts(lx, ey, 6.2, 12), { seed: 60, jit: 0.6, width: 2.3, fill: skin });
        stroke(circlePts(rx, ey, 6.2, 12), { seed: 61, jit: 0.6, width: 2.3, fill: skin });
        dot(lx + 1, ey + 1, 2.4, { seed: 62 }); dot(rx + 1, ey + 1, 2.4, { seed: 63 });
      } else if (kind === "tired") {
        stroke([[lx - 7, ey - 1], [lx, ey + 1], [lx + 7, ey - 1]], { seed: 60, jit: 0.5, width: 2.4 });
        stroke([[rx - 7, ey - 1], [rx, ey + 1], [rx + 7, ey - 1]], { seed: 61, jit: 0.5, width: 2.4 });
        // under-eye bags
        stroke([[lx - 5, ey + 5], [lx, ey + 7], [lx + 5, ey + 5]], { seed: 64, jit: 0.4, width: 1.7, opacity: 0.7 });
        stroke([[rx - 5, ey + 5], [rx, ey + 7], [rx + 5, ey + 5]], { seed: 65, jit: 0.4, width: 1.7, opacity: 0.7 });
      } else if (kind === "squint") {
        stroke([[lx - 6, ey], [lx + 6, ey - 1]], { seed: 60, jit: 0.4, width: 2.5 });
        stroke([[rx - 6, ey - 1], [rx + 6, ey]], { seed: 61, jit: 0.4, width: 2.5 });
      } else if (kind === "annoyed") {
        stroke([[lx - 6, ey - 2], [lx + 6, ey - 2]], { seed: 60, jit: 0.4, width: 2.4 });
        stroke([[rx - 6, ey - 2], [rx + 6, ey - 2]], { seed: 61, jit: 0.4, width: 2.4 });
        dot(lx + 1, ey + 1, 2.6, { seed: 62 }); dot(rx - 1, ey + 1, 2.6, { seed: 63 });
      } else if (kind === "happy") { // upward smiling eyes  ^_^
        stroke([[lx - 6, ey + 2], [lx, ey - 3], [lx + 6, ey + 2]], { seed: 60, jit: 0.4, width: 2.5 });
        stroke([[rx - 6, ey + 2], [rx, ey - 3], [rx + 6, ey + 2]], { seed: 61, jit: 0.4, width: 2.5 });
      } else if (kind === "closed") { // calm closed  ‿
        stroke([[lx - 6, ey - 1], [lx, ey + 2], [lx + 6, ey - 1]], { seed: 60, jit: 0.4, width: 2.3 });
        stroke([[rx - 6, ey - 1], [rx, ey + 2], [rx + 6, ey - 1]], { seed: 61, jit: 0.4, width: 2.3 });
      }
    }

    function drawBrows(kind) {
      const lx = -11, rx = 11, by = -14;
      if (kind === "none") return;
      let L, Rr;
      if (kind === "worried") { L = [[lx - 6, by + 1], [lx + 6, by - 3]]; Rr = [[rx - 6, by - 3], [rx + 6, by + 1]]; }
      else if (kind === "raised") { L = [[lx - 6, by - 3], [lx, by - 5], [lx + 6, by - 3]]; Rr = [[rx - 6, by - 3], [rx, by - 5], [rx + 6, by - 3]]; by; }
      else if (kind === "flat") { L = [[lx - 6, by], [lx + 6, by]]; Rr = [[rx - 6, by], [rx + 6, by]]; }
      else if (kind === "angry") { L = [[lx - 6, by - 3], [lx + 6, by + 2]]; Rr = [[rx - 6, by + 2], [rx + 6, by - 3]]; }
      else if (kind === "quizzical") { L = [[lx - 6, by + 1], [lx + 6, by + 1]]; Rr = [[rx - 6, by - 5], [rx, by - 7], [rx + 6, by - 4]]; }
      stroke(L, { seed: 70, jit: 0.5, width: 2.4 });
      stroke(Rr, { seed: 71, jit: 0.5, width: 2.4 });
    }

    function drawMouth(kind) {
      const my = 14;
      if (kind === "flat") stroke([[-6, my], [6, my]], { seed: 80, jit: 0.4, width: 2.3 });
      else if (kind === "small") stroke([[-3.5, my], [3.5, my]], { seed: 80, jit: 0.3, width: 2.3 });
      else if (kind === "frown") stroke([[-8, my + 3], [0, my - 2], [8, my + 3]], { seed: 80, jit: 0.5, width: 2.4 });
      else if (kind === "smile") stroke([[-8, my - 2], [0, my + 4], [8, my - 2]], { seed: 80, jit: 0.5, width: 2.5 });
      else if (kind === "bigsmile") {
        stroke([[-11, my - 3], [0, my + 7], [11, my - 3]], { seed: 80, jit: 0.5, width: 2.7 });
        stroke([[-8, my + 0.5], [0, my + 4], [8, my + 0.5]], { seed: 81, jit: 0.4, width: 1.7, opacity: 0.6 });
      }
      else if (kind === "open") stroke(circlePts(0, my + 2, 5.2, 12), { seed: 80, jit: 0.5, width: 2.4, fill: ink, opacity: 0.9 });
      else if (kind === "wavy") stroke([[-8, my], [-4, my - 2.5], [0, my], [4, my - 2.5], [8, my]], { seed: 80, jit: 0.4, width: 2.3 });
    }

    function drawArms(kind) {
      const sL = shL, sR = shR;
      function arm(sh, elbow, hand, sd) { stroke([sh, elbow, hand], { seed: sd, jit: 0.9, width: 2.7 }); dot(hand[0], hand[1], 3.2, { seed: sd + 1, color: ink, fill: skin, width: 2.2 }); }
      if (kind === "laptop") {
        // laptop between us and character; hands rest on the near edge
        arm(sL, [-34, 74], [-19, 86], 90);
        arm(sR, [34, 74], [19, 86], 92);
        const lb = [[-40, 88], [40, 88], [46, 104], [-46, 104]];
        stroke([lb[0], lb[1], lb[2], lb[3], lb[0]], { seed: 94, jit: 0.9, width: 2.7, fill: skin });
        // keyboard hint + accent screen-glow line
        stroke([[-30, 96], [30, 96]], { seed: 95, jit: 0.4, width: 1.6, opacity: 0.5 });
        stroke([[-40, 88], [40, 88]], { seed: 96, color: accent, jit: 0.5, width: 2.4, opacity: 0.9 });
      } else if (kind === "phone") {
        arm(sL, [-34, 78], [-24, 96], 90);
        // right hand raised holding a glowing phone near the face
        arm(sR, [30, 60], [26, 26], 92);
        const ph = [[20, 8], [34, 12], [30, 30], [16, 26]];
        stroke([ph[0], ph[1], ph[2], ph[3], ph[0]], { seed: 97, jit: 0.7, width: 2.6, fill: skin });
        stroke([[22, 14], [31, 17]], { seed: 98, color: accent, jit: 0.4, width: 2.4 });
      } else if (kind === "chin") {
        arm(sL, [-34, 80], [-26, 100], 90);
        // right forearm up beside the face, hand cupping the chin — thinking
        stroke([sR, [42, 62], [30, 34], [15, 25]], { seed: 92, jit: 0.8, width: 2.7 });
        dot(13, 26, 4.4, { seed: 93, color: ink, fill: skin, width: 2.3 });
      } else if (kind === "up") {
        arm(sL, [-34, 78], [-26, 98], 90);
        // right index finger up — the "aha!"
        stroke([sR, [36, 30], [40, -6]], { seed: 92, jit: 0.9, width: 2.7 });
        dot(40, -8, 3.2, { seed: 93, color: ink, fill: skin, width: 2.2 });
      } else if (kind === "point") {
        arm(sL, [-34, 80], [-26, 100], 90);
        stroke([sR, [40, 58], [58, 52]], { seed: 92, jit: 0.9, width: 2.7 });
        dot(60, 52, 3.0, { seed: 93, color: ink, fill: skin, width: 2.2 });
      } else if (kind === "thumbs") {
        arm(sL, [-34, 82], [-24, 100], 90);
        // right arm across, thumbs up
        stroke([sR, [30, 70], [12, 58]], { seed: 92, jit: 0.8, width: 2.7 });
        stroke([[12, 58], [10, 44]], { seed: 93, jit: 0.5, width: 2.6 }); // thumb
        dot(11, 60, 4.2, { seed: 94, color: ink, fill: skin, width: 2.2 });
      } else if (kind === "rest") {
        // asleep — arms folded on a desk, head will tilt onto them
        arm(sL, [-30, 86], [6, 96], 90);
        arm(sR, [30, 86], [-6, 100], 92);
        stroke([[-44, 104], [44, 104]], { seed: 95, jit: 0.5, width: 2.4, opacity: 0.7 }); // desk line
      } else { // relaxed — hands tucked just inside the torso, not knobs
        arm(sL, [-32, 80], [-22, 98], 90);
        arm(sR, [32, 80], [22, 98], 92);
      }
    }

    function drawSymbol(sym) {
      if (!sym) return;
      // position up-and-right of the head in a little sketch bubble
      const bx = 46, by = -34;
      const put = (str, col, size, dx, dy, rot) => {
        const [px, py] = P(bx + (dx || 0), by + (dy || 0));
        textNode(g, px, py, str, { color: col, size: (size || 34) * s, rotate: rot || 0 });
      };
      if (sym === "zzz") { put("z", accent, 22, -4, -6, 8); put("z", accent, 28, 8, -16, 8); put("z", accent, 36, 24, -28, 8); }
      else if (sym === "q") put("?", accent, 46, 2, 0, 8);
      else if (sym === "q2") put("?", accent, 40, 0, -2, -8);
      else if (sym === "alert") { drawBell(bx, by); }
      else if (sym === "grr") { put("#", accent, 30, -6, -6, -12); put("@", accent, 30, 14, -14, 10); put("%", accent, 26, 2, 6, 0); }
      else if (sym === "phew") put("~", accent, 40, 0, 0, 0);
      else if (sym === "bulb") drawBulb(bx + 2, by - 2);
    }
    function drawBell(bx, by) {
      // little alert bell in accent
      stroke([[bx - 12, by + 6], [bx - 10, by - 6], [bx, by - 12], [bx + 10, by - 6], [bx + 12, by + 6], [bx - 12, by + 6]], { seed: 120, color: accent, jit: 0.6, width: 2.6 });
      dot(bx, by - 15, 2.6, { seed: 121, color: accent, fill: accent });
      dot(bx, by + 10, 2.4, { seed: 122, color: accent, fill: accent });
      // ring lines
      stroke([[bx + 15, by - 8], [bx + 20, by - 12]], { seed: 123, color: accent, jit: 0.4, width: 2 });
      stroke([[bx + 16, by + 2], [bx + 22, by + 2]], { seed: 124, color: accent, jit: 0.4, width: 2 });
    }
    function drawBulb(bx, by) {
      stroke(circlePts(bx, by - 4, 11, 14), { seed: 130, color: accent, jit: 0.6, width: 2.6 });
      stroke([[bx - 6, by + 7], [bx + 6, by + 7]], { seed: 131, color: accent, jit: 0.3, width: 2.4 });
      stroke([[bx - 5, by + 11], [bx + 5, by + 11]], { seed: 132, color: accent, jit: 0.3, width: 2.2 });
      // rays
      [[0, -20], [-16, -12], [16, -12], [-20, 2], [20, 2]].forEach((r, i) =>
        stroke([[bx + r[0] * 0.6, by + r[1] * 0.6 - 2], [bx + r[0], by + r[1] - 4]], { seed: 133 + i, color: accent, jit: 0.3, width: 2 }));
    }
  }

  window.Character = { draw, POSES };
})();
