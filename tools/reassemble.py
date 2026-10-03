"""Dev-only: rebuild index.html from a page's blocks (blocks.json or extracted from an existing index.html),
re-run sanitize + checks. Usage: python tools/reassemble.py runs/x case.json"""
import json, os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from p2p import checks
from p2p.assemble import assemble

d, case = sys.argv[1], json.load(open(sys.argv[2]))
bp = os.path.join(d, "blocks.json")
if os.path.exists(bp):
    blocks = json.load(open(bp))
else:
    html = open(os.path.join(d, "index.html")).read()
    def between(a, b):
        i = html.index(a) + len(a); return html[i:html.index(b, i)].strip()
    blocks = {
        "META": json.dumps({"title": between("<title>", "</title>"), "paper": "?", "section": "?"}),
        "INTRO": between('<h2><span class="n">1</span>The idea</h2>', '</section>'),
        "PLAYGROUND": between('<div id="learnbar" hidden></div>', '<div class="card" id="livebox"'),
        "MODEL": between('/* ---------- MODEL (generated) ---------- */', '</script>'),
        "UI": between('/* ---------- UI (generated) ---------- */', '</script>'),
        "EXPLORE": between('<h2><span class="n">3</span>Guided explorations</h2>', '</section>'),
        "GROUNDING": between('<h2><span class="n">4</span>Source grounding</h2>', '<p class="disclaimer">'),
    }
    json.dump(blocks, open(bp, "w"), indent=1)
print(checks.sanitize(blocks))
r = checks.check(blocks)
print("ERRORS:", json.dumps(r["errors"], indent=1)); print("WARNINGS:", r["warnings"])
open(os.path.join(d, "index.html"), "w").write(assemble(blocks, case))
