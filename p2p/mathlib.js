/* ---------- L: small, tested numeric helpers (template, paper-agnostic) ---------- */
const L = (function () {
  const isM = (A) => Array.isArray(A) && Array.isArray(A[0]);
  const range = (n, a, b) => (b === undefined ? Array.from({ length: n }, (_, i) => i) : Array.from({ length: n }, (_, i) => a + (n === 1 ? 0 : ((b - a) * i) / (n - 1))));
  const zeros = (r, c) => (c === undefined ? Array(r).fill(0) : Array.from({ length: r }, () => Array(c).fill(0)));
  const sum = (v) => v.reduce((a, b) => a + b, 0);
  const mean = (v) => (v.length ? sum(v) / v.length : 0);
  const dot = (a, b) => a.reduce((s, x, i) => s + x * (b[i] || 0), 0);
  const transpose = (A) => (A.length ? A[0].map((_, j) => A.map((r) => r[j])) : []);
  function matmul(A, B) {
    if (!isM(B)) return A.map((r) => dot(r, B));
    if (!A.length || !B.length) return [];
    if (A[0].length !== B.length) throw new Error("L.matmul: shapes " + A.length + "x" + A[0].length + " and " + B.length + "x" + B[0].length + " do not match");
    return A.map((r) => B[0].map((_, j) => r.reduce((s, x, k) => s + x * B[k][j], 0)));
  }
  const map = (A, f) => (isM(A) ? A.map((r, i) => r.map((x, j) => f(x, i, j))) : A.map((x, i) => f(x, i)));
  const scale = (A, k) => map(A, (x) => x * k);
  const add = (A, B) => map(A, (x, i, j) => x + (j === undefined ? B[i] : B[i][j]));
  const sub = (A, B) => map(A, (x, i, j) => x - (j === undefined ? B[i] : B[i][j]));
  function softmax(v, T) {
    T = T === undefined ? 1 : T;
    if (isM(v)) return v.map((r) => softmax(r, T));
    if (!v.length) return [];
    const m = Math.max(...v), e = v.map((x) => Math.exp((x - m) / T)), s = sum(e);
    return e.map((x) => x / s);
  }
  const logsumexp = (v) => { const m = Math.max(...v); return m + Math.log(sum(v.map((x) => Math.exp(x - m)))); };
  const log2 = (x) => Math.log(x) / Math.LN2;
  const xlogx = (p, base) => (p > 0 ? (p * Math.log(p)) / Math.log(base || 2) : 0);
  const normalize = (v) => { const s = sum(v); return s > 0 ? v.map((x) => x / s) : v.map(() => 1 / v.length); };
  const argmax = (v) => v.reduce((bi, x, i) => (x > v[bi] ? i : bi), 0);
  const norm = (v) => Math.sqrt(dot(v, v));
  const rowSums = (A) => A.map(sum);
  const shape = (A) => (isM(A) ? [A.length, A[0].length] : [A.length]);
  const sigmoid = (x) => 1 / (1 + Math.exp(-x));
  const round = (x, d) => { const k = Math.pow(10, d === undefined ? 3 : d); return Math.round(x * k) / k; };
  function rng(seed) { let s = seed >>> 0 || 1; return () => { s = (s * 1664525 + 1013904223) >>> 0; return s / 4294967296; }; }
  function randn(r) { const u = Math.max(1e-12, r()), v = r(); return Math.sqrt(-2 * Math.log(u)) * Math.cos(2 * Math.PI * v); }
  const max = (v) => Math.max(...(isM(v) ? v.flat() : v));
  const min = (v) => Math.min(...(isM(v) ? v.flat() : v));
  const ones = (r, c) => map(zeros(r, c), () => 1);
  const abs = (A) => map(A, Math.abs);
  const cumsum = (v) => { let s = 0; return v.map((x) => (s += x)); };
  const clip = (A, a, b) => map(A, (x) => Math.min(b, Math.max(a, x)));
  const fmt = (x, d) => (typeof x === "number" && isFinite(x) ? x.toFixed(d === undefined ? 3 : d) : String(x));
  const fill = (n, v) => Array(n).fill(v === undefined ? 0 : v);
  const api = { fill, log: Math.log, exp: Math.exp, sqrt: Math.sqrt, pow: Math.pow, fmt, range, zeros, ones, sum, mean, max, min, abs, cumsum, clip, dot, transpose, matmul, map, scale, add, sub, softmax, logsumexp, log2, xlogx, normalize, argmax, norm, rowSums, shape, sigmoid, round, rng, randn };
  if (typeof __err === "function") return new Proxy(api, { get(t, k) { if (k in t || typeof k === "symbol") return t[k]; __err("L." + String(k) + " does not exist (available: " + Object.keys(t).join(", ") + ")"); return () => 0; } });
  return api;
})();
