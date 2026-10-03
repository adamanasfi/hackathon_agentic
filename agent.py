#!/usr/bin/env python3
"""Paper-to-Playground agent.

Pipeline:  source -> generate (1 LLM call: plan + all page blocks) -> assemble -> check (static + executed JS)
           -> targeted repair of failing blocks (0-2 LLM calls) -> write out/index.html + out/trace.jsonl

Usage: python agent.py --input case.json --output out --model MODEL_ID
"""
import argparse
import json
import os
import re
import sys
import time

T0 = time.time()

from p2p import checks, prompts, source  # noqa: E402
from p2p.assemble import apply_edits, assemble, parse_blocks  # noqa: E402
from p2p.llm import LLM, BudgetError, Trace  # noqa: E402

CORE = ("INTRO", "PLAYGROUND", "MODEL", "UI")
JS_BLOCKS = ["PLAYGROUND", "MODEL", "UI"]


def load_key():
    key = os.environ.get("OPENROUTER_API_KEY", "").strip()
    if not key:  # development convenience only; .env is git-ignored
        p = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env")
        if os.path.exists(p):
            for line in open(p, encoding="utf-8"):
                if line.strip().startswith("OPENROUTER_API_KEY"):
                    key = line.split("=", 1)[1].strip().strip("'\"")
    return key


def dbg(args, name, text):
    if os.environ.get("P2P_DEBUG"):
        open(os.path.join(args.output, name), "w", encoding="utf-8").write(text)


def blocks_for(errors, blocks):
    """Map each check failure to the block(s) that must change (smallest set)."""
    need = set()
    for e in errors:
        hit = False
        for b in ("META", "INTRO", "EXPLORE", "GROUNDING", "PLAYGROUND", "MODEL", "UI"):
            if e.startswith(b + " ") or f"block {b} " in e:
                need.add(b)
                hit = True
        if "data-preset" in e or "calc span" in e or "EXPLORE card" in e:
            need.add("EXPLORE")
            hit = True
        if re.match(r'(TEST "|invariant|compute\(|step\(\)|L\.|MODEL)', e):
            need.add("MODEL")
            hit = True
        if re.search(r"render|SLIDES|V\.|d\.\w+\(|readState|setState|init\(|page text|control #|second update|UI", e):
            need.add("UI")
            hit = True
        if re.search(r"no element|references #|controls lists #|PLAYGROUND has", e):
            need.update(["UI", "PLAYGROUND"])
            hit = True
        if not hit:
            need.update(JS_BLOCKS)
    return [b for b in prompts.BLOCKS if b in need]


FATAL = re.compile(r"block failed to load|is not defined|compute\(DEFAULT_STATE\) threw|render\(DEFAULT_STATE\) threw|block \w+ is missing"
                   r"|readState\(\) after DEFAULT_STATE threw|setState\(DEFAULT_STATE\) threw|readState\(\) must return|compute\(DEFAULT_STATE\) gives non-finite"
                   r"|harness aborted|UI: SLIDES array is not defined")


def weight(e):
    if FATAL.search(e):
        return 100
    if re.match(r'(TEST "|invariant ")', e):
        return 1
    if re.match(r"SLIDES\[\d+\]\.draw threw at DEFAULT", e) or "setState then readState" in e or "choices[" in e:
        return 40  # broken scenario buttons / presets: the main interaction silently does nothing
    return 5


def severity(errors):
    """Weighted error score: anything that kills the page counts far more than cosmetic or expectation issues."""
    return sum(weight(e) for e in errors)


def model_summary(blocks, info):
    names = re.findall(r"^(?:const|let|var|function)\s+([A-Za-z_$][\w$]*)", blocks.get("MODEL", ""), re.M)
    return ("(unchanged; summary) declares: " + ", ".join(names) + "\nDEFAULT_STATE keys: " + ", ".join(info.get("state_keys", []))
            + "\ncompute() returns keys: " + ", ".join(info.get("default_result_keys", [])) + "\nPRESETS: " + ", ".join(info.get("presets", [])))


def fmt_blocks(blocks, names):
    return "\n".join(f"@@{n}\n{blocks.get(n, '(missing)')}" for n in names) + "\n@@END"


def main():
    ap = argparse.ArgumentParser(description="Turn a paper excerpt + learning brief into an interactive explainer page.")
    ap.add_argument("--input", required=True)
    ap.add_argument("--output", required=True)
    ap.add_argument("--model", required=True)
    ap.add_argument("--max-repairs", type=int, default=1)
    ap.add_argument("--gen-max-tokens", type=int, default=16000)
    ap.add_argument("--web-search", action="store_true",
                    help="optional: one small extra call using OpenRouter's server-side web plugin to research how this concept is usually visualised")
    ap.add_argument("--effort", default="", help="optional OpenRouter reasoning effort (low/medium/high); default: model default")
    args = ap.parse_args()

    os.makedirs(args.output, exist_ok=True)
    trace = Trace(os.path.join(args.output, "trace.jsonl"), T0)
    trace("setup", "start", "ok", model=args.model, input=args.input, limits={"requests": 10, "completion_tokens": 30000, "seconds": 600})
    try:
        return run(args, trace)
    except Exception as e:  # never die without a trace record
        trace("done", "fatal", "error", error=f"{type(e).__name__}: {str(e)[:500]}", elapsed_s=round(time.time() - T0, 2))
        print(f"error: {e}", file=sys.stderr)
        return 1
    finally:
        trace.close()


def run(args, trace):
    # ---- input
    try:
        case = json.load(open(args.input, encoding="utf-8"))
        assert isinstance(case, dict)
    except Exception as e:
        trace("setup", "read_input", "error", error=str(e)[:300])
        return 2
    missing = [k for k in ("source_url", "focus", "audience") if not str(case.get(k, "")).strip()]
    trace("setup", "read_input", "ok" if not missing else "warning", fields=sorted(case), missing=missing)
    key = load_key()
    if not key:
        trace("setup", "api_key", "error", error="OPENROUTER_API_KEY not set")
        print("error: OPENROUTER_API_KEY not set", file=sys.stderr)
        return 2

    # ---- source
    extra = source.gather(case, trace)
    case_txt = json.dumps({k: (v[:20000] if isinstance(v, str) else v) for k, v in case.items()}, ensure_ascii=False, indent=1)
    src_txt = f"\nSOURCE TEXT (fetched from source_url; most relevant part):\n<<<\n{extra}\n>>>\n" if extra else ""

    llm = LLM(args.model, key, trace, T0)
    xtra = {"reasoning": {"effort": args.effort, "exclude": True}} if args.effort else None
    system = {"role": "system", "content": prompts.SYSTEM}

    # ---- optional visual-design research (OpenRouter web plugin; off by default to save tokens)
    if args.web_search:
        q = ("In 3-5 short bullet points, how is the following concept best visualised for teaching (diagrams, metaphors, "
             "interactive demos that make the mechanism intuitive)? Concept: " + str(case.get("focus", ""))[:600])
        try:
            ideas, _ = llm.chat("design_research", [{"role": "user", "content": q}], max_tokens=400,
                                extra={"plugins": [{"id": "web", "max_results": 3}]})
            ideas = re.sub(r"\[([^\]]+)\]\((https?://[^)]+)\)", r"\1", ideas)[:1500]
            src_txt += "\nVISUALISATION IDEAS (from a web search; adapt, do not copy):\n" + ideas + "\n"
            trace("design_research", "web_search", "ok", chars=len(ideas))
        except (BudgetError, RuntimeError) as e:
            trace("design_research", "web_search", "failed", error=str(e)[:200], note="continuing without it")

    # ---- generate (plan + all blocks in one call)
    trace("generate", "request", "started", note="single call: plan, metadata, intro, playground, model, ui, explorations, grounding")
    text, finish = llm.chat("generate", [system, {"role": "user", "content": prompts.USER.format(case=case_txt, source=src_txt)}],
                            max_tokens=args.gen_max_tokens, extra=xtra)
    dbg(args, "gen_raw.txt", text)
    blocks = parse_blocks(text, truncated=finish == "length")
    trace("generate", "parse_blocks", "ok" if all(b in blocks for b in CORE) else "incomplete",
          blocks={k: len(v) for k, v in blocks.items()}, finish_reason=finish)
    if blocks.get("PLAN"):
        trace("plan", "model_plan", "ok", plan=blocks["PLAN"][:1500])

    # ---- check / repair loop
    best, best_n, prev_errors = None, None, set()
    try:
        for rnd in range(args.max_repairs + 2):
            fixes = checks.sanitize(blocks)
            if fixes:
                trace("check", "sanitize", "fixed", fixes=fixes, round=rnd)
            t = time.time()
            res = checks.check(blocks)
            n_err = severity(res["errors"])
            trace("check", "run_checks", "pass" if not n_err else "fail", round=rnd, errors=res["errors"], warnings=res["warnings"],
                  tests=res["report"].get("tests"), info=res["report"].get("info"), elapsed_s=round(time.time() - t, 2))
            if best_n is None or n_err <= best_n:
                best, best_n = dict(blocks), n_err
            else:
                trace("revise", "rollback", "kept_previous", reason=f"revision error score {n_err} vs {best_n} (fatal errors weigh 100)", round=rnd)
                blocks = dict(best)
            if best_n == 0 or (rnd >= args.max_repairs and not (rnd == args.max_repairs and best_n >= 100 and llm.requests < 8)):
                break  # one extra round is allowed only while a fatal error survives
            if all(re.match(r'TEST "', e) or (re.match(r'invariant "', e) and " for control #" not in e) for e in res["errors"]):
                trace("revise", "stop", "expectations_only", round=rnd,
                      reason="only model-proposed test/invariant expectations disagree with the executed computation; pruning them instead of spending tokens")
                break
            if rnd > 0 and set(res["errors"]) == prev_errors:
                trace("revise", "stop", "no_progress", reason="revision left the same errors; not spending more tokens", round=rnd)
                break
            prev_errors = set(res["errors"])
            names = blocks_for(res["errors"] if n_err else [], blocks)
            if not names:
                break
            if llm.time_left() < 120:
                trace("revise", "skip", "time_budget", time_left_s=round(llm.time_left()))
                break
            shown = dict(blocks)
            context = list(names)
            if set(names) & {"UI", "EXPLORE"}:
                if "PLAYGROUND" not in context and blocks.get("PLAYGROUND"):
                    context.append("PLAYGROUND")  # ids the fixed blocks must match (small)
                if "MODEL" not in context and blocks.get("MODEL"):
                    context.append("MODEL")
                    shown["MODEL"] = model_summary(blocks, res["report"].get("info") or {})
            ranked = sorted(res["errors"], key=lambda e: -weight(e))
            msg = prompts.REPAIR.format(problems="\n".join(("- [FATAL: page is dead until fixed] " if weight(e) >= 100 else "- ") + e for e in ranked[:25]) + ("\nAlso (warnings):\n" + "\n".join("- " + w for w in res["warnings"][:8]) if res["warnings"] else ""),
                                        blocks=fmt_blocks(shown, [b for b in prompts.BLOCKS if b in context]), names=", ".join(names))
            est = sum(len(blocks[n]) // 2 if blocks.get(n) else 3000 for n in names) + 2500
            trace("revise", "request", "started", round=rnd + 1, blocks=names, n_errors=n_err)
            try:
                fix_text, finish = llm.chat("revise", [system, {"role": "user", "content": msg}], max_tokens=max(5000, min(14000, est)), extra=xtra)
            except (BudgetError, RuntimeError) as e:
                trace("revise", "request", "aborted", error=str(e)[:300])
                break
            dbg(args, f"revise{rnd + 1}_raw.txt", fix_text)
            fixed = parse_blocks(fix_text, truncated=finish == "length")
            fixed = {k: v for k, v in fixed.items() if k in names and v.strip()}
            blocks = dict(blocks)
            blocks.update(fixed)
            blocks, edited, failed = apply_edits(blocks, fix_text)
            trace("revise", "apply", "ok" if (fixed or edited) else "nothing_applied", round=rnd + 1, replaced=sorted(fixed),
                  edited=edited, failed_edits=failed, finish_reason=finish)
    except Exception as e:  # a checker/sanitizer bug must never cost the page: keep what we have and write it
        trace("check", "internal_error", "continuing", error=f"{type(e).__name__}: {str(e)[:300]}",
              note="writing the best version available")
        if best is None:
            best, best_n = dict(blocks), 999

    blocks = best if best is not None else blocks
    try:
        final = checks.check(blocks)
        dropped = sorted({m.group(1) for e in final["errors"] for m in [re.match(r'TEST "(.*)" (?:failed|threw)', e)] if m})
        bad_inv = sorted({m.group(1) for e in final["errors"] for m in [re.match(r'invariant "(.*)" fails for ', e)] if m})
        if dropped or bad_inv:  # unverifiable model-proposed expectations: exclude from the page, disclose on page and in trace
            blocks["MODEL"] = blocks.get("MODEL", "") + "\nconst __DROP_TESTS = " + json.dumps(dropped) + ";\nconst __DROP_INV = " + json.dumps(bad_inv) + ";"
            trace("check", "prune_expectations", "excluded", tests=dropped, invariants=bad_inv,
                  reason="model-proposed expectation did not match the executed computation")
    except Exception as e:
        final = {"errors": ["final check unavailable"]}
        trace("check", "internal_error", "continuing", stage_detail="final check", error=f"{type(e).__name__}: {str(e)[:300]}")
    if os.environ.get("P2P_DEBUG"):  # dev only: keep raw blocks to re-assemble after template changes
        json.dump(blocks, open(os.path.join(args.output, "blocks.json"), "w"), indent=1)
    # ---- write
    page = assemble(blocks, case)
    out = os.path.join(args.output, "index.html")
    with open(out, "w", encoding="utf-8") as f:
        f.write(page)
    ok = all(blocks.get(b, "").strip() for b in CORE)
    tot = llm.totals()
    trace("write", "index.html", "ok" if ok else "incomplete", bytes=len(page.encode("utf-8")), remaining_errors=len(final["errors"]), error_score=best_n)
    trace("done", "summary", "success" if ok else "failure", elapsed_s=round(time.time() - T0, 2), remaining_errors=len(final["errors"]), error_score=best_n, **tot)
    print(json.dumps({"ok": ok, "remaining_errors": len(final["errors"]), "error_score": best_n, "elapsed_s": round(time.time() - T0, 1), **tot}))
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
