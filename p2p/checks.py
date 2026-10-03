"""Deterministic checks on generated blocks: static HTML/content checks + executing the JS in QuickJS
against a stub DOM built from the generated HTML. No LLM calls."""
import html as H
import json
import os
import re
from html.parser import HTMLParser

from . import latex

try:
    import quickjs
except Exception:  # pragma: no cover - checks degrade gracefully
    quickjs = None


class _Collect(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.els, self.dups, self.tags = {}, [], []
        self._select = None

    def handle_starttag(self, tag, attrs):
        a = {k: (v if v is not None else "") for k, v in attrs}
        self.tags.append((tag, a))
        if tag == "option" and self._select is not None:
            sel = self.els.get(self._select)
            if sel is not None:
                v = a.get("value", "")
                if not sel["options"] or "selected" in a:
                    sel["value"] = v
                sel["options"].append(v)
        if "id" in a:
            i = a["id"]
            if i in self.els:
                self.dups.append(i)
            rec = {"tag": tag, "attrs": a, "value": a.get("value", ""), "options": []}
            if tag == "input" and a.get("type") == "range" and "value" not in a:
                try:
                    rec["value"] = str((float(a.get("min", 0)) + float(a.get("max", 100))) / 2)
                except ValueError:
                    pass
            self.els[i] = rec
            if tag == "select":
                self._select = i

    def handle_endtag(self, tag):
        if tag == "select":
            self._select = None


def parse_html(html):
    p = _Collect()
    try:
        p.feed(html or "")
    except Exception:
        pass
    return p


TEMPLATE_IDS = (["play", "source", "selftest", "live", "livebox", "learnbar", "errors", "tests", "track", "deck", "explore-src",
                 "intro-cards", "prev", "next", "dots", "counter", "bar", "flowbtn"]
                + [f"slide-viz-{i}" for i in range(12)] + [f"slide-ctrls-{i}" for i in range(12)] + [f"xviz-{i}" for i in range(8)])

EXTERNAL = [
    (r"<script[^>]*\bsrc\s*=", "external <script src>"),
    (r"<link\b[^>]*>", "<link> tag"),
    (r"@import", "CSS @import"),
    (r"url\(\s*['\"]?\s*https?:", "remote url() in CSS"),
    (r"<(img|iframe|video|audio|source|embed|object)\b[^>]*\bsrc\s*=\s*['\"]?\s*(https?:)?//", "remote media"),
    (r"\bfetch\s*\(", "fetch()"),
    (r"XMLHttpRequest", "XMLHttpRequest"),
    (r"\bimport\s*\(|^\s*import\s", "JS import"),
]


def sanitize(blocks):
    """Auto-fixes that need no LLM: strip external resource tags and stray scripts from HTML blocks."""
    fixes = []
    for k in ("INTRO", "PLAYGROUND", "EXPLORE", "GROUNDING"):
        v = blocks.get(k, "")
        n = re.sub(r"<script\b[\s\S]*?</script>", "", v, flags=re.I)
        n = re.sub(r"<link\b[^>]*>", "", n, flags=re.I)
        if n != v:
            fixes.append(f"removed script/link tags from {k}")
            blocks[k] = n
    for k in ("INTRO", "PLAYGROUND", "EXPLORE", "GROUNDING"):
        v, n_m = latex.fix_html(blocks.get(k, ""))
        if n_m:
            fixes.append(f"converted {n_m} LaTeX spans to HTML in {k}")
            blocks[k] = v
    v, n_m = latex.fix_js(blocks.get("UI", ""))
    if n_m:
        fixes.append(f"converted {n_m} LaTeX spans to HTML in UI strings")
        blocks["UI"] = v
    ui, pg = blocks.get("UI", ""), blocks.get("PLAYGROUND", "")
    if ui and pg:
        known = set(parse_html("".join(blocks.get(k, "") for k in ("INTRO", "PLAYGROUND", "EXPLORE", "GROUNDING"))).els) | set(TEMPLATE_IDS)
        draw = set(re.findall(r"V\.(?:bars|line|matrix|table|diagram|editGrid)\(\s*['\"]([\w-]+)['\"]", ui))
        draw |= set(re.findall(r"V\.\$\(\s*['\"]([\w-]+)['\"]\s*\)\.(?:innerHTML|textContent)\s*=", ui))
        miss = sorted(i for i in draw - known if not re.search(r"id\s*=\s*\\?['\"]" + re.escape(i), ui))
        if miss:
            blocks["PLAYGROUND"] = pg + "\n<div class=\"auto-viz\">" + "".join(f'<div class="viz" id="{i}"></div>' for i in miss) + "</div>"
            fixes.append(f"created missing display containers {miss}")
    decl = re.compile(r"^(?:const|let|var|function)\s+([A-Za-z_$][\w$]*)", re.M)
    model_names = set(decl.findall(blocks.get("MODEL", "")))
    lines, dropped = blocks.get("UI", "").split("\n"), []
    for i, line in enumerate(lines):
        m = re.match(r"^(const|let|var)\s+([A-Za-z_$][\w$]*)\s*=.*;\s*(//.*)?$", line)
        if m and m.group(2) in model_names:
            lines[i] = "/* duplicate of MODEL declaration removed: " + line.replace("*/", "") + " */"
            dropped.append(m.group(2))
    if dropped:
        blocks["UI"] = "\n".join(lines)
        fixes.append(f"removed UI re-declarations of MODEL names {dropped}")
    for k in ("MODEL", "UI"):
        v = blocks.get(k, "")
        n = re.sub(r"^\s*</?script[^>]*>\s*$", "", v, flags=re.I | re.M)
        if n != v:
            fixes.append(f"removed <script> wrapper from {k}")
            blocks[k] = n
    return fixes


# ---------------------------------------------------------------- JS harness
STUB = r"""
var __E = [], __W = [], __ids = {}, __grids = {}, __texts = [], __listeners = 0;
function __err(m){ if (__E.length < 40 && __E.indexOf(m) < 0) __E.push(m); }
function __warn(m){ if (__W.length < 40 && __W.indexOf(m) < 0) __W.push(m); }
function __absorb(name){ var f = function(){}; return new Proxy(f, {
  get: function(t,k){ if (k === Symbol.toPrimitive) return function(){ return 0; }; if (k === Symbol.iterator) return function*(){};
    if (k === 'length') return 0; if (k === 'then') return undefined; if (k === 'toString' || k === 'valueOf') return function(){ return ''; };
    return __absorb(name + '.' + String(k)); },
  set: function(){ return true; }, apply: function(){ return __absorb(name + '()'); }, construct: function(){ return __absorb('new ' + name); } }); }
function __attr(s, n){ var m = new RegExp('\\b' + n + '\\s*=\\s*(?:"([^"]*)"|\'([^\']*)\'|([^\\s>]+))', 'i').exec(s); return m ? (m[1] !== undefined ? m[1] : m[2] !== undefined ? m[2] : m[3]) : undefined; }
function __scanHTML(h){ h = String(h); __texts.push(h);
  var re = /<(\w+)([^>]*?)\bid\s*=\s*["']([^"']+)["']([^>]*)>/g, m;
  while ((m = re.exec(h))) { var a = m[2] + ' ' + m[4]; var o = {tag: m[1].toLowerCase(), attrs: {type: __attr(a,'type')||'', min: __attr(a,'min'), max: __attr(a,'max'), step: __attr(a,'step')}, value: __attr(a,'value') || ''};
    if (/\bchecked\b/i.test(a)) o.checked = true; __mk(m[3], o); } }
function __snap(v, a){ if (a.type !== 'range') return v; var x = parseFloat(v); if (!isFinite(x)) return v;
  var lo = a.min !== undefined && a.min !== '' ? parseFloat(a.min) : 0, hi = a.max !== undefined && a.max !== '' ? parseFloat(a.max) : 100;
  var st = a.step === 'any' ? 0 : (a.step !== undefined && a.step !== '' ? parseFloat(a.step) : 1);
  x = Math.min(hi, Math.max(lo, x)); if (st > 0) x = lo + Math.round((x - lo) / st) * st; x = Math.min(hi, Math.max(lo, x));
  return String(+x.toFixed(10)); }
function __El(rec){
  rec = rec || {tag: 'div', attrs: {}, value: ''};
  var a = rec.attrs || {};
  var st = {tagName: (rec.tag || 'div').toUpperCase(), value: String(rec.value === undefined ? '' : rec.value), checked: !!(rec.checked || a.checked !== undefined && rec.tag === 'input' && a.type === 'checkbox' && a.checked !== false),
    type: a.type || (rec.tag === 'select' ? 'select-one' : ''), textContent: '', innerHTML: '', dataset: {}, style: {}, id: rec.id || '', disabled: false, min: a.min, max: a.max, step: a.step};
  var p;
  var meth = {
    getAttribute: function(k){ return a[k] === undefined ? null : a[k]; },
    setAttribute: function(k, v){ a[k] = String(v); if (k === 'id') __ids[v] = p; if (k === 'value' || k === 'min' || k === 'max' || k === 'step' || k === 'type') st[k] = String(v); },
    addEventListener: function(){ __listeners++; }, removeEventListener: function(){},
    querySelectorAll: function(){ return []; }, querySelector: function(){ return __absorb('qs'); }, closest: function(){ return __absorb('closest'); },
    appendChild: function(c){ return c; }, append: function(){}, prepend: function(){}, after: function(){}, before: function(){}, remove: function(){}, replaceChildren: function(){},
    insertAdjacentHTML: function(pos, h){ __scanHTML(h); }, matches: function(){ return false; }, contains: function(){ return false; }, focus: function(){}, blur: function(){}, dispatchEvent: function(){ return true; },
    getBoundingClientRect: function(){ return {x:0,y:0,width:600,height:300,left:0,top:0,right:600,bottom:300}; }, getContext: function(){ return __absorb('ctx'); }
  };
  p = new Proxy(st, {
    get: function(t, k){ if (k in meth) return meth[k]; if (k === 'valueAsNumber') return parseFloat(st.value); if (k === 'options') return []; if (k === 'children' || k === 'childNodes') return [];
      if (k === 'classList') return {add: function(){}, remove: function(){}, toggle: function(){}, contains: function(){ return false; }};
      if (k in st) return st[k]; return __absorb(st.tagName + '.' + String(k)); },
    set: function(t, k, v){ if (k === 'value') v = __snap(String(v), {type: st.type, min: st.min, max: st.max, step: st.step});
      st[k] = v; if (k === 'id') __ids[v] = p; if (k === 'innerHTML' || k === 'outerHTML') __scanHTML(v); if (k === 'textContent' || k === 'innerText') __texts.push(String(v));
      if (k.slice && k.slice(0,2) === 'on' && typeof v === 'function') __listeners++; return true; } });
  return p;
}
function __mk(id, rec){ rec.id = id; var e = __El(rec); __ids[id] = e; return e; }
var document = {
  getElementById: function(id){ id = __resolve(id); if (id in __ids) return __ids[id]; __warn('getElementById: no element #' + id + ' (static HTML)'); return null; },
  querySelector: function(s){ var m = /^#([\w-]+)$/.exec(s); if (m) return document.getElementById(m[1]); return __absorb('qs'); }, querySelectorAll: function(){ return []; },
  createElement: function(t){ return __El({tag: t, attrs: {}, value: ''}); }, createElementNS: function(n, t){ return __El({tag: t, attrs: {}, value: ''}); },
  createTextNode: function(){ return __absorb('text'); }, addEventListener: function(){}, body: __absorb('body'), documentElement: __absorb('html'), activeElement: null };
var window = globalThis; globalThis.addEventListener = function(){};
var requestAnimationFrame = function(){ return 0; }, cancelAnimationFrame = function(){}, setTimeout = function(){ return 0; }, clearTimeout = function(){}, setInterval = function(){ return 0; }, clearInterval = function(){};
var performance = {now: function(){ return 0; }}, console = {log: function(){}, warn: function(){}, error: function(){}, info: function(){}}, alert = function(){}, getComputedStyle = function(){ return __absorb('cs'); };
function __close(a, b, tol){ if (Array.isArray(a) || Array.isArray(b)) return Array.isArray(a) && Array.isArray(b) && a.length === b.length && a.every(function(x, i){ return __close(x, b[i], tol); });
  if (typeof a === 'number' && typeof b === 'number') return Math.abs(a - b) <= tol; return a === b; }
function __fin(x){ return typeof x === 'number' && isFinite(x); }
var __drawn = {};
function __resolve(id){ id = String(id); if (id in __ids || !/^(slide-viz|xviz)-/.test(id)) return id;
  for (var cut = id.lastIndexOf('-'); cut > 0; cut = id.lastIndexOf('-', cut - 1)) if (id.slice(0, cut) in __ids) { __mk(id, {tag: 'div', attrs: {}, value: ''}); return id; }
  return id; }
function __need(id, f){ id = __resolve(id); __drawn[id] = 1; if (!(id in __ids)) __err(f + "('" + id + "'): no element with that id" + (String(id).length <= 2 ? " (a 1-character id usually means a string was destructured: V.split returns an ARRAY of ids, use const [a, b] = V.split(id, 2))" : "")); }
var V = (function(){
  var $ = function(id){ return document.getElementById(id); };
  function fmt(x, d){ d = d === undefined ? 3 : d; if (typeof x !== 'number') return String(x); if (isNaN(x)) return 'NaN'; if (!isFinite(x)) return x > 0 ? '∞' : '−∞'; return x.toFixed(d); }
  function num(id){ var e = $(id); if (!e) return NaN; return e.type === 'checkbox' ? (e.checked ? 1 : 0) : parseFloat(e.value); }
  function val(id){ var e = $(id); return !e ? undefined : e.type === 'checkbox' ? e.checked : e.value; }
  function set(id, v){ var e = $(id); if (!e) { __err("V.set('" + id + "'): no element with that id"); return; } if (v === undefined) return; if (e.type === 'checkbox') e.checked = !!v; else e.value = v; }
  function split(id, n){ id = String(id); __need(id, 'V.split'); var out = []; for (var i = 0; i < n; i++) { (function(cid){ __mk(cid, {tag: 'div', attrs: {}, value: ''}); out.push({id: cid, toString: function(){ return cid; }, valueOf: function(){ return cid; }}); })(id + '-' + i); } return out; }
  function geo(f, a){ for (var k in a) { if (/^(x|y|x1|y1|x2|y2|cx|cy|r|rx|ry|width|height)$/.test(k) && !__fin(a[k])) __err(f + ': attribute ' + k + ' is ' + a[k]); if (k === 'd' && /NaN|undefined|Infinity/.test(String(a[k]))) __err(f + ': path d contains NaN/undefined'); } }
  function diagram(id, w, h){ __need(id, 'V.diagram'); w = w || 640; h = h || 360;
    function tag(t, k){ return "V.diagram('" + id + "') d." + t + "('" + k + "')"; }
    function inb(k, xs, ys){ var m = 4; xs.forEach(function(x){ if (__fin(x) && (x < -m || x > w + m)) __warn("V.diagram('" + id + "') draws '" + k + "' at x=" + Math.round(x) + ', outside its viewBox width ' + w + ' (it will be clipped): enlarge w or rescale'); });
      ys.forEach(function(y){ if (__fin(y) && (y < -m || y > h + m)) __warn("V.diagram('" + id + "') draws '" + k + "' at y=" + Math.round(y) + ', outside its viewBox height ' + h + ' (it will be clipped): enlarge h or rescale'); }); }
    function pos(names, args){ if (typeof args[0] !== 'number') return args[0] || {}; var o = Object.assign({}, args[names.length] || {}); names.forEach(function(n, i){ o[n] = args[i]; }); return o; }
    var d = {w: w, h: h, width: w, height: h,
    rect: function(k){ var a = pos(['x', 'y', 'width', 'height'], [].slice.call(arguments, 1)); geo(tag('rect', k), a); inb(k, [a.x, (a.x || 0) + (a.width || 0)], [a.y, (a.y || 0) + (a.height || 0)]); },
    circle: function(k){ var a = pos(['cx', 'cy', 'r'], [].slice.call(arguments, 1)); geo(tag('circle', k), a); inb(k, [a.cx], [a.cy]); },
    line: function(k){ var a = pos(['x1', 'y1', 'x2', 'y2'], [].slice.call(arguments, 1)); geo(tag('line', k), a); inb(k, [a.x1, a.x2], [a.y1, a.y2]); },
    path: function(k, a){ geo(tag('path', k), a || {}); },
    text: function(k, x, y, s, a){ geo(tag('text', k), {x: x, y: y}); inb(k, [x], [y]); if (/NaN|undefined/.test(String(s))) __err('d.text shows "' + s + '"');
      a = a || {}; var fs = +(a.fontSize || a['font-size'] || 13) || 13, anc = a.textAnchor || a['text-anchor'] || 'start';
      var tw = String(s).replace(/<[^>]*>/g, '').length * fs * 0.56, x0 = anc === 'middle' ? x - tw / 2 : anc === 'end' ? x - tw : x;
      if (__fin(x) && !a.transform && (x0 < -6 || x0 + tw > w + 6)) __warn("V.diagram('" + id + "') label '" + String(s).slice(0, 30) + "' (~" + Math.round(tw) + 'px wide at x=' + Math.round(x) + ', anchor ' + anc + ') overflows the ' + w + 'px viewBox: shorten it, move it, or enlarge w'); },
    arrow: function(k, x1, y1, x2, y2){ geo(tag('arrow', k), {x1: x1, y1: y1, x2: x2, y2: y2}); inb(k, [x1, x2], [y1, y2]); }, end: function(){}, svg: __absorb('svg') };
    return new Proxy(d, {get: function(t, k){ if (k in t || typeof k === 'symbol') return t[k];
      __err("V.diagram(...) has no member '" + String(k) + "' (it has only w, h, rect, circle, line, path, text, arrow, end). For coordinate maps use V.scale(d0, d1, r0, r1) which returns a function; V.line returns X/Y maps for plots.");
      return function(){ return 0; }; }}); }
  function bars(id, items, o){ __need(id, 'V.bars'); if (!Array.isArray(items)) { __err('V.bars: items must be an array'); return; }
    items.forEach(function(it, i){ if (!it || !__fin(it.value)) __err("V.bars('" + id + "'): item " + i + ' has value=' + (it && it.value) + ' (keys: ' + (it ? Object.keys(it).join(',') : '') + '). Signature: V.bars(id, [{label, value: finite number, color?}, ...], opts) draws ONE bar per item; for two quantities use two charts or interleave items.'); }); }
  function line(id, series, o){ __need(id, 'V.line'); if (!Array.isArray(series)) { __err('V.line: series must be an array'); return {X: function(){return 0;}, Y: function(){return 0;}}; }
    series.forEach(function(s, i){ if (!s || !Array.isArray(s.pts)) { __err("V.line('" + id + "'): series " + i + ' has no pts array (keys: ' + (s ? Object.keys(s).join(',') : '') + '). Signature: V.line(id, [{name?, pts: [[x, y], ...], color?, dash?, dots?}], opts)'); return; }
      var bad = s.pts.filter(function(p){ return !Array.isArray(p) || !__fin(p[0]) || !__fin(p[1]); }).length;
      if (bad === s.pts.length && bad > 0) __err("V.line('" + id + "'): series " + i + ' has no finite points'); else if (bad) __warn("V.line('" + id + "'): series " + i + ' has ' + bad + ' non-finite points'); });
    return {X: function(){ return 0; }, Y: function(){ return 0; }}; }
  function matrix(id, M, o){ __need(id, 'V.matrix'); if (!Array.isArray(M) || !M.every(Array.isArray)) { __err("V.matrix('" + id + "'): M is not a 2-D array of numbers. Signature: V.matrix(id, [[...], ...], {rows, cols, digits, title})"); return; }
    M.forEach(function(r, i){ r.forEach(function(v, j){ if (typeof v === 'number' && !isFinite(v)) __err("V.matrix('" + id + "'): cell [" + i + ',' + j + '] is ' + v); }); }); }
  function editGrid(id, M, o){ __need(id, 'V.editGrid'); if (!Array.isArray(M)) { __err("V.editGrid('" + id + "'): M must be an array (1-D or 2-D)"); return; }
    __grids[id] = M.map(function(r){ return Array.isArray(r) ? r.map(Number) : Number(r); }); }
  function readGrid(id){ return (__grids[id] || []).map(function(r){ return Array.isArray(r) ? r.slice() : r; }); }
  function table(id, head, rows){ __need(id, 'V.table'); if (!Array.isArray(rows)) __err('V.table: rows must be an array'); else rows.forEach(function(r){ (r || []).forEach(function(v){ if (typeof v === 'number' && !isFinite(v)) __err("V.table('" + id + "') shows " + v); }); }); }
  function resize(M, rows, cols, fill){ fill = fill === undefined ? 0 : fill; var A = Array.isArray(M) ? M : [], out = [], i, j;
    for (i = 0; i < rows; i++) { if (cols === undefined) out.push(A[i] === undefined || A[i] === null ? fill : A[i]);
      else { var row = []; for (j = 0; j < cols; j++) row.push(Array.isArray(A[i]) && A[i][j] !== undefined && A[i][j] !== null ? A[i][j] : fill); out.push(row); } } return out; }
  var api = {$: $, fmt: fmt, num: num, val: val, set: set, clamp: function(x, a, b){ return Math.min(b, Math.max(a, x)); }, color: function(){ return '#000'; },
    diagram: diagram, bars: bars, line: line, matrix: matrix, editGrid: editGrid, readGrid: readGrid, table: table, ticks: function(){ return [0, 1]; }, resize: resize, split: split, scale: function(d0, d1, r0, r1){ return function(v){ return r0 + ((v - d0) / ((d1 - d0) || 1)) * (r1 - r0); }; }, stage: Infinity, syncOut: function(){}, update: function(){}, apply: function(){} };
  return new Proxy(api, {get: function(t, k){ if (k in t || typeof k === 'symbol') return t[k];
    __err('V.' + String(k) + ' does not exist in the helper library (available: $, fmt, num, val, set, clamp, color, resize, split, scale, bars, line, matrix, editGrid, readGrid, table, diagram). The template already shows invariants() and TESTS; do not render them yourself.');
    return function(){ return ''; }; }});
})();
"""

HARNESS = r"""
(function(){
  var R = {tests: [], info: {}};
  function has(n){ try { return typeof eval(n) !== 'undefined'; } catch (e) { return false; } }
  function msg(e){ return (e && e.message ? e.message : String(e)) + (e && e.stack ? ' @ ' + String(e.stack).split('\n').slice(0, 2).join(' ').trim() : ''); }
  function nonfinite(o, path, out){ out = out || [];
    if (typeof o === 'number') { if (!isFinite(o)) out.push(path + '=' + o); }
    else if (Array.isArray(o)) o.forEach(function(v, i){ nonfinite(v, path + '[' + i + ']', out); });
    else if (o && typeof o === 'object') for (var k in o) nonfinite(o[k], path + '.' + k, out);
    return out; }
  ['DEFAULT_STATE', 'compute', 'TESTS', 'PRESETS', 'invariants'].forEach(function(n){ if (!has(n)) __err('MODEL: ' + n + ' is not defined'); });
  ['readState', 'setState', 'render'].forEach(function(n){ if (!has(n)) __err('UI: function ' + n + ' is not defined'); });
  if (!has('compute') || !has('DEFAULT_STATE')) return JSON.stringify({E: __E, W: __W, R: R});
  var S0 = DEFAULT_STATE;
  function full(s){ return Object.assign({}, S0, s || {}); }
  function cmp(label, s){
    var r; try { r = compute(full(s)); } catch (e) { __err('compute(' + label + ') threw: ' + msg(e)); return null; }
    if (!r || typeof r !== 'object') { __err('compute(' + label + ') must return an object'); return null; }
    var nf = nonfinite(r, 'r'); if (nf.length) __err('compute(' + label + ') gives non-finite values: ' + nf.slice(0, 4).join(', '));
    if (has('invariants')) { try { (invariants(full(s), r) || []).forEach(function(c){ if (!c.ok) __err('invariant "' + c.label + '" fails for ' + label + (c.detail ? ' (' + c.detail + ')' : '')); }); } catch (e) { __err('invariants(' + label + ') threw: ' + msg(e)); } }
    return r; }
  var r0 = cmp('DEFAULT_STATE', S0);
  if (r0) R.info.default_result_keys = Object.keys(r0).slice(0, 20);
  var P = has('PRESETS') ? PRESETS : {};
  Object.keys(P).forEach(function(k){ cmp('PRESETS.' + k, P[k]); });
  if (has('TESTS')) { if (!Array.isArray(TESTS) || TESTS.length < 2) __err('TESTS must be an array with >= 2 cases');
    (TESTS || []).forEach(function(t, i){ var name = (t && t.name) || ('#' + i), got, ok = false;
      try { var st = full(t.state); got = t.get(compute(st), st); var tol = t.tol === undefined ? 1e-6 : t.tol; ok = __close(got, t.expect, tol); }
      catch (e) { __err('TEST "' + name + '" threw: ' + msg(e)); }
      R.tests.push({name: name, got: got, expect: t && t.expect, ok: ok});
      if (!ok && got !== undefined) __err('TEST "' + name + '" failed: computed ' + JSON.stringify(got) + ', expected ' + JSON.stringify(t && t.expect) + ' with tol ' + (t.tol === undefined ? 1e-6 : t.tol) + ' (recompute the expected value by hand from the equation: either compute() or the expectation is wrong)'); }); }
  if (has('step') && typeof step === 'function') { var s = full(S0), n = 0;
    try { for (; n < 60; n++) { var nx = step(Object.assign({}, s)); if (!nx) break; s = full(nx); } var nf = nonfinite(s, 'state'); if (nf.length) __err('step() produces non-finite state after ' + n + ' iterations: ' + nf.slice(0, 3).join(', ')); R.info.step_iters = n; }
    catch (e) { __err('step() threw: ' + msg(e)); } }
  var used = __PRESET_KEYS__; used.forEach(function(k){ if (!(k in P)) __err('EXPLORE button uses data-preset="' + k + '" but PRESETS has no such key'); });
  if (!has('readState') || !has('setState') || !has('render')) return JSON.stringify({E: __E, W: __W, R: R});
  function same(a, b){ if (typeof a === 'number' && typeof b === 'number') return Math.abs(a - b) <= 1e-6 * Math.max(1, Math.abs(a));
    if (Array.isArray(a) && Array.isArray(b)) return a.length === b.length && a.every(function(v, i){ return same(v, b[i]); });
    if (typeof a === 'boolean' || typeof b === 'boolean') return !!a === !!b; return String(a) === String(b); }
  function apply(label, s){
    var st = full(s), rd;
    try { if (has('init') && typeof init === 'function' && label === 'DEFAULT_STATE') init(); } catch (e) { __err('init() threw: ' + msg(e)); }
    try { setState(st); } catch (e) { __err('setState(' + label + ') threw: ' + msg(e)); return; }
    try { rd = readState(); } catch (e) { __err('readState() after ' + label + ' threw: ' + msg(e)); return; }
    if (!rd || typeof rd !== 'object') { __err('readState() must return an object'); return; }
    Object.keys(s || {}).forEach(function(k){ if (k in rd && !same(s[k], rd[k])) (typeof s[k] === 'number' && typeof rd[k] === 'number' && Math.abs(s[k] - rd[k]) <= 0.02 * Math.max(1, Math.abs(s[k])) ? __warn : __err)(label + ': setState then readState gives ' + k + '=' + JSON.stringify(rd[k]) + ' instead of ' + JSON.stringify(s[k]) + ' (control not written, or value outside the slider min/max/step)'); });
    var cur = full(Object.assign({}, st, rd)), r;
    try { r = compute(cur); } catch (e) { __err('compute(readState() after ' + label + ') threw: ' + msg(e)); return; }
    try { render(cur, r); } catch (e) { __err('render(' + label + ') threw: ' + msg(e)); } }
  apply('DEFAULT_STATE', S0);
  try { setState(full(S0)); render(full(readState()), compute(full(readState()))); } catch (e) {}
  Object.keys(P).forEach(function(k){ apply('PRESETS.' + k, P[k]); });
  R.info.state_keys = Object.keys(S0);
  var CT = __CTRLS__;
  CT.forEach(function(c){
    var vals = c.tag === 'select' ? c.options : c.type === 'checkbox' ? [true, false] : [c.min, c.max].filter(function(v){ return v !== undefined && v !== null && v !== ''; });
    vals.forEach(function(v){
      try { setState(full(S0)); } catch (e) { return; }
      var el = __ids[c.id]; if (!el) return;
      if (c.type === 'checkbox') el.checked = v; else el.value = String(v);
      var lab = 'control #' + c.id + ' = ' + v, rd, cur, r;
      try { rd = readState(); } catch (e) { __err('readState() threw after setting ' + lab + ': ' + msg(e)); return; }
      cur = full(Object.assign({}, rd));
      r = cmp(lab, cur); if (!r) return;
      try { render(cur, r); } catch (e) { __err('render threw after setting ' + lab + ': ' + msg(e)); }
      try { var rd2 = readState(), c2 = full(rd2), r2 = compute(c2); render(c2, r2); } catch (e) { __err('second update after setting ' + lab + ' threw (controls rebuilt inconsistently?): ' + msg(e)); }
    }); });
  try { setState(full(S0)); } catch (e) {}
  if (!has('SLIDES') || !Array.isArray(SLIDES)) __err('UI: SLIDES array is not defined (the lesson needs 4-7 visual slides)');
  else {
    if (SLIDES.length < 3) __err('SLIDES has only ' + SLIDES.length + ' slides; the lesson needs 4-7 (primitives first, then integration)');
    SLIDES.forEach(function(sl, i){
      if (!sl || typeof sl.draw !== 'function') { __err('SLIDES[' + i + '] has no draw(id, s, r) function'); return; }
      if (!sl.title) __warn('SLIDES[' + i + '] has no title');
      if (sl.text && String(sl.text).replace(/<[^>]*>/g, '').split(/\s+/).length > 110) __warn('SLIDES[' + i + '] text is long; keep <= 60 words');
      if (sl.preset && !(sl.preset in P)) __err('SLIDES[' + i + '] uses unknown preset ' + sl.preset);
      (sl.controls || []).forEach(function(id){ if (!(id in __ids)) __err('SLIDES[' + i + '].controls lists #' + id + ' but no PLAYGROUND element has that id'); });
      var states = [['DEFAULT_STATE', S0]].concat(Object.keys(P).map(function(k){ return ['PRESETS.' + k, P[k]]; }));
      states.forEach(function(st){ var c = full(st[1]), r; try { r = compute(c); } catch (e) { return; }
        try { sl.draw('slide-viz-' + i, c, r); } catch (e) { __err('SLIDES[' + i + '].draw threw at ' + st[0] + ': ' + msg(e)); } });
      var pre = 'slide-viz-' + i;
      if (!Object.keys(__drawn).some(function(k){ return k === pre || k.indexOf(pre + '-') === 0; })) __err('SLIDES[' + i + '].draw draws nothing into its container "' + pre + '" (every slide needs a visual made with V helpers)');
    });
    R.info.slides = SLIDES.length;
    (__XSHOW__).forEach(function(x){
      if (x.k === null) return;
      if (!(x.k >= 0 && x.k < SLIDES.length)) __err('EXPLORE card data-show-slide="' + x.k + '" is not a valid 0-based SLIDES index (0..' + (SLIDES.length - 1) + ')');
      if (x.p && !(x.p in P)) __err('EXPLORE card data-show-preset="' + x.p + '" is not a PRESETS key');
    });
  }
  (__CALCS__).forEach(function(c){
    var st = full(c.at ? P[c.at] : S0), r, v;
    if (c.at && !(c.at in P)) { __err('calc span data-at="' + c.at + '" is not a PRESETS key'); return; }
    try { r = compute(st); v = (new Function('r', 's', 'return (' + c.get + ');'))(r, st); } catch (e) { __err('calc span data-get="' + c.get + '" fails: ' + msg(e)); return; }
    var flat = Array.isArray(v) ? [].concat.apply([], v.map(function(x){ return Array.isArray(x) ? x : [x]; })) : [v];
    if (!flat.length || flat.some(function(x){ return typeof x !== 'number' || !isFinite(x); })) __err('calc span data-get="' + c.get + '"' + (c.at ? ' at preset ' + c.at : '') + ' gives ' + JSON.stringify(v) + ' (must be a finite number, vector or matrix)'); });
  var bad = __texts.filter(function(t){ return /\bNaN\b|\bundefined\b|\[object Object\]/.test(t); });
  if (bad.length) __err('page text shows NaN/undefined/[object Object], e.g. "' + bad[0].replace(/<[^>]+>/g, ' ').replace(/\s+/g, ' ').slice(0, 120) + '"');
  R.info.presets = Object.keys(P); R.info.has_step = has('step'); R.info.dynamic_ids = Object.keys(__ids).length;
  return JSON.stringify({E: __E, W: __W, R: R});
})()
"""


def _u8(t):
    """QuickJS hands strings back as latin-1-decoded UTF-8 bytes; repair them."""
    try:
        return t.encode("latin-1").decode("utf-8")
    except (UnicodeEncodeError, UnicodeDecodeError):
        return t


def _quote(code, err):
    """Append the offending source line(s) to a JS error so the repair can locate it."""
    m = re.search(r"<input>:(\d+)", err)
    if not m:
        return ""
    n, lines = int(m.group(1)), code.split("\n")
    if not 0 < n <= len(lines):
        return ""
    return " | line " + str(n) + ": " + lines[n - 1].strip()[:160]


def run_js(blocks, els, preset_keys, calcs=None, xshow=None, time_limit=4):
    """Execute MODEL+UI in QuickJS against a stub DOM. Returns (errors, warnings, report)."""
    if quickjs is None:
        return [], ["quickjs not available: JS execution checks skipped"], {}
    ctx = quickjs.Context()
    ctx.set_time_limit(time_limit)
    ctx.set_memory_limit(256 * 1024 * 1024)
    errors = []
    ctx.eval(STUB)
    ctx.eval(open(os.path.join(os.path.dirname(__file__), "mathlib.js"), encoding="utf-8").read())
    init = {i: {"tag": "div", "attrs": {}, "value": ""} for i in TEMPLATE_IDS}
    init.update({i: {"tag": e["tag"], "attrs": e["attrs"], "value": e["value"],
                     "checked": "checked" in e["attrs"]} for i, e in els.items()})
    ctx.eval("(function(){var m=" + json.dumps(init) + ";for(var k in m) __mk(k,m[k]);})();")
    from .assemble import split_tests
    model, tests_js = split_tests(blocks.get("MODEL", ""))
    for name, code in (("MODEL", model), ("TESTS", tests_js), ("UI", blocks.get("UI", ""))):
        try:
            ctx.eval(code)
        except Exception as e:
            errors.append(f"{name if name != 'TESTS' else 'MODEL (TESTS)'} block failed to load: {_u8(str(e)).strip()[:300]}" + _quote(code, str(e)))
    if tests_js:
        te = ctx.eval("__TESTS_ERROR")
        if te:
            errors.append(f"MODEL: evaluating the TESTS array threw: {_u8(str(te))} — TESTS entries must be plain literals or functions (no references to s or r outside get())")
    try:
        ctrls = [{"id": i, "tag": e["tag"], "type": e["attrs"].get("type", ""), "min": e["attrs"].get("min"),
                  "max": e["attrs"].get("max"), "options": e["options"][:8]}
                 for i, e in els.items() if e["tag"] in ("input", "select") and e["attrs"].get("type", "text") in ("range", "number", "checkbox", "text") or e["tag"] == "select"]
        if not any(e["tag"] == "input" and e["attrs"].get("type") == "number" for e in els.values()):
            pass
        out = json.loads(_u8(ctx.eval(HARNESS.replace("__PRESET_KEYS__", json.dumps(preset_keys)).replace("__CTRLS__", json.dumps(ctrls))
                                  .replace("__CALCS__", json.dumps(calcs or []))
                                  .replace("__XSHOW__", json.dumps(xshow or [])))))
    except Exception as e:
        errors.append(f"execution harness aborted (infinite loop or crash?): {str(e).strip()[:300]}")
        return errors, [], {}
    codes = {"MODEL": model, "UI": blocks.get("UI", "")}

    def locate(e):
        m = re.search(r"at ([\w$.<>]+) \(<input>:(\d+)\)", e)
        if not m or "| line" in e:
            return e
        fn, n = m.group(1).split(".")[-1], int(m.group(2))
        if fn == "<anonymous>" or fn == "anonymous":
            blk = "UI" if re.search(r"render|draw|readState|setState|SLIDES", e) else "MODEL"
            lines = codes[blk].split("\n")
            return e + (" | " + blk + " line " + str(n) + ": " + lines[n - 1].strip()[:160] if 0 < n <= len(lines) else "")
        for code in codes.values():
            if re.search(r"(function\s+" + re.escape(fn) + r"\b|\b" + re.escape(fn) + r"\s*[:=]\s*(\(|function|async))", code):
                lines = code.split("\n")
                if 0 < n <= len(lines):
                    return e + " | line " + str(n) + ": " + lines[n - 1].strip()[:160]
        return e
    return errors + [locate(e) for e in out["E"]], out["W"], out["R"]


def static_checks(blocks):
    errors, warns = [], []
    for k in ("META", "INTRO", "PLAYGROUND", "MODEL", "UI", "EXPLORE", "GROUNDING"):
        if not blocks.get(k, "").strip():
            errors.append(f"block {k} is missing or empty")
    meta = {}
    try:
        meta = json.loads(blocks.get("META", "{}"))
        for f in ("title", "paper", "section"):
            if not str(meta.get(f, "")).strip():
                errors.append(f"META lacks '{f}'")
    except Exception as e:
        errors.append(f"META is not valid JSON: {e}")
    allhtml = "".join(blocks.get(k, "") for k in ("INTRO", "PLAYGROUND", "EXPLORE", "GROUNDING"))
    for k in ("INTRO", "PLAYGROUND", "EXPLORE", "GROUNDING", "MODEL", "UI"):
        for rx, what in EXTERNAL:
            if re.search(rx, blocks.get(k, ""), flags=re.I | re.M):
                errors.append(f"{k} uses a network/external resource ({what}); the page must be fully offline")
    m = re.search(r"\\{1,2}(?:frac|sqrt|sum|mathbf|mathrm|text|cdot|left|right|hat|alpha|beta|sigma|theta)\b", blocks.get("UI", ""))
    if m:
        errors.append(f"UI contains LaTeX ({m.group(0)!r}); nothing renders LaTeX here, use HTML <sub>/<sup>/Unicode")
    for k in ("INTRO", "PLAYGROUND", "EXPLORE", "GROUNDING"):
        m = re.search(r"\$[^$\n]{1,60}\$(?![{\w])|\\(?:frac|sqrt|sum|mathbf|mathrm|text|cdot|left|right)\b", re.sub(r"\$\{", "", blocks.get(k, "")))
        if m:
            errors.append(f"{k} contains LaTeX ({m.group(0)[:40]!r}); nothing renders LaTeX here, use HTML <sub>/<sup>/Unicode")
    intro = blocks.get("INTRO", "")
    if 'class="sym"' not in intro and "class='sym'" not in intro:
        errors.append('INTRO lacks the symbol table <table class="sym">')
    if 'class="eq"' not in intro and "class='eq'" not in intro:
        warns.append('INTRO has no <div class="eq"> equation')
    ex = blocks.get("EXPLORE", "")
    n_ex = len(re.findall(r"class=[\"'][^\"']*\bexplore\b", ex))
    if n_ex < 2:
        errors.append(f"EXPLORE has {n_ex} exploration cards; need exactly 2 (class=\"card explore\")")
    if not re.search(r"class=[\"'][^\"']*\bcaution\b", ex):
        errors.append("EXPLORE lacks the limitation/misunderstanding card (class=\"card caution\")")
    for w in ("Try", "Watch", "Why"):
        if ex.count(w) < 2:
            warns.append(f"explorations should each contain '{w}:'")
    xshow = []
    for tag, a in parse_html(ex).tags:
        if "card" in a.get("class", "").split():
            k = a.get("data-show-slide")
            try:
                k = int(k) if k is not None else None
            except ValueError:
                errors.append(f"EXPLORE data-show-slide={k!r} must be an integer")
                k = None
            xshow.append({"k": k, "p": a.get("data-show-preset", "")})
    if sum(1 for x in xshow if x["k"] is not None) < 2:
        warns.append("exploration cards should set data-show-slide/data-show-preset so their slides have a visual")
    gr = blocks.get("GROUNDING", "")
    if "from-paper" not in gr or "ours" not in gr:
        errors.append("GROUNDING must contain both the 'from-paper' and 'ours' cards")
    pg = parse_html(blocks.get("PLAYGROUND", ""))
    all_p = parse_html(allhtml)
    if all_p.dups:
        errors.append(f"duplicate element ids: {sorted(set(all_p.dups))[:6]}")
    n_ctrl = sum(1 for t, a in pg.tags if t in ("input", "select", "textarea"))
    n_ctrl += len(re.findall(r"V\.editGrid\s*\(", blocks.get("UI", "")))
    n_ctrl += len(re.findall(r"<input|<select", blocks.get("UI", "")))
    if n_ctrl < 2:
        errors.append(f"PLAYGROUND has {n_ctrl} controls; need at least 2 meaningful controls")
    for t, a in pg.tags:
        if t == "input" and a.get("type") == "range":
            try:
                lo, hi, v = float(a.get("min", 0)), float(a.get("max", 100)), float(a.get("value", "nan"))
                if not lo <= v <= hi:
                    warns.append(f"range #{a.get('id')} value {v} outside [{lo},{hi}]")
            except ValueError:
                pass
    # ids referenced literally in JS must exist (statically or created by JS)
    js = blocks.get("UI", "") + "\n" + blocks.get("MODEL", "")
    known = set(all_p.els) | set(TEMPLATE_IDS)
    for i in sorted(set(re.findall(r"(?:V\.\$|getElementById|V\.(?:num|val|set|bars|line|matrix|editGrid|readGrid|table|diagram))\(\s*['\"]([\w-]+)['\"]", js))):
        if i not in known and not re.search(r"id\s*=\s*\\?['\"]" + re.escape(i) + r"\\?['\"]|\.id\s*=\s*['\"]" + re.escape(i), js):
            errors.append(f"UI references #{i} but no element has id=\"{i}\"")
    calcs = []
    for tag, a in all_p.tags:
        if "data-get" in a:
            calcs.append({"get": H.unescape(a["data-get"]), "at": a.get("data-at", "")})
    n_calc_ex = len(re.findall(r"data-get=", ex))
    if n_calc_ex < 2:
        warns.append("explorations quote no computed values (use <span class=\"calc\" data-at=... data-get=...>)")
    preset_keys = sorted(set(re.findall(r"data-preset\s*=\s*['\"]([^'\"]+)['\"]", ex)))
    if len(preset_keys) < 2:
        warns.append("explorations should each have a data-preset 'Set this up' button")
    return errors, warns, all_p.els, preset_keys, meta, calcs, xshow


def check(blocks):
    """Run all checks. Returns dict with errors, warnings, report."""
    errors, warns, els, preset_keys, meta, calcs, xshow = static_checks(blocks)
    report = {}
    if blocks.get("MODEL", "").strip():
        e2, w2, report = run_js(blocks, els, preset_keys, calcs, xshow)
        errors += e2
        warns += w2
    return {"errors": errors, "warnings": warns, "report": report, "meta": meta}
