# Paper to Playground

An agent that turns a focused research-paper excerpt and a learning brief into a single, self-contained,
interactive HTML explanation for an engineering undergraduate. It adds a trace of everything it did.

**Team:** Ismail Abou Zeid, Ghina Daoud

## Run

```bash
python -m pip install -r requirements.txt
export OPENROUTER_API_KEY=...            # never committed; read from the environment
python agent.py --input case.json --output out --model google/gemini-2.5-flash
```

- **MODEL_ID:** `google/gemini-2.5-flash` is the model we developed and tested with. Any OpenRouter chat model
  works; nothing in the code is model-specific.
- **Input:** `case.json` must contain `source_url`, `focus` and `audience`. All other fields, such as `excerpt`,
  `title` or `section`, are passed to the model verbatim.
- **Output:** `out/index.html` is one file with all CSS and JS inline. It needs no network, CDN, fonts or API key.
  `out/trace.jsonl` holds one JSON event per stage.
- **Exit code:** `0` when a usable page was written, nonzero otherwise.
- **Requirements:** Python 3.11 and the three pinned pure-pip dependencies. No GPU, browser or system packages.

## Architecture

```
case.json
  │ 1. SOURCE    use the excerpt in the case; only if it has none, try a 6 s fetch of source_url (HTML or PDF)
  │              and keep the window most relevant to the brief. A failed fetch is logged and the run continues.
  │ 2. GENERATE  ONE streamed LLM call returns labelled blocks, in this order:
  │              PLAN · META · MODEL (pure JS math) · PLAYGROUND (controls HTML) · UI (DOM JS)
  │              · INTRO · EXPLORE · GROUNDING
  │ 3. SANITIZE  deterministic fixes that cost no tokens: LaTeX → HTML math, strip external tags,
  │              create missing display containers, remove UI re-declarations of MODEL names
  │ 4. CHECK     static checks + EXECUTION of the generated JS in QuickJS against a stub DOM built from
  │              the generated HTML (see below)
  │ 5. REVISE    if checks fail: send only the failing blocks and the error list, and receive search/replace
  │              EDITs (or whole blocks if missing). Up to 2 rounds. Stops early when a round makes no
  │              progress or only model-proposed expectations disagree. Keeps the best version seen.
  │ 6. WRITE     assemble into the generic template → index.html. The trace records every stage.
```

**Why one generation call?** Prompt and completion tokens are both scored. Running separate plan and write
calls would send the excerpt twice. The plan is still produced explicitly as the first block and logged in the
trace.

**The template is generic and paper-agnostic** ([p2p/template.html](p2p/template.html)). Every page is a
horizontal **slide-deck lesson** with a progress bar, ←/→ keys and a "View as page" toggle that stacks all the
slides. The deck runs in this order:
1. A title slide: idea, why it matters, key equation, symbols.
2. **4–7 concept slides** written by the model as `SLIDES = [{title, text, draw(id, s, r), controls}]`. Each
   introduces one primitive with its own large live visual; later slides integrate the primitives into the full
   mechanism. A slide's controls are moved next to its visual while it is shown.
3. A playground slide with all the controls, an optional ▶ Run/Step loop for iterative mechanisms, and live
   invariants.
4. One slide per guided exploration and one for the limitation. Each shows a slide visual rendered at its preset,
   with a "Try it in the playground" button.
5. A sources-and-checks slide: from the paper vs. our simplifications, plus the built-in calculation checks.

The template also provides two helper libraries:
- `V`: animated SVG bar, line and scatter charts, heatmaps, editable matrices, multi-panel splits, and keyed
  diagram primitives that tween smoothly between states. A diagram's viewBox auto-fits its contents, so nothing is
  clipped.
- `L` ([p2p/mathlib.js](p2p/mathlib.js)): small numeric helpers such as matmul, softmax and xlogx.

The model writes only the paper-specific blocks, which keeps output tokens low and the visuals consistent.

**Every number shown is computed.** `compute(state)` is the only source of the numbers on the page. Values
quoted in the explanations are `<span class="calc" data-at="preset" data-get="r.H">` placeholders, evaluated
from `compute()` at load time, never typed by the model.

### Checks (in [p2p/checks.py](p2p/checks.py), no LLM involved)

| Check | What it catches |
|---|---|
| Block presence; META fields; symbol table; 2 explorations + 1 limitation card; grounding cards | Missing required content |
| No external URLs, `fetch`, imports, `<link>` or remote media | Page would not work offline |
| LaTeX leaks | Formulas that would show as raw `$…$` |
| Ids the UI touches exist; no duplicate ids; at least 2 controls | Dead controls |
| `compute(DEFAULT_STATE)`, every preset and every test state give finite results | NaN / ∞ / crashes |
| `TESTS`: canonical cases from the brief, compared with tolerance | Wrong mechanism maths |
| `invariants()` hold for every preset and every control extreme | Broken properties (e.g. rows sum to 1) |
| Control sweep: each slider and number input at its min and max, each select option, each checkbox | Edge-case crashes |
| `setState` → `readState` round-trip for presets | Presets outside slider ranges or not applied |
| Chart and diagram calls get finite data; shapes and labels stay inside the viewBox | Clipped or NaN visuals |
| Every slide's `draw()` runs for the default state and every preset, draws something, and borrows only existing controls | Broken or empty slides |
| Calc spans and exploration slides reference real presets, slides and finite expressions | Wrong numbers in prose |
| Helper calls exist in `V` / `L` | Hallucinated APIs |
| `step()` stays finite for 60 iterations | Diverging iterative demos |

A model-proposed test or invariant whose hand-derived expectation still disagrees with the executed computation
is removed from the page. The page discloses this and the trace logs it, so a visible ✓ always means a passing
calculation.

### Budget guards
- The client enforces ≤ 10 requests, ≤ 30,000 completion tokens and a 9-minute deadline, capping `max_tokens`
  by what remains.
- Responses are streamed. A degenerate repetition loop (e.g. endless `0000…`) is detected and the call is cut
  short; the unfinished block is dropped and regenerated.
- A 402 "can only afford N tokens" error is retried once with a smaller ceiling. A 429 is retried with backoff.
- The trace logs per-call prompt, completion, reasoning and cached tokens, elapsed seconds, finish reason and
  the OpenRouter generation id, so usage can be verified against API records. No credentials or hidden
  reasoning are logged.

## Files

| Path | Purpose |
|---|---|
| `agent.py` | CLI entry point and orchestration loop |
| `p2p/prompts.py` | System, user and repair prompts (generic page contract) |
| `p2p/llm.py` | OpenRouter streaming client with budget enforcement and tracing |
| `p2p/checks.py` | Static checks, sanitizers and the QuickJS execution harness |
| `p2p/latex.py` | Deterministic LaTeX → HTML converter |
| `p2p/assemble.py` | Block parser, search/replace edit applier, template assembly |
| `p2p/source.py` | Excerpt handling and best-effort source fetch |
| `p2p/template.html`, `p2p/mathlib.js` | Generic page template and helper libraries |
| `examples/*.json` | Practice inputs (our own; the two public examples plus three others) |
| `examples/output/` | One example input/output pair with its trace |
| `tools/` | Development-only scripts (browser smoke test, re-assembly); not used by the agent |

## Credits and reuse
- No third-party code is vendored. The template, helper libraries, checks and prompts were written for this
  project, with help from an AI coding assistant (Claude Code), as the hackathon rules allow.
- Runtime dependencies:
  - [`requests`](https://pypi.org/project/requests/) (Apache-2.0) for HTTP;
  - [`quickjs`](https://pypi.org/project/quickjs/) (MIT) for Python bindings to Fabrice Bellard's QuickJS, used to
    execute generated JS during checks;
  - [`pypdf`](https://pypi.org/project/pypdf/) (BSD) for PDF text extraction during the optional fetch.
- Development only: [Playwright](https://playwright.dev/) for the browser smoke test in `tools/`. It is not in
  `requirements.txt`.
- Practice cases paraphrase short excerpts from the cited papers. They are used only as test inputs.
