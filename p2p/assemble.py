"""Parse the model's @@BLOCK output and assemble the self-contained page from the generic template."""
import html as H
import json
import os
import re

from .prompts import BLOCKS

TEMPLATE = os.path.join(os.path.dirname(__file__), "template.html")
MATHLIB = os.path.join(os.path.dirname(__file__), "mathlib.js")
VIZLIB = os.path.join(os.path.dirname(__file__), "vizlib.js")
MARK = re.compile(r"^[ \t]*@@([A-Z]+(?:[ \t]+[A-Z]+)?)[ \t]*$", re.M)


def parse_blocks(text, truncated=False):
    """Split '@@NAME' blocks. If the output was cut off (finish_reason=length), drop the unfinished last block."""
    out = {}
    parts = MARK.split(text)
    if truncated and "@@END" not in text and len(parts) >= 3:
        parts = parts[:-2]
    for i in range(1, len(parts) - 1, 2):
        name, body = parts[i], parts[i + 1]
        if name == "END" or name not in BLOCKS:
            continue
        body = body.strip("\n")
        # strip markdown fences the model may add despite instructions
        body = re.sub(r"^\s*```[a-zA-Z]*\s*\n", "", body)
        body = re.sub(r"\n\s*```\s*$", "", body)
        out[name] = body.strip()
    if "META" in out:
        m = re.search(r"\{[\s\S]*\}", out["META"])
        out["META"] = m.group(0) if m else out["META"]
    return out


def split_tests(model):
    """Move `const TESTS = [...]` out of MODEL into a guarded snippet so a bad test can never break compute()."""
    m = re.search(r"^(const|let|var)\s+TESTS\s*=\s*\[", model or "", re.M)
    if not m:
        return model, ""
    i, depth, q = m.end() - 1, 0, None
    while i < len(model):
        c = model[i]
        if q:
            if c == "\\":
                i += 1
            elif c == q:
                q = None
        elif c in "'\"`":
            q = c
        elif c == "[":
            depth += 1
        elif c == "]":
            depth -= 1
            if depth == 0:
                break
        i += 1
    if depth != 0:
        return model, ""
    end = i + 1
    if end < len(model) and model[end] == ";":
        end += 1
    body = model[m.end() - 1:i + 1]
    guarded = ("var TESTS = [], __TESTS_ERROR = null;\ntry { TESTS = " + body + "; } catch (e) { __TESTS_ERROR = String(e && e.message || e); }")
    return model[:m.start()] + model[end:], guarded


def _js(s):
    return (s or "").replace("</script", "<\\/script")


def assemble(blocks, case):
    try:
        meta = json.loads(blocks.get("META", "{}"))
    except Exception:
        meta = {}
    title = H.escape(str(meta.get("title") or "Interactive explanation"))
    url = case.get("source_url", "")
    cite = []
    if meta.get("paper"):
        cite.append("Source: " + H.escape(str(meta["paper"])))
    if meta.get("section"):
        cite.append(H.escape(str(meta["section"])))
    if url:
        cite.append(f'<a href="{H.escape(url, quote=True)}" target="_blank" rel="noopener">{H.escape(url)}</a>')
    aud = case.get("audience")
    if aud:
        cite.append("Audience: " + H.escape(str(aud)))
    page = open(TEMPLATE, encoding="utf-8").read()
    model, tests_js = split_tests(blocks.get("MODEL", ""))
    rep = {
        "%%TITLE%%": title,
        "%%CITE%%": " · ".join(cite),
        "%%SUMMARY%%": H.escape(str(meta.get("summary", ""))),
        "%%INTRO%%": blocks.get("INTRO", ""),
        "%%PLAYGROUND%%": blocks.get("PLAYGROUND", ""),
        "%%EXPLORE%%": blocks.get("EXPLORE", ""),
        "%%GROUNDING%%": blocks.get("GROUNDING", ""),
        "%%MODEL%%": _js(model),
        "%%TESTS%%": _js(tests_js),
        "%%UI%%": _js(blocks.get("UI", "")),
        "%%MATHLIB%%": open(MATHLIB, encoding="utf-8").read(),
        "%%VIZLIB%%": open(VIZLIB, encoding="utf-8").read(),
    }
    # single pass so generated content containing %%X%% is never re-substituted
    return re.sub("|".join(re.escape(k) for k in rep), lambda m: rep[m.group(0)], page)


EDIT_HDR = re.compile(r"^[ \t]*@@EDIT[ \t]+([A-Z]+)[ \t]*$", re.M)
EDIT_RX = re.compile(r"<{5,}[^\n]*\n([\s\S]*?)\n={5,}[^\n]*\n([\s\S]*?)\n?>{5,}[^\n]*")


def _replace_once(text, old, new):
    if old and old in text:
        return text.replace(old, new, 1)
    # whitespace-tolerant fallback: match stripped lines
    tl, ol = text.split("\n"), [l.strip() for l in old.strip("\n").split("\n")]
    n = len(ol)
    for i in range(len(tl) - n + 1):
        if [l.strip() for l in tl[i:i + n]] == ol:
            return "\n".join(tl[:i] + new.split("\n") + tl[i + n:])
    return None


def apply_edits(blocks, text):
    """Apply '@@EDIT BLOCK' search/replace hunks. Returns (blocks, applied, failed)."""
    blocks = dict(blocks)
    applied, failed = [], []
    parts = re.split(r"^[ \t]*(@@EDIT[ \t]+[A-Z]+|@@[A-Z]+)[ \t]*$", text, flags=re.M)
    for i in range(1, len(parts) - 1, 2):
        m = EDIT_HDR.match(parts[i])
        if not m:
            continue
        name = m.group(1)
        for old, new in EDIT_RX.findall(parts[i + 1]):
            res = _replace_once(blocks.get(name, ""), old, new)
            if res is None:
                failed.append(f"{name}: search text not found: {old.strip()[:80]!r}")
            else:
                blocks[name] = res
                applied.append(name)
    return blocks, applied, failed
