# Paper to Playground

An agent that turns a focused research-paper excerpt and a learning brief into a self-contained, interactive
**slide-deck lesson** (one HTML file) for an engineering undergraduate. It also writes a trace of everything it
did.

**Team:** Adam Manasfi, Ismail Abou Zeid, Ghina Daoud

## Run

```bash
python -m pip install -r requirements.txt
export OPENROUTER_API_KEY=...            # read from the environment; never committed or written to outputs
python agent.py --input case.json --output out --model google/gemini-2.5-flash
```

- **MODEL_ID:** `google/gemini-2.5-flash`, the model we developed and tested with. Any OpenRouter chat model
  works; nothing in the code is model-specific.
- **Input:** `case.json` must contain `source_url`, `focus` and `audience`. Any other fields, such as `excerpt`,
  `title` or `section`, are passed to the model verbatim.
- **Output:** `out/index.html` is a single file with all CSS, JS and visuals inline. It needs no network, CDN,
  fonts or API key. `out/trace.jsonl` holds one JSON event per stage, LLM call, check and revision.
- **Exit code:** `0` when a usable page was written, nonzero otherwise.
- **Requirements:** Python 3.11 and three pinned pure-pip packages. No GPU, browser or system packages.
- **Optional flags** (all have defaults; the command above is all you need): `--web-search`, `--max-repairs`,
  `--gen-max-tokens`, `--effort`.

## Pipeline

```
case.json
 │ 1. SOURCE    use the excerpt in the case; only if there is none, try a 6 s fetch of source_url (HTML or PDF)
 │              and keep the most relevant window. A failed fetch is logged and the run continues.
 │ 2. GENERATE  ONE streamed LLM call returns labelled blocks:
 │              PLAN (incl. a per-slide VISUAL PLAN) · META · MODEL (pure JS maths) · PLAYGROUND (controls)
 │              · UI (slides + drawing code) · INTRO · EXPLORE · GROUNDING
 │ 3. SANITIZE  zero-token deterministic fixes: LaTeX → HTML, strip external tags, create missing containers,
 │              drop UI re-declarations of MODEL names, remove live-state references inside scenario literals
 │ 4. CHECK     static checks + EXECUTION of all generated JS in QuickJS against a stub DOM built from the
 │              generated HTML (details below)
 │ 5. REVISE    if checks fail: send only the failing blocks and a severity-ranked error list (with the
 │              offending source line quoted); apply search/replace EDITs. One round by default, plus one extra
 │              round only while a page-killing (fatal) error survives (also when the previous repair reply contained nothing
 │              applicable: the agent retries once with an explicit format reminder). The best version seen is kept.
 │ 6. WRITE     assemble into the generic template → index.html; disclose any pruned self-checks
```

**Why one generation call?** Prompt and completion tokens are both scored. Separate plan and write calls would
send the excerpt twice. The plan is still written explicitly, as the first block, and logged in the trace.

## What a generated lesson looks like

The template ([p2p/template.html](p2p/template.html)) is generic and paper-agnostic. Every page is a horizontal
slide deck in a dark lecture style: gold headings, teal accents, monospace numbers. It has a progress bar, ←/→
navigation, and a **View as page** toggle that stacks all slides for reading or inspection.

1. **Title slide:** the idea as a plain-words analogy, why it matters, the key equation, and a symbol table.
2. **4–7 concept slides** (`SLIDES = [{title, text, draw(id, s, r), choices, controls}]`). Each slide adds exactly
   one new idea with its own large live visual. Primitives come first; the full equation is revealed last and
   mapped to pieces already seen. Learners explore through **scenario chips**: 2–4 named one-click situations
   that animate the visual to a meaningfully different outcome. A slide can also borrow up to 2 sliders.
3. **Playground:** a scenario bar built from all presets, every control the brief asks for (matrix editors are
   folded under "Fine-tune"), an optional ▶ Run/Step loop for iterative mechanisms, and live invariant checks.
4. **Two guided explorations and one limitation**, each on its own slide in Try / Watch / Why form. Each shows a
   slide visual rendered at its own preset, with a "Try it in the playground" button.
5. **Sources and checks:** what is stated in the paper (with section/equation) vs. our simplifications, a
   disclaimer that the toy demo does not reproduce the paper's results, and a built-in calculation-check table.

**Every number shown is computed.** `compute(state)` is the single source of numbers. Values quoted in the prose
are `<span class="calc" data-at="preset" data-get="…">` placeholders evaluated from `compute()`, never typed by the
model.

## Visual design: reasoning, not a lookup table

The prompt does not map topics to pictures. Before writing code, the model answers four questions for each slide
and records them in its VISUAL PLAN:

1. What one thing changes in this step, and what causes it?
2. If you sketched it on a whiteboard for a friend, what would you draw?
3. Which visual property carries the key quantity (position, length, angle, area, size, colour), so the cause and
   effect is *seen* rather than read?
4. Only then: which drawing tool matches the sketch? Or draw it directly with diagram primitives.

General perception rules also apply: big marks, direct labels, the picture fills its panel, every scenario must
look visibly different, and the picture must make sense with the text hidden. An optional `--web-search` flag
(off by default) adds one small call through OpenRouter's server-side web plugin to research how a concept is
usually visualised. In our tests it added about 2k tokens and 7 s.

The template provides a library of 3Blue1Brown-style drawing tools ([p2p/vizlib.js](p2p/vizlib.js)). The prompt
describes each one only by what it draws:

| Tool | Draws |
|---|---|
| `V.space` | Points and arrows in an equal-aspect 2-D plane, with angle arcs, projections, regions and **draggable** handles |
| `V.network` | Columns of nodes joined by weighted edges (edge width/colour = weight, node fill = value) |
| `V.graph` | Nodes sized by value, joined by weighted directed arrows |
| `V.numberline` | One axis with big labelled markers and labelled brackets for distances between positions |
| `V.curve` | y = f(x) with a ball on it, its tangent, and a trail of earlier points |
| `V.pixels` | A grid of shaded cells with movable highlight windows |
| `V.pipeline` | Arrays side by side as shaded grids, joined by labelled arrows |
| `V.flow` | A row of boxes with live values, joined by arrows |
| `V.waffle` | A population of dots coloured by group |
| `V.transform` | The plane's grid and basis vectors warped by a 2×2 matrix |
| `V.bars`, `V.line`, `V.matrix`, `V.diagram` | Charts, heatmaps, and free-form keyed primitives (rect, circle, line, path, arrow, text) |

Engine properties that make the visuals robust without prompt rules:
- **Animated:** every element is keyed and tweens to its new geometry, Manim-style, when a value changes.
- **Stable scales:** an axis stays fixed while the new data still fills at least 40% of it, so switching scenarios
  visibly moves the data instead of re-zooming; it re-fits when the data would shrink to a speck.
- **Responsive:** charts lay themselves out at their container's real pixel width, so labels stay full size in
  split panels.
- **Composable:** each tool cleans up only its own elements and returns an annotatable context with X/Y maps.
- **Safe text:** SVG labels are cleaned of HTML and wrapped; diagram viewBoxes auto-fit their contents within a
  cap, so nothing is clipped.
- `L` ([p2p/mathlib.js](p2p/mathlib.js)) provides small, tested numeric helpers such as matmul, softmax, xlogx,
  normalize and seeded random numbers.

We considered [Manim](https://github.com/3b1b/manim). It renders non-interactive videos and needs
OpenGL/ffmpeg/LaTeX system packages, so we built the same ideas (keyed objects that transform smoothly, scenes as
slides) as live, interactive SVG instead.

## Checks ([p2p/checks.py](p2p/checks.py), no LLM involved)

| Check | What it catches |
|---|---|
| Block presence; META fields; symbol table; 2 explorations + 1 limitation; grounding cards | Missing required content |
| No external URLs, `fetch`, imports, `<link>` or remote media; no LaTeX leaks | Pages that fail offline or show raw `$…$` |
| Ids the UI touches exist; no duplicate ids; ≥ 2 controls, including every control the brief requires | Dead controls |
| `compute()` finite for the default state, every preset, every scenario and every control extreme | NaN / ∞ / crashes |
| `TESTS` (canonical cases from the brief) and `invariants()` | Wrong mechanism maths |
| Control sweep (each slider/number at min and max, each select option, each checkbox) | Edge-case crashes |
| `setState` → `readState` round trip for presets; each slide's scenarios give *different* results | Scenario buttons that do nothing |
| Every slide's `draw()` runs for the default state, every preset and every scenario, and **visible shapes survive** | Broken or blank slides |
| Chart data finite; diagram content and labels stay inside their frame | NaN visuals, clipped or shrunken diagrams |
| Calc spans, exploration slides and presets reference real things | Wrong numbers in the prose |
| Every `V`/`L` call exists (with the list of real names in the message) | Hallucinated APIs |
| `step()` stays finite for 60 iterations | Diverging iterative demos |

Errors are weighted by severity. Page-killing errors (a block fails to load, `compute`/`readState` throws on the
default state, missing slides) weigh 100; broken scenarios weigh 40; cosmetic issues weigh 5; and the model's own
self-check expectations weigh 1. This weighting drives repair priority and the keep-best rollback. A model-written
test or invariant whose hand-derived expectation disagrees with the executed computation is not "fixed" with
tokens: it is removed from the page, and the page and the trace say so. A visible ✓ therefore always means a
passing calculation.

### Budget guards
- The client enforces ≤ 10 requests, ≤ 30,000 completion tokens and a 9-minute deadline, capping `max_tokens` by
  what remains.
- Responses are streamed. A degenerate repetition loop (e.g. endless `0000…`) is detected and cut short.
- A 402 "can only afford N tokens" error is retried with a smaller ceiling. A 429 is retried with backoff.
- Fail-safe: an unexpected internal error in the checker or sanitizer is logged as `internal_error`, and the agent
  still writes the best page it has. We tested this with an injected checker failure: the page was written and the
  run exited 0. Bad input or a missing API key exits with code 2; a failed generation exits 1 with the error in the
  trace.
- The trace logs per-call prompt, completion, reasoning and cached tokens, elapsed seconds, finish reason and the
  OpenRouter generation id, so usage can be verified against API records. No credentials or hidden reasoning are
  logged.

## Measured results

**Final batch:** each case was run once through `agent.py` with exactly
`python agent.py --input <case>.json --output <dir> --model google/gemini-2.5-flash`, on the submitted code, with
nothing post-processed. Every run exited 0, wrote exactly `index.html` and `trace.jsonl`, and stayed inside 10
requests, 30k completion tokens and 10 minutes.

| Case | Calls | Total tokens | Time | Final status |
|---|---|---|---|---|
| **Held-out:** sampling and aliasing (Shannon 1949, Thm 1) | 1 | 13.1k | 32 s | clean (example output below) |
| **Held-out:** scalar Kalman update (Kalman 1960) | 2 | 40.6k | 75 s | works; 4 minor issues |
| **Held-out:** Huffman construction (Huffman 1952) | 2 | 28.9k | 44 s | **failed:** the model's `compute()` stringifies a self-referencing object and throws on load |
| Shannon entropy (Sec. 6) | 1 | 14.8k | 34 s | clean |
| Bayes' rule, base-rate fallacy | 1 | 14.8k | 35 s | clean |
| MLP forward pass (Rumelhart et al. 1986, Eq. 1–2) | 2 | 40.4k | 72 s | works; 4 minor issues |
| word2vec analogies (Sec. 1, 5) | 2 | 36.1k | 64 s | works; 3 minor issues |
| PageRank (Sec. 2.4, 2.6, iterative) | 2 | 41.6k | 74 s | works; 2 minor issues |
| Batch Normalization (Alg. 1) | 2 | 35.8k | 62 s | works; 3 minor issues |
| Convolution + sub-sampling (LeCun et al. 1998, Sec. II.A) | 2 | 29.9k | 49 s | works; one slide has mis-positioned shapes |
| Scaled dot-product attention (Sec. 3.2.1) | 2 | 40.9k | 74 s | works; 5 minor issues |
| Adam bias correction (Alg. 1, iterative) | 3 | 40.7k | 78 s | works; its scenario presets carry iteration history that does not round-trip |

The held-out cases were written after the prompt was finalised and are never referenced by it. "Minor issues" are
non-fatal checker findings, such as an edge case at a control extreme or a pruned model-written self-check.

**Variance.** Over several full batches on the final code, about 1–3 of 12 runs per batch ended with a
model-written code error that the repair round could not fix, and *which* case failed changed from batch to batch
(PageRank, Huffman, entropy, Bayes and MLP each failed once). The trace always records the remaining errors. Each
recurring failure *pattern* was turned into a deterministic engine fix rather than a prompt rule.

We also verified:
- a clean-room install (fresh clone, fresh venv, exact command above);
- a run where every network request except OpenRouter was blocked (the source fetch failed in 0.05 s and
  generation completed from the case text);
- a second model family (`openai/gpt-4.1-mini`).

**Example input/output pair:** [examples/output/aliasing/](examples/output/aliasing/) holds `case.json`,
`index.html` and `trace.jsonl` from the final batch, exactly as the agent wrote them.

## Files

| Path | Purpose |
|---|---|
| `agent.py` | CLI entry point and orchestration loop (generate → check → revise → write) |
| `p2p/prompts.py` | System, user and repair prompts: the generic page contract and teaching/visual-design guidance |
| `p2p/llm.py` | OpenRouter streaming client with budget enforcement, loop detection and tracing |
| `p2p/checks.py` | Static checks, sanitizers and the QuickJS execution harness (stub DOM) |
| `p2p/assemble.py` | Block parser, search/replace edit applier, template assembly |
| `p2p/latex.py` | Deterministic LaTeX → HTML converter |
| `p2p/source.py` | Excerpt handling and best-effort source fetch |
| `p2p/template.html` | Slide-deck template: layout, theme, navigation, scenarios, run loop, self-tests, `V` core |
| `p2p/vizlib.js`, `p2p/mathlib.js` | Drawing tools and numeric helpers embedded in every page |
| `examples/*.json` | Practice inputs (the two public examples plus seven of ours) |
| `examples/heldout/*.json` | Held-out inputs, used only for testing |
| `examples/output/aliasing/` | Example input/output pair with its trace |
| `tools/` | Development-only scripts, never used by the agent: browser smoke test, slide screenshots and contact sheets, an A/B script for a one-shot prompt, and `reassemble.py`, which rebuilds a saved debug run with the current library so library fixes could be compared on identical model output during development. None of the reported results use it. |

## Credits and reuse
- No third-party code is vendored. The template, drawing and maths libraries, checks and prompts were written for
  this project, with help from an AI coding assistant (Claude Code), as the hackathon rules allow. The visual
  style is inspired by 3Blue1Brown/Manim; no Manim code is used.
- Runtime dependencies:
  - [`requests`](https://pypi.org/project/requests/) (Apache-2.0) for HTTP;
  - [`quickjs`](https://pypi.org/project/quickjs/) (MIT) for Python bindings to Fabrice Bellard's QuickJS, used to
    execute generated JS during checks;
  - [`pypdf`](https://pypi.org/project/pypdf/) (BSD) for PDF text extraction during the optional fetch.
- Development only: [Playwright](https://playwright.dev/) (browser smoke tests in `tools/`) and Pillow (contact
  sheets). Neither is in `requirements.txt`.
- Practice and held-out cases paraphrase short excerpts from the cited papers and are used only as test inputs.
