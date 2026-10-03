"""Tiny deterministic LaTeX -> HTML converter for inline math the model leaks into HTML (no tokens spent)."""
import re

SYM = {
    "alpha": "α", "beta": "β", "gamma": "γ", "delta": "δ", "epsilon": "ε", "varepsilon": "ε", "zeta": "ζ", "eta": "η",
    "theta": "θ", "lambda": "λ", "mu": "μ", "nu": "ν", "xi": "ξ", "pi": "π", "rho": "ρ", "sigma": "σ", "tau": "τ",
    "phi": "φ", "varphi": "φ", "chi": "χ", "psi": "ψ", "omega": "ω", "Gamma": "Γ", "Delta": "Δ", "Theta": "Θ",
    "Lambda": "Λ", "Pi": "Π", "Sigma": "Σ", "Phi": "Φ", "Psi": "Ψ", "Omega": "Ω", "cdot": "·", "times": "×",
    "sum": "Σ", "prod": "Π", "leq": "≤", "le": "≤", "geq": "≥", "ge": "≥", "neq": "≠", "approx": "≈", "infty": "∞",
    "in": "∈", "to": "→", "rightarrow": "→", "leftarrow": "←", "Rightarrow": "⇒", "ldots": "…", "dots": "…",
    "cdots": "⋯", "pm": "±", "propto": "∝", "partial": "∂", "nabla": "∇", "mid": "|", "top": "T", "intercal": "T",
    "sim": "∼", "equiv": "≡", "forall": "∀", "exists": "∃", "int": "∫", "ell": "ℓ", "log": "log", "ln": "ln",
    "exp": "exp", "max": "max", "min": "min", "arg": "arg", "softmax": "softmax", "quad": " ", "qquad": "  ",
    "lfloor": "⌊", "rfloor": "⌋", "lceil": "⌈", "rceil": "⌉", "langle": "⟨", "rangle": "⟩", "|": "‖", "neg": "¬",
}


def _group(s, i):
    """Return (content, end) of the {...} group or single token starting at s[i]."""
    while i < len(s) and s[i] == " ":
        i += 1
    if i >= len(s):
        return "", i
    if s[i] == "{":
        depth, j = 0, i
        while j < len(s):
            if s[j] == "{":
                depth += 1
            elif s[j] == "}":
                depth -= 1
                if depth == 0:
                    return s[i + 1:j], j + 1
            j += 1
        return s[i + 1:], len(s)
    if s[i] == "\\":
        m = re.match(r"\\[a-zA-Z]+", s[i:])
        if m:
            return m.group(0), i + len(m.group(0))
    return s[i], i + 1


def conv(s):
    out, i = [], 0
    while i < len(s):
        c = s[i]
        if c == "\\":
            m = re.match(r"\\([a-zA-Z]+|.)", s[i:])
            name = m.group(1)
            i += len(m.group(0))
            if name == "frac" or name == "dfrac" or name == "tfrac":
                a, i = _group(s, i)
                b, i = _group(s, i)
                out.append(f'<span class=frac><span>{conv(a)}</span><span>{conv(b)}</span></span>')
            elif name == "sqrt":
                a, i = _group(s, i)
                ca = conv(a)
                out.append("√" + (ca if len(a) <= 1 else f'<span class=ovl>{ca}</span>'))
            elif name in ("mathrm", "text", "operatorname", "textrm", "mathit", "textit", "mathcal", "mathsf"):
                a, i = _group(s, i)
                out.append(conv(a))
            elif name in ("mathbf", "textbf", "boldsymbol", "bm"):
                a, i = _group(s, i)
                out.append(f"<b>{conv(a)}</b>")
            elif name in ("hat", "bar", "tilde", "vec"):
                a, i = _group(s, i)
                mark = {"hat": "̂", "bar": "̄", "tilde": "̃", "vec": "⃗"}[name]
                out.append(conv(a) + mark)
            elif name in ("left", "right", "big", "Big", "bigg", "Bigg", "displaystyle", "limits"):
                pass
            elif name in (",", ";", ":", " ", "!"):
                out.append(" " if name != "!" else "")
            elif name in ("{", "}", "%", "$", "&", "#", "_"):
                out.append(name)
            else:
                out.append(SYM.get(name, name))
        elif c in "^_":
            a, i = _group(s, i + 1)
            tag = "sup" if c == "^" else "sub"
            out.append(f"<{tag}>{conv(a)}</{tag}>")
        elif c in "{}":
            i += 1
        else:
            out.append(c)
            i += 1
    return "".join(out)


MATH = re.compile(r"\$\$([\s\S]+?)\$\$|\\\[([\s\S]+?)\\\]|\\\(([\s\S]+?)\\\)|(?<![\\$])\$(?!\{)([^$\n]{1,200}?)\$")


def fix_html(html):
    """Convert $...$, $$...$$, \\(...\\), \\[...\\] spans in HTML text into HTML math. Returns (html, n)."""
    n = 0

    def rep(m):
        nonlocal n
        n += 1
        body = next(g for g in m.groups() if g is not None)
        return conv(body.strip())

    return MATH.sub(rep, html), n


JSMATH = re.compile(r"(?<![\\$])\$(?!\{)([^$\n`'\"]{1,200}?)\$")


def fix_js(js):
    """Convert LaTeX inside JS string literals (output uses no quotes, so literals stay valid)."""
    n = 0

    def rep(m):
        nonlocal n
        body = m.group(1)
        if not re.search(r"\\{1,2}[a-zA-Z]|[\^_]\{?\w", body):
            return m.group(0)
        n += 1
        return conv(body.replace("\\\\", "\\"))

    return JSMATH.sub(rep, js), n
