"""Multi-label eval diagnostic: race three conditions on a small subset and save
everything, so we never re-run to recover data we forgot to keep.

Conditions (all predict a SET of labels per item, scored with set-based metrics):
  - zero_shot : the multi-label set-prompt straight from the codebook.
  - approach_A: stock ReflectAgent (single-label governor, learns a rule library
                by exploding multi-label items), whose learned rules are injected
                into the set-prompt. Optimizer unchanged.
  - approach_B: a NEW multi-label optimizer whose governor scores set macro-F1 on
                validation and mines rules from set errors (missed labels = recall
                misses, wrongly-added = precision misses).

Both micro- and macro- precision/recall/F1 are reported (plus exact-match).

Run (from annotagent/backend):
  ./.venv/bin/python scripts/multilabel_diag.py --user fiona --dim "Listening strategy" \
      --limit 50 --budget 3 --out /tmp/ml_diag_fiona.json
"""
from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import random
import re
import sys
from datetime import datetime
from pathlib import Path

BACKEND = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND))
sys.path.insert(0, str(Path(__file__).resolve().parent))  # sibling import

from app.config import resolve_api_key  # noqa: E402
from app.engine.codebook_parser import parse_codebook  # noqa: E402
from app.engine.llm_client import call_llm  # noqa: E402
from app.engine.metrics import compute_metrics_multilabel  # noqa: E402
from app.engine.prompt_generator import generate_dimension_prompt  # noqa: E402
from app.optimizers import Example, get_optimizer  # noqa: E402
from run_per_user_eval import _match_label, _norm, _load_items, PRESETS_DIR  # noqa: E402

SEP = " | "


# ── multi-label prompt / parsing / scoring ───────────────────────────────────

def _rule_text(rule) -> str:
    if isinstance(rule, str):
        return rule
    return rule.get("rule") or rule.get("boundary") or json.dumps(rule)[:200]


def build_ml_prompt(dim, rules: list) -> str:
    lines = [
        f'You are an expert annotator for the dimension "{dim.name}".',
        "An utterance may express SEVERAL of these labels at once, or none. "
        "Select ALL labels that apply.",
        "",
        "Labels:",
    ]
    for l in dim.labels:
        lines.append(f"- {l.name}: {l.definition}")
    if rules:
        lines += ["", "## Learned rules"]
        lines += [f"- {_rule_text(r)}" for r in rules]
    lines += [
        "",
        f'Respond with the applicable label names exactly as written above, separated by "{SEP.strip()}". '
        'If none apply, respond "None".',
    ]
    return "\n".join(lines)


def parse_set(text: str, valid: list[str]) -> set[str]:
    t = (text or "").strip()
    if not t or _norm(t) in ("none", "n a", "na"):
        return set()
    out: set[str] = set()
    for part in re.split(r"[|\n]", t):           # split on | / newline (NOT comma:
        m = _match_label(part, valid)            # one label contains commas)
        if m:
            out.add(m)
    nt = _norm(t)                                # fallback: full label name present
    for l in valid:
        if _norm(l) and _norm(l) in nt:
            out.add(l)
    return out


def gold_set(item: dict, dim, valid: list[str]) -> set[str]:
    labels = item.get("labels", {})
    raw = labels.get(dim.name)
    if raw is None:
        for k, v in labels.items():
            if _norm(k) == _norm(dim.name):
                raw = v
                break
    if raw is None:
        return set()
    raw_list = raw if isinstance(raw, list) else [raw]
    return {m for r in raw_list if (m := _match_label(r, valid))}


async def predict_sets(prompt, items, dim, valid, args):
    sem = asyncio.Semaphore(args.concurrency)

    async def one(it):
        async with sem:
            try:
                resp = await call_llm(
                    messages=[{"role": "system", "content": prompt},
                              {"role": "user", "content": f"Sentence: {it['sentence']}"}],
                    provider=args.provider, model=args.model, api_key=args.api_key, max_tokens=200,
                )
                return parse_set(resp.text, valid), resp.input_tokens + resp.output_tokens
            except Exception:
                return set(), 0

    res = await asyncio.gather(*(one(it) for it in items))
    preds = [r[0] for r in res]
    return preds, sum(r[1] for r in res)


async def score(prompt, items, dim, valid, args):
    golds = [gold_set(it, dim, valid) for it in items]
    preds, tok = await predict_sets(prompt, items, dim, valid, args)
    m = compute_metrics_multilabel([sorted(g) for g in golds], [sorted(p) for p in preds])
    preds_dump = [
        {"sentence": it["sentence"][:300], "gold": sorted(g), "pred": sorted(p)}
        for it, g, p in zip(items, golds, preds)
    ]
    return m, preds_dump, tok


def _explode(items, dim, valid) -> list[Example]:
    out: list[Example] = []
    for it in items:
        for g in gold_set(it, dim, valid):
            out.append(Example(sentence=it["sentence"], gold=g, context=""))
    return out


# ── approach B: a multi-label optimizer (set-F1 governor + set-error mining) ──

async def _mine_rules(dim, valid, failures, existing, args):
    ex_lines = []
    for it, g, p in failures:
        ex_lines.append(
            f'- "{it["sentence"][:180]}"\n  correct: {sorted(g)} | predicted: {sorted(p)} | '
            f'missed: {sorted(g - p)} | wrongly added: {sorted(p - g)}'
        )
    sys_p = (
        f'You improve a MULTI-LABEL classifier for the dimension "{dim.name}". '
        f"Valid labels: {valid}. Below are cases it got wrong: missed labels are recall "
        f"errors, wrongly-added labels are precision errors. Write 1 to 4 SHORT, general "
        f"rules that would fix these mistakes. Abstract the pattern; do NOT quote whole "
        f'sentences. Each rule on its own line starting with "-".'
    )
    existing_txt = "\n".join(f"- {_rule_text(r)}" for r in existing) or "(none yet)"
    user = f"Existing rules:\n{existing_txt}\n\nFailures:\n" + "\n".join(ex_lines)
    try:
        resp = await call_llm(
            messages=[{"role": "system", "content": sys_p}, {"role": "user", "content": user}],
            provider=args.provider, model=args.model, api_key=args.api_key, max_tokens=400,
        )
        rules = [ln.strip()[1:].strip() for ln in resp.text.splitlines() if ln.strip().startswith("-")]
        return rules[:4], resp.input_tokens + resp.output_tokens
    except Exception:
        return [], 0


async def approach_B(dim, valid, train, val, args):
    rules: list[str] = []
    prompt = build_ml_prompt(dim, rules)
    tok = 0
    m, _, t = await score(prompt, val, dim, valid, args)
    tok += t
    best = m["macro_f1"]
    traj = [{"round": 0, "val_macro_f1": m["macro_f1"], "val_micro_f1": m["micro_f1"], "action": "baseline"}]

    for r in range(1, args.budget + 1):
        preds, t = await predict_sets(prompt, train, dim, valid, args); tok += t
        golds = [gold_set(it, dim, valid) for it in train]
        failures = [(it, g, p) for it, g, p in zip(train, golds, preds) if g != p]
        if not failures:
            traj.append({"round": r, "action": "no_failures", "val_macro_f1": best})
            break
        rng = random.Random(r)
        sample = rng.sample(failures, min(12, len(failures)))
        new_rules, t = await _mine_rules(dim, valid, sample, rules, args); tok += t
        if not new_rules:
            traj.append({"round": r, "action": "no_rules", "val_macro_f1": best})
            continue
        cand = build_ml_prompt(dim, rules + new_rules)
        cm, _, t = await score(cand, val, dim, valid, args); tok += t
        if cm["macro_f1"] > best + 1e-9:
            rules = rules + new_rules; prompt = cand; best = cm["macro_f1"]
            action = "accept"
        else:
            action = "rollback"
        traj.append({"round": r, "val_macro_f1": cm["macro_f1"], "val_micro_f1": cm["micro_f1"],
                     "action": action, "n_rules": len(rules)})
    return prompt, rules, traj, tok


# ── driver ───────────────────────────────────────────────────────────────────

def _split_items(items, seed, fr_train=0.4, fr_val=0.3):
    idx = list(range(len(items)))
    random.Random(seed).shuffle(idx)
    n = len(items); nt = int(n * fr_train); nv = int(n * fr_val)
    pick = lambda s: [items[i] for i in s]
    return pick(idx[:nt]), pick(idx[nt:nt + nv]), pick(idx[nt + nv:])


async def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--user", default="fiona")
    ap.add_argument("--codebook", default="ai_behavior")
    ap.add_argument("--dim", default="Listening strategy")
    ap.add_argument("--limit", type=int, default=50)
    ap.add_argument("--budget", type=int, default=3)
    ap.add_argument("--provider", default="openai")
    ap.add_argument("--model", default="gpt-5.4-mini")
    ap.add_argument("--concurrency", type=int, default=8)
    ap.add_argument("--out", default="/tmp/ml_diag.json")
    ap.add_argument("--seed", type=int, default=0, help="split seed index; 0 reproduces the original single-seed run")
    ap.add_argument("--skip-a", action="store_true", help="skip approach A (stock ReflectAgent)")
    args = ap.parse_args()
    args.api_key = resolve_api_key(args.provider)
    if not args.api_key:
        raise SystemExit("No API key.")

    cb = parse_codebook(json.loads((PRESETS_DIR / f"{args.codebook}.json").read_text()))
    dim = next(d for d in cb.dimensions if d.name == args.dim)
    valid = [l.name for l in dim.labels]
    items = _load_items(args.user, args.codebook)
    # keep only items that carry this dimension, then cap.
    items = [it for it in items if gold_set(it, dim, valid)]
    if args.limit:  # 0 = use all items
        items = items[: args.limit]
    seed_key = f"{args.user}|{args.dim}" + (f"|{args.seed}" if args.seed else "")
    seed = int(hashlib.sha256(seed_key.encode()).hexdigest()[:8], 16)
    train, val, test = _split_items(items, seed)
    print(f"{args.user}/{args.dim}: {len(items)} items -> train {len(train)} / val {len(val)} / test {len(test)}")

    out = {
        "generated": datetime.now().strftime("%Y-%m-%d %H:%M"),
        "config": {"user": args.user, "codebook": args.codebook, "dim": dim.name,
                   "labels": valid, "model": args.model, "budget": args.budget,
                   "n_items": len(items), "n_train": len(train), "n_val": len(val), "n_test": len(test)},
        "conditions": {},
    }

    # zero-shot
    zs_prompt = build_ml_prompt(dim, [])
    m, preds, tok = await score(zs_prompt, test, dim, valid, args)
    out["conditions"]["zero_shot"] = {"prompt": zs_prompt, "rules": [], "test_metrics": m,
                                      "test_predictions": preds, "tokens": tok}
    print(f"  zero-shot   micro-F1 {m['micro_f1']:.3f}  macro-F1 {m['macro_f1']:.3f}  exact {m['accuracy']:.3f}")

    # approach A: stock ReflectAgent rules injected into the set-prompt
    if not args.skip_a:
        tr_ex, va_ex = _explode(train, dim, valid), _explode(val, dim, valid)
        opt = get_optimizer("reflect_agent", provider=args.provider, model=args.model,
                            api_key=args.api_key, budget=args.budget,
                            label_defs="\n".join(f"- {l.name}: {l.definition}" for l in dim.labels),
                            seed_rules=[])
        res = await opt.optimize(initial_prompt=generate_dimension_prompt(dim), dimension=dim.name,
                                 valid_labels=valid, trainset=tr_ex, valset=va_ex)
        a_rules = list((res.artifact or {}).get("rule_library") or [])
        a_prompt = build_ml_prompt(dim, a_rules)
        m, preds, tok = await score(a_prompt, test, dim, valid, args)
        out["conditions"]["approach_A"] = {"prompt": a_prompt, "rules": a_rules,
                                           "val_trajectory_singlelabel": res.trajectory,
                                           "test_metrics": m, "test_predictions": preds,
                                           "tokens": tok + res.total_tokens}
        print(f"  approach_A  micro-F1 {m['micro_f1']:.3f}  macro-F1 {m['macro_f1']:.3f}  exact {m['accuracy']:.3f}  ({len(a_rules)} rules)")

    # approach B: multi-label optimizer
    b_prompt, b_rules, b_traj, b_tok = await approach_B(dim, valid, train, val, args)
    m, preds, tok = await score(b_prompt, test, dim, valid, args)
    out["conditions"]["approach_B"] = {"prompt": b_prompt, "rules": b_rules, "val_trajectory": b_traj,
                                       "test_metrics": m, "test_predictions": preds,
                                       "tokens": tok + b_tok}
    print(f"  approach_B  micro-F1 {m['micro_f1']:.3f}  macro-F1 {m['macro_f1']:.3f}  exact {m['accuracy']:.3f}  ({len(b_rules)} rules)")

    Path(args.out).write_text(json.dumps(out, indent=2))
    print(f"\nSaved everything -> {args.out}")


if __name__ == "__main__":
    asyncio.run(main())
