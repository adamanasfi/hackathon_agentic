/* ---------- Semantic visual primitives (template, paper-agnostic) ----------
   3Blue1Brown-style building blocks on top of V.diagram: every element is keyed, so re-rendering animates. */
(function () {
  const { diagram, color, fmt, ticks, clamp, line } = V;
  const INK = V.ink, MUTED = V.muted, BG = V.bg, GOLD = "#e2b86b", TEAL = "#4fb3bf", CORAL = "#e07a5f";
  const fin = (v) => typeof v === "number" && isFinite(v);
  const num = (v, d) => (fin(v) ? fmt(v, d === undefined ? 2 : d) : String(v === undefined ? "" : v));
  const host = (id) => V.$(id);

  /* ---- drag support: element calls fn(x, y) in data coordinates, then the page recomputes ---- */
  function draggable(e, svg, fn) {
    e._drag = fn;
    if (e._wired) return;
    e._wired = true;
    e.style.cursor = "grab";
    e.addEventListener("pointerdown", (ev) => { e.setPointerCapture(ev.pointerId); e._on = true; e.style.cursor = "grabbing"; ev.preventDefault(); });
    e.addEventListener("pointerup", () => { e._on = false; e.style.cursor = "grab"; });
    e.addEventListener("pointermove", (ev) => {
      if (!e._on || !e._drag || !svg._map) return;
      const pt = svg.createSVGPoint(); pt.x = ev.clientX; pt.y = ev.clientY;
      const p = pt.matrixTransform(svg.getScreenCTM().inverse()), m = svg._map;
      const snap = m.snap || 0.05, r = (v) => Math.round(v / snap) * snap;
      try { e._drag(+r(m.ix(p.x)).toFixed(4), +r(m.iy(p.y)).toFixed(4)); V.update(); } catch (err) { console.warn(err); }
    });
  }

  /* ---- V.space: 2-D vector space (embeddings, similarity, attention geometry, linear algebra) ---- */
  function space(id, o) {
    o = o || {};
    const W = o.w || 640, H = o.h || 440, top = o.title ? 26 : 8, m = 26;
    const d = diagram(id, W, H), svg = d.svg;
    const vs = o.vectors || [], ps = o.points || [], ls = o.lines || [];
    const xs = [0], ys = [0];
    vs.forEach((v) => { const f = v.from || [0, 0]; xs.push(v.x, f[0]); ys.push(v.y, f[1]); });
    ps.forEach((p) => { xs.push(p.x); ys.push(p.y); });
    ls.forEach((l) => { xs.push(l.x1, l.x2); ys.push(l.y1, l.y2); });
    const fx = xs.filter(fin), fy = ys.filter(fin);
    let rng = { x0: Math.min(...fx), x1: Math.max(...fx), y0: Math.min(...fy), y1: Math.max(...fy) };
    const pad = (a, b) => { const s = Math.max(b - a, 1e-9) * 0.18 + 0.4; return [a - s, b + s]; };
    [rng.x0, rng.x1] = pad(rng.x0, rng.x1); [rng.y0, rng.y1] = pad(rng.y0, rng.y1);
    const dragging = vs.concat(ps).some((q) => q.drag);
    if (o.xmin !== undefined) { rng = { x0: o.xmin, x1: o.xmax, y0: o.ymin, y1: o.ymax }; }
    else if (dragging) { if (!svg._frozen) svg._frozen = rng; else { const f = svg._frozen; rng = { x0: Math.min(f.x0, rng.x0), x1: Math.max(f.x1, rng.x1), y0: Math.min(f.y0, rng.y0), y1: Math.max(f.y1, rng.y1) }; svg._frozen = rng; } }
    const s = Math.min((W - 2 * m) / (rng.x1 - rng.x0), (H - top - 2 * m) / (rng.y1 - rng.y0));
    const cx = W / 2 - s * (rng.x0 + rng.x1) / 2, cy = top + (H - top) / 2 + s * (rng.y0 + rng.y1) / 2;
    const X = (x) => cx + s * x, Y = (y) => cy - s * y;
    svg._map = { ix: (px) => (px - cx) / s, iy: (py) => (cy - py) / s, snap: o.snap };
    if (o.title) d.text("title", W / 2, 18, o.title, { textAnchor: "middle", fontWeight: 650, fill: GOLD });
    if (o.grid !== false) {
      const vx0 = (m - cx) / s, vx1 = (W - m - cx) / s, vy0 = (cy - (H - m)) / s, vy1 = (cy - top - m) / s;
      ticks(vx0, vx1, 8).forEach((t, i) => d.line("gx" + i, { x1: X(t), x2: X(t), y1: top + m, y2: H - m, class: "grid" }));
      ticks(vy0, vy1, 6).forEach((t, i) => d.line("gy" + i, { x1: m, x2: W - m, y1: Y(t), y2: Y(t), class: "grid" }));
      if (vy0 <= 0 && vy1 >= 0) d.line("axx", { x1: m, x2: W - m, y1: Y(0), y2: Y(0), class: "ax" });
      if (vx0 <= 0 && vx1 >= 0) d.line("axy", { x1: X(0), x2: X(0), y1: top + m, y2: H - m, class: "ax" });
      if (o.xlabel) d.text("xl", W - m, Y(0) - 6, o.xlabel, { textAnchor: "end", fill: MUTED, fontSize: 12 });
      if (o.ylabel) d.text("yl", X(0) + 6, top + m + 4, o.ylabel, { fill: MUTED, fontSize: 12 });
    }
    (o.regions || []).forEach((g, i) => d.circle("rg" + i, { cx: X(g.x), cy: Y(g.y), r: Math.max(4, (g.r || 0.5) * s), fill: g.color || color(i), fillOpacity: 0.1, stroke: g.color || color(i), strokeDasharray: "4 4" }));
    (o.regions || []).forEach((g, i) => { if (g.label) d.text("rgl" + i, X(g.x), Y(g.y) - (g.r || 0.5) * s - 6, g.label, { textAnchor: "middle", fill: g.color || color(i), fontSize: 12 }); });
    ls.forEach((l, i) => {
      d.line("l" + i, { x1: X(l.x1), y1: Y(l.y1), x2: X(l.x2), y2: Y(l.y2), stroke: l.color || MUTED, strokeWidth: l.width || 1.5, strokeDasharray: l.dash === false ? "none" : "5 4" });
      if (l.label) d.text("ll" + i, X((l.x1 + l.x2) / 2) + 6, Y((l.y1 + l.y2) / 2) - 6, l.label, { fill: l.color || MUTED, fontSize: 12 });
    });
    (o.arcs || []).forEach((a, i) => {
      const va = vs[a.a], vb = vs[a.b]; if (!va || !vb) return;
      const t1 = Math.atan2(va.y, va.x), t2 = Math.atan2(vb.y, vb.x), R = a.r || 34;
      let dt = t2 - t1; while (dt > Math.PI) dt -= 2 * Math.PI; while (dt < -Math.PI) dt += 2 * Math.PI;
      const p1 = [X(0) + R * Math.cos(t1), Y(0) - R * Math.sin(t1)], p2 = [X(0) + R * Math.cos(t1 + dt), Y(0) - R * Math.sin(t1 + dt)];
      d.path("arc" + i, { d: "M" + p1[0] + " " + p1[1] + " A" + R + " " + R + " 0 0 " + (dt > 0 ? 0 : 1) + " " + p2[0] + " " + p2[1], stroke: a.color || GOLD, strokeWidth: 2 });
      if (a.label) { const tm = t1 + dt / 2; d.text("arcl" + i, X(0) + (R + 16) * Math.cos(tm), Y(0) - (R + 16) * Math.sin(tm) + 4, a.label, { textAnchor: "middle", fill: a.color || GOLD, fontSize: 12 }); }
    });
    const placed = [];
    function spot(x, y, w, anchor) {
      const x0 = anchor === "end" ? x - w : anchor === "middle" ? x - w / 2 : x;
      for (const dy of [0, -14, 14, -28, 28, -42, 42]) {
        const b = [x0, y + dy - 11, x0 + w, y + dy + 3];
        if (!placed.some((q) => b[0] < q[2] && b[2] > q[0] && b[1] < q[3] && b[3] > q[1])) { placed.push(b); return y + dy; }
      }
      placed.push([x0, y - 11, x0 + w, y + 3]); return y;
    }
    const tw = (t) => String(t).length * 7.2;
    vs.forEach((v, i) => {
      const f = v.from || [0, 0], c = v.color || color(i);
      d.arrow("v" + i, X(f[0]), Y(f[1]), X(v.x), Y(v.y), { stroke: c, strokeWidth: v.width || 3, head: 11, opacity: v.opacity === undefined ? 1 : v.opacity });
      if (v.label) {
        const dx = X(v.x) - X(f[0]), dy = Y(v.y) - Y(f[1]), L = Math.hypot(dx, dy) || 1;
        const anc = dx < -2 ? "end" : dx > 2 ? "start" : "middle", lx = X(v.x) + (dx / L) * 14;
        d.text("vl" + i, lx, spot(lx, Y(v.y) + (dy / L) * 14 + 4, tw(v.label), anc), v.label, { textAnchor: anc, fill: c, fontWeight: 650 });
      }
      if (v.drag) draggable(d.circle("vh" + i, { cx: X(v.x), cy: Y(v.y), r: 10, fill: c, fillOpacity: 0.28, stroke: c }), svg, v.drag);
    });
    ps.forEach((p, i) => {
      const c = p.color || color(i), r = p.r || 7;
      const e = d.circle("p" + i, { cx: X(p.x), cy: Y(p.y), r, fill: c, stroke: BG, strokeWidth: 2, opacity: p.opacity === undefined ? 1 : p.opacity });
      if (p.label) d.text("pl" + i, X(p.x) + r + 5, spot(X(p.x) + r + 5, Y(p.y) + 4, tw(p.label), "start"), p.label, { fill: INK, fontSize: 13 });
      if (p.drag) draggable(e, svg, p.drag);
    });
    d.end();
    return { X, Y, scale: s };
  }

  /* ---- V.network: layered neural network graph ---- */
  function network(id, o) {
    o = o || {};
    const layers = (o.layers || []).map((n) => Math.max(1, n | 0)), Lc = layers.length;
    const maxN = Math.max(1, ...layers), W = o.w || 640, top = o.title ? 28 : 10;
    const gap = clamp(300 / maxN, 34, 70), H = o.h || Math.max(260, top + 50 + gap * maxN);
    const d = diagram(id, W, H), m = 60;
    const nx = (l) => (Lc === 1 ? W / 2 : m + ((W - 2 * m) * l) / (Lc - 1));
    const ny = (l, i) => top + (H - top - 30) / 2 + (i - (layers[l] - 1) / 2) * gap;
    const rN = clamp(gap * 0.32, 10, 20);
    if (o.title) d.text("title", W / 2, 18, o.title, { textAnchor: "middle", fontWeight: 650, fill: GOLD });
    const Wt = o.weights || [];
    let wmax = 0;
    Wt.forEach((M) => (M || []).forEach((r) => (r || []).forEach((v) => { if (fin(v)) wmax = Math.max(wmax, Math.abs(v)); })));
    const wAt = (l, i, j) => { const M = Wt[l]; if (!M) return undefined; if (M.length === layers[l + 1] && M[0] && M[0].length === layers[l]) return M[j][i]; if (M.length === layers[l] && M[0] && M[0].length === layers[l + 1]) return M[i][j]; return undefined; };
    let ne = 0;
    for (let l = 0; l + 1 < Lc; l++) for (let i = 0; i < layers[l]; i++) for (let j = 0; j < layers[l + 1]; j++) {
      const w = wAt(l, i, j), t = fin(w) && wmax ? Math.abs(w) / wmax : 0.35;
      d.line("e" + l + "_" + i + "_" + j, { x1: nx(l) + rN, y1: ny(l, i), x2: nx(l + 1) - rN, y2: ny(l + 1, j), stroke: !fin(w) ? MUTED : w >= 0 ? TEAL : CORAL, strokeWidth: 0.6 + 4 * t, opacity: 0.25 + 0.7 * t });
      if (o.edgeLabels && fin(w)) { ne++; d.text("el" + l + "_" + i + "_" + j, nx(l) + (nx(l + 1) - nx(l)) * 0.3, ny(l, i) + (ny(l + 1, j) - ny(l, i)) * 0.3 - 4, num(w, 1), { textAnchor: "middle", fontSize: 11, fill: w >= 0 ? TEAL : CORAL }); }
    }
    const A = o.values || [];
    let amax = 0;
    A.forEach((r) => (r || []).forEach((v) => { if (fin(v)) amax = Math.max(amax, Math.abs(v)); }));
    for (let l = 0; l < Lc; l++) {
      for (let i = 0; i < layers[l]; i++) {
        const v = A[l] ? A[l][i] : undefined, t = fin(v) && amax ? Math.abs(v) / amax : 0;
        const act = o.active === l || (o.active && o.active.layer === l && o.active.node === i);
        d.circle("n" + l + "_" + i, { cx: nx(l), cy: ny(l, i), r: rN, fill: fin(v) ? (v >= 0 ? "rgba(79,179,191," : "rgba(224,122,95,") + (0.15 + 0.8 * t).toFixed(3) + ")" : "#1b2330", stroke: act ? GOLD : "#3a4352", strokeWidth: act ? 3 : 1.5 });
        if (fin(v) && o.showValues !== false) d.text("nv" + l + "_" + i, nx(l), ny(l, i) + 4, num(v, 2), { textAnchor: "middle", fontSize: 11, fill: t > 0.6 ? "#071014" : INK });
        const lab = o.labels && o.labels[l] && o.labels[l][i];
        if (lab) d.text("nl" + l + "_" + i, l === 0 ? nx(l) - rN - 6 : nx(l) + rN + 6, ny(l, i) + 4, lab, { textAnchor: l === 0 ? "end" : "start", fontSize: 12, fill: INK });
      }
      const ln = o.layerNames && o.layerNames[l];
      if (ln) d.text("ln" + l, nx(l), H - 8, ln, { textAnchor: "middle", fontSize: 12, fill: o.active === l ? GOLD : MUTED });
    }
    d.end();
    return d;
  }

  /* ---- V.graph: weighted directed graph (PageRank, Markov chains, message passing) ---- */
  function graph(id, o) {
    o = o || {};
    const N = o.nodes || [], E = o.edges || [], W = o.w || 640, H = o.h || 420, top = o.title ? 28 : 6;
    const d = diagram(id, W, H);
    if (o.title) d.text("title", W / 2, 18, o.title, { textAnchor: "middle", fontWeight: 650, fill: GOLD });
    const idx = new Map(N.map((n, i) => [n.id === undefined ? i : n.id, i]));
    const vmax = Math.max(1e-9, ...N.map((n) => (fin(n.value) ? Math.abs(n.value) : 0)));
    const R0 = Math.min(W, H - top) * 0.36, ccx = W / 2, ccy = top + (H - top) / 2;
    const pos = N.map((n, i) => fin(n.x) && fin(n.y) ? [40 + n.x * (W - 80), top + 30 + n.y * (H - top - 60)] : [ccx + R0 * Math.cos(-Math.PI / 2 + (2 * Math.PI * i) / Math.max(1, N.length)), ccy + R0 * Math.sin(-Math.PI / 2 + (2 * Math.PI * i) / Math.max(1, N.length))]);
    const rad = N.map((n) => (fin(n.value) ? 14 + 22 * Math.sqrt(Math.abs(n.value) / vmax) : 22));
    const wmax = Math.max(1e-9, ...E.map((e) => (fin(e.w) ? Math.abs(e.w) : 1)));
    const has = new Set(E.map((e) => idx.get(e.from) + ">" + idx.get(e.to)));
    E.forEach((e, k) => {
      const a = idx.get(e.from), b = idx.get(e.to); if (a === undefined || b === undefined) return;
      const c = e.color || MUTED, t = fin(e.w) ? Math.abs(e.w) / wmax : 0.5, sw = 1 + 4 * t;
      if (a === b) { const [x, y] = pos[a], r = rad[a]; d.path("e" + k, { d: "M" + (x - 8) + " " + (y - r) + " C" + (x - 30) + " " + (y - r - 46) + " " + (x + 30) + " " + (y - r - 46) + " " + (x + 8) + " " + (y - r), stroke: c, strokeWidth: sw, opacity: 0.4 + 0.6 * t }); return; }
      const [x1, y1] = pos[a], [x2, y2] = pos[b], L = Math.hypot(x2 - x1, y2 - y1) || 1, ux = (x2 - x1) / L, uy = (y2 - y1) / L;
      const off = has.has(b + ">" + a) ? 7 : 0, px = -uy * off, py = ux * off;
      d.arrow("e" + k, x1 + ux * rad[a] + px, y1 + uy * rad[a] + py, x2 - ux * (rad[b] + 3) + px, y2 - uy * (rad[b] + 3) + py, { stroke: c, strokeWidth: sw, opacity: 0.4 + 0.6 * t, head: 8 + 2 * t });
      if (e.label !== undefined) d.text("elb" + k, (x1 + x2) / 2 + px * 2.2, (y1 + y2) / 2 + py * 2.2 - 4, typeof e.label === "number" ? num(e.label, 2) : e.label, { textAnchor: "middle", fontSize: 11, fill: c === MUTED ? INK : c });
    });
    N.forEach((n, i) => {
      const c = n.color || color(i);
      d.circle("n" + i, { cx: pos[i][0], cy: pos[i][1], r: rad[i], fill: c, fillOpacity: 0.85, stroke: n.active ? GOLD : BG, strokeWidth: n.active ? 3 : 2 });
      d.text("nl" + i, pos[i][0], pos[i][1] + 4, n.label === undefined ? String(n.id === undefined ? i : n.id) : n.label, { textAnchor: "middle", fontWeight: 700, fill: "#071014" });
      if (fin(n.value)) d.text("nv" + i, pos[i][0], pos[i][1] + rad[i] + 15, num(n.value, o.digits === undefined ? 3 : o.digits), { textAnchor: "middle", fontSize: 12, fill: INK });
    });
    d.end();
    return { pos };
  }

  /* ---- V.flow: stages of an algorithm / pipeline with live values ---- */
  function flow(id, o) {
    o = o || {};
    const S = o.steps || [], n = Math.max(1, S.length), gap = 34, m = 16;
    const bw = clamp(o.boxWidth || 130, 80, 200), W = o.w || Math.max(640, 2 * m + n * bw + (n - 1) * gap), top = o.title ? 30 : 8;
    const bh = 70, H = o.h || top + bh + 46, y0 = top + 8;
    const d = diagram(id, W, H);
    const x0 = (W - (n * bw + (n - 1) * gap)) / 2;
    if (o.title) d.text("title", W / 2, 20, o.title, { textAnchor: "middle", fontWeight: 650, fill: GOLD });
    S.forEach((st, i) => {
      const x = x0 + i * (bw + gap), c = st.color || color(i), act = o.active === i;
      d.rect("b" + i, { x, y: y0, width: bw, height: bh, rx: 10, fill: act ? "rgba(226,184,107,.12)" : "#171e29", stroke: act ? GOLD : c, strokeWidth: act ? 3 : 1.5 });
      d.text("bl" + i, x + bw / 2, y0 + 24, st.label || "", { textAnchor: "middle", fontWeight: 650, fill: act ? GOLD : c, fontSize: 13 });
      if (st.value !== undefined) d.text("bv" + i, x + bw / 2, y0 + 50, typeof st.value === "number" ? num(st.value, 3) : String(st.value), { textAnchor: "middle", fill: INK, fontSize: 13, fontFamily: "monospace" });
      if (st.note) d.text("bn" + i, x + bw / 2, y0 + bh + 18, st.note, { textAnchor: "middle", fill: MUTED, fontSize: 11 });
      if (i + 1 < n) {
        d.arrow("a" + i, x + bw + 4, y0 + bh / 2, x + bw + gap - 4, y0 + bh / 2, { stroke: o.active === i + 1 ? GOLD : MUTED, strokeWidth: 2, head: 8 });
        const al = o.arrowLabels && o.arrowLabels[i];
        if (al) d.text("al" + i, x + bw + gap / 2, y0 + bh / 2 - 8, al, { textAnchor: "middle", fill: MUTED, fontSize: 11 });
      }
    });
    d.end();
    return d;
  }

  /* ---- V.pixels: image / feature-map grid with an (animated) sliding window ---- */
  function pixels(id, M, o) {
    o = o || {};
    M = (Array.isArray(M) ? M : []).map((r) => (Array.isArray(r) ? r : [r]));
    const R = M.length, C = R ? Math.max(...M.map((r) => r.length)) : 0, top = o.title ? 28 : 6, m = 20;
    const cs = o.cell || clamp(Math.floor(Math.min(340 / Math.max(R, 1), 560 / Math.max(C, 1))), 10, 52);
    const W = o.w || Math.max(240, C * cs + 2 * m), H = top + R * cs + 2 * m;
    const d = diagram(id, W, H), x0 = (W - C * cs) / 2, y0 = top + m;
    let mx = o.max; if (mx === undefined) { mx = 0; M.forEach((r) => r.forEach((v) => { if (fin(v)) mx = Math.max(mx, Math.abs(v)); })); }
    if (o.title) d.text("title", W / 2, 18, o.title, { textAnchor: "middle", fontWeight: 650, fill: GOLD });
    const showV = o.values !== false && cs >= 24;
    M.forEach((r, i) => r.forEach((v, j) => {
      const t = fin(v) ? clamp(Math.abs(v) / (mx || 1), 0, 1) : 0;
      const fill = !fin(v) ? "#5c2323" : o.gray ? "rgba(230,237,243," + (0.04 + 0.9 * t).toFixed(3) + ")" : (v < 0 ? "rgba(224,122,95," : "rgba(79,179,191,") + (0.06 + 0.88 * t).toFixed(3) + ")";
      d.rect("c" + i + "_" + j, { x: x0 + j * cs, y: y0 + i * cs, width: cs - 1, height: cs - 1, fill, rx: 2 });
      if (showV) d.text("t" + i + "_" + j, x0 + j * cs + cs / 2, y0 + i * cs + cs / 2 + 4, num(v, o.digits === undefined ? (Number.isInteger(v) ? 0 : 1) : o.digits), { textAnchor: "middle", fontSize: Math.min(12, cs * 0.36), fill: t > 0.6 ? "#071014" : INK });
    }));
    (o.windows || (o.window ? [o.window] : [])).forEach((w, k) => {
      d.rect("w" + k, { x: x0 + w.c * cs - 2, y: y0 + w.r * cs - 2, width: (w.w || 1) * cs + 3, height: (w.h || 1) * cs + 3, fill: "none", stroke: w.color || GOLD, strokeWidth: 3, rx: 4 });
      if (w.label) d.text("wl" + k, x0 + w.c * cs, y0 + w.r * cs - 7, w.label, { fill: w.color || GOLD, fontSize: 12, fontWeight: 650 });
    });
    d.end();
    return { cell: cs, x0, y0 };
  }

  /* ---- V.curve: function curve with a ball, tangent and trail (optimisation, calculus, losses) ---- */
  function curve(id, o) {
    o = o || {};
    const f = typeof o.f === "function" ? o.f : null, x0 = o.xmin === undefined ? -5 : o.xmin, x1 = o.xmax === undefined ? 5 : o.xmax;
    const pts = o.pts || (f ? Array.from({ length: 160 }, (_, i) => { const x = x0 + ((x1 - x0) * i) / 159; return [x, f(x)]; }) : []);
    const series = [{ name: o.name, pts, color: o.color || TEAL, width: 3 }];
    const points = [];
    const fy = (x) => (f ? f(x) : NaN);
    (o.trail || []).forEach((x, i, a) => { const y = fy(x); if (fin(y)) points.push({ x, y, r: 4, color: "rgba(226,184,107," + (0.25 + (0.6 * i) / Math.max(1, a.length)).toFixed(2) + ")" }); });
    if (o.tangent && f) {
      const x = o.tangent.x, h = 1e-4 * Math.max(1, Math.abs(x)), sl = fin(o.tangent.slope) ? o.tangent.slope : (f(x + h) - f(x - h)) / (2 * h), L = (x1 - x0) * 0.16;
      series.push({ name: o.tangent.label || "slope " + num(sl, 2), pts: [[x - L, f(x) - sl * L], [x + L, f(x) + sl * L]], color: GOLD, dash: true, width: 2 });
    }
    if (o.ball) { const y = fin(o.ball.y) ? o.ball.y : fy(o.ball.x); if (fin(y)) points.push({ x: o.ball.x, y, r: 9, color: o.ball.color || GOLD, label: o.ball.label }); }
    let ymin = o.ymin, ymax = o.ymax;
    if (ymin === undefined || ymax === undefined) { const ys = pts.map((p) => p[1]).filter(fin); if (ymin === undefined) ymin = Math.min(...ys); if (ymax === undefined) ymax = Math.max(...ys); }
    return line(id, series, Object.assign({}, o, { points, xmin: x0, xmax: x1, ymin, ymax }));
  }

  /* ---- V.waffle: population of dots split into groups (probability, base rates, Bayes) ---- */
  function waffle(id, o) {
    o = o || {};
    const G = o.groups || [], tot = Math.min(2000, G.reduce((a, g) => a + Math.max(0, Math.round(g.n || 0)), 0));
    const cols = o.cols || (tot > 400 ? 40 : tot > 100 ? 20 : 10), rows = Math.ceil(tot / cols) || 1;
    const top = o.title ? 28 : 6, cs = clamp(Math.floor(600 / cols), 6, 30), W = o.w || Math.max(320, cols * cs + 40), H = top + rows * cs + 24 + 22 * Math.ceil(G.length / 2);
    const d = diagram(id, W, H), x0 = (W - cols * cs) / 2;
    if (o.title) d.text("title", W / 2, 18, o.title, { textAnchor: "middle", fontWeight: 650, fill: GOLD });
    let k = 0;
    G.forEach((g, gi) => { for (let q = 0; q < Math.round(g.n || 0) && k < tot; q++, k++) d.circle("d" + k, { cx: x0 + (k % cols) * cs + cs / 2, cy: top + 8 + Math.floor(k / cols) * cs + cs / 2, r: cs * 0.38, fill: g.color || color(gi) }); });
    G.forEach((g, gi) => {
      const lx = gi % 2 === 0 ? W * 0.08 : W * 0.54, ly = top + rows * cs + 30 + 22 * Math.floor(gi / 2);
      d.circle("lg" + gi, { cx: lx, cy: ly - 4, r: 6, fill: g.color || color(gi) });
      d.text("lgt" + gi, lx + 12, ly, (g.label || "group " + (gi + 1)) + ": " + Math.round(g.n || 0), { fontSize: 13, fill: INK });
    });
    d.end();
    return d;
  }

  /* ---- V.transform: the plane warped by a 2x2 matrix (3b1b linear-algebra view) ---- */
  function transform(id, o) {
    o = o || {};
    const M = o.M || [[1, 0], [0, 1]], t = o.t === undefined ? 1 : clamp(o.t, 0, 1);
    const a = 1 + (M[0][0] - 1) * t, b = M[0][1] * t, c = M[1][0] * t, e = 1 + (M[1][1] - 1) * t;
    const ap = (x, y) => [a * x + b * y, c * x + e * y];
    const n = o.n || 3, lines = [];
    for (let k = -n; k <= n; k++) { const p = ap(k, -n), q = ap(k, n), r = ap(-n, k), s = ap(n, k); lines.push({ x1: p[0], y1: p[1], x2: q[0], y2: q[1], color: "rgba(79,179,191,.35)", dash: false, width: 1 }, { x1: r[0], y1: r[1], x2: s[0], y2: s[1], color: "rgba(79,179,191,.35)", dash: false, width: 1 }); }
    const i1 = ap(1, 0), j1 = ap(0, 1);
    const vecs = [{ x: i1[0], y: i1[1], label: "î", color: GOLD }, { x: j1[0], y: j1[1], label: "ĵ", color: CORAL }].concat((o.vectors || []).map((v, k) => { const p = ap(v.x, v.y); return Object.assign({}, v, { x: p[0], y: p[1], color: v.color || color(k + 2) }); }));
    return space(id, Object.assign({ xmin: -n - 0.5, xmax: n + 0.5, ymin: -n - 0.5, ymax: n + 0.5 }, o, { vectors: vecs, lines: lines.concat(o.lines || []), grid: o.grid === undefined ? false : o.grid }));
  }

  /* write into an editable grid cell (for drag callbacks) */
  function setCell(gridId, i, j, v) {
    const h = host(gridId); if (!h) return;
    const inp = h.querySelector("input[data-i='" + i + "'][data-j='" + j + "']");
    if (inp) inp.value = +(+v).toFixed(3);
  }

  Object.assign(V, { space, network, graph, flow, pixels, curve, waffle, transform, setCell });
})();
