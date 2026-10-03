"""Source acquisition. The case normally carries the excerpt; fetching the URL is a best-effort fallback
(it will simply fail fast when network access is restricted)."""
import io
import re
from html.parser import HTMLParser

import requests

STOP = set("the and for with that this from into using show shows explain their them they what when where which while about over under than then each between learner learners student students should must will able change changes value values".split())


class _Text(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.out, self.skip = [], 0

    def handle_starttag(self, tag, attrs):
        if tag in ("script", "style", "nav", "header", "footer"):
            self.skip += 1
        if tag in ("p", "div", "h1", "h2", "h3", "h4", "li", "tr", "section", "math", "br"):
            self.out.append("\n")

    def handle_endtag(self, tag):
        if tag in ("script", "style", "nav", "header", "footer") and self.skip:
            self.skip -= 1

    def handle_data(self, d):
        if not self.skip:
            self.out.append(d)

    def handle_starttag_math(self, attrs):
        pass


def _html_text(html):
    # arXiv HTML renders math as MathML with an alttext attribute holding the LaTeX: keep it
    html = re.sub(r"<math[^>]*alttext=\"([^\"]*)\"[^>]*>[\s\S]*?</math>", lambda m: " $" + m.group(1) + "$ ", html)
    p = _Text()
    p.feed(html)
    return re.sub(r"\n\s*\n+", "\n", re.sub(r"[ \t]+", " ", "".join(p.out)))


def _pdf_text(data):
    from pypdf import PdfReader
    r = PdfReader(io.BytesIO(data))
    return "\n".join((pg.extract_text() or "") for pg in r.pages[:40])


def has_excerpt(case):
    known = {"source_url", "focus", "audience"}
    return any(isinstance(v, str) and len(v) > 300 for k, v in case.items() if k not in known)


def relevant_window(text, focus, max_chars=7000):
    text = text.replace("\r", "")
    words = [w for w in re.findall(r"[a-zA-Z][a-zA-Z\-]{3,}", focus.lower()) if w not in STOP]
    secs = re.findall(r"\b\d+(?:\.\d+)+\b", focus)
    step, size = 600, 1800
    best, best_i = -1, 0
    for i in range(0, max(1, len(text) - size), step):
        chunk = text[i:i + size]
        low = chunk.lower()
        s = sum(min(low.count(w), 5) for w in set(words))
        s += sum(15 for sec in secs if re.search(r"(^|\n)\s*" + re.escape(sec) + r"\b", chunk))
        if s > best:
            best, best_i = s, i
    start = max(0, best_i - 1200)
    return text[start:start + max_chars]


def gather(case, trace, timeout=6):
    """Return extra source text for the prompt ('' if not needed or unavailable)."""
    if has_excerpt(case):
        trace("source", "use_case_excerpt", "ok", fields=[k for k in case])
        return ""
    url = case.get("source_url", "")
    if not url.startswith("http"):
        trace("source", "fetch", "skipped", reason="no excerpt and no URL")
        return ""
    try:
        r = requests.get(url, timeout=(3, timeout), headers={"User-Agent": "Mozilla/5.0 paper-to-playground"})
        r.raise_for_status()
        if url.lower().endswith(".pdf") or "pdf" in r.headers.get("content-type", ""):
            text = _pdf_text(r.content)
        else:
            text = _html_text(r.text)
        win = relevant_window(text, case.get("focus", ""))
        trace("source", "fetch", "ok", url=url, chars=len(text), excerpt_chars=len(win))
        return win
    except Exception as e:
        trace("source", "fetch", "failed", url=url, error=f"{type(e).__name__}: {str(e)[:160]}",
              note="continuing from the case text and model knowledge")
        return ""
