"""Dev-only A/B: run a free-form 'write the whole index.html' prompt in ONE call (no template, no checks).
Usage: python tools/ab_raw_prompt.py case.json outdir MODEL"""
import json, os, re, sys, time
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from agent import load_key
from p2p import source
from p2p.llm import LLM, Trace

case, out, model = json.load(open(sys.argv[1])), sys.argv[2], sys.argv[3]
os.makedirs(out, exist_ok=True)
t0 = time.time()
tr = Trace(os.path.join(out, "trace.jsonl"), t0)
exc = case.get("excerpt") or source.gather(case, tr) or "(no excerpt provided)"
tpl = open(os.path.join(os.path.dirname(__file__), "raw_prompt.txt")).read()
prompt = tpl.replace("{source_excerpt}", exc).replace("{source_url}", case.get("source_url", "")) \
            .replace("{focus}", case.get("focus", "")).replace("{audience}", case.get("audience", ""))
llm = LLM(model, load_key(), tr, t0)
text, finish = llm.chat("generate", [{"role": "user", "content": prompt}], max_tokens=29000)
m = re.search(r"```(?:html)?\s*\n([\s\S]*?)```", text)
html = m.group(1) if m else text[text.find("<!"):] if "<!" in text else text
open(os.path.join(out, "index.html"), "w").write(html)
print(json.dumps({"finish": finish, "elapsed_s": round(time.time() - t0, 1), "html_kb": len(html) // 1024, **llm.totals()}))
