"""Rigorous multi-label multi-seed evaluation (fixes the AI Behavior row).

What the reviewer flagged in the old runs (exp_result/exp_result_ai_behavior_*):
  1. "three seeds" mixed one full-data run (n_test 70-88) with two 50-item runs
     (n_test 15). This driver uses the FULL dataset for every seed.
  2. non-stratified 40/30/30 split. This driver uses label-balanced iterative
     stratification at the same 15/42/43 fractions as the single-label protocol.
  3. only zero_shot + approach_B were saved. This runs all three conditions
     (zero_shot, approach_A = stock ReflectAgent exploded, approach_B = native
     multi-label optimizer) on the SAME split, so approach_B's advantage over the
     naive exploded baseline is an honest ablation.

Everything is saved per (coder, seed): split composition, prompts, rules,
per-item predictions, and metrics. Aggregation + paired bootstrap run at the end.

Run from annotagent/backend (needs an API key in env / .env):
  ./.venv/bin/python scripts/run_multilabel_multiseed.py \
      --coders fiona,chang --dim "Listening strategy" --seeds 0,1,2 \
      --train 0.15 --val 0.42 --budget 5 \
      --outdir ../../exp_result/multilabel_rigorous
"""
from __future__ import annotations

import argparse
import asyncio
import json
import statistics
import sys
from datetime import datetime
from pathlib import Path

BACKEND = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from app.config import resolve_api_key  # noqa: E402
from app.engine.codebook_parser import parse_codebook  # noqa: E402
from app.engine.prompt_generator import generate_dimension_prompt  # noqa: E402
from app.optimizers import Example, get_optimizer  # noqa: E402
from run_per_user_eval import _load_items, PRESETS_DIR  # noqa: E402
# Reuse the already-working multi-label building blocks; only the split changes.
from multilabel_diag import (  # noqa: E402
    build_ml_prompt, score, approach_B, _explode, gold_set,
)
from multilabel_stratify import (  # noqa: E402
    iterative_stratification, split_report, paired_bootstrap_delta,
)


async def run_one(coder, dim_name, valid, cb_dim, items, seed, args):
    # gold_set / score / _explode need the dimension OBJECT (they read .name);
    # dim_name (str) is only used for the ReflectAgent `dimension=` arg + config.
    label_sets = [gold_set(it, cb_dim, valid) for it in items]
    assignment = iterative_stratification(
        label_sets,
        {"train": args.train, "val": args.val, "test": 1.0 - args.train - args.val},
        seed=seed,
    )
    train = [items[i] for i in assignment["train"]]
    val = [items[i] for i in assignment["val"]]
    test = [items[i] for i in assignment["test"]]
    report = split_report(label_sets, assignment)
    print(f"\n[{coder} seed={seed}] {len(items)} items -> "
          f"train {len(train)} / val {len(val)} / test {len(test)}")

    conditions = {}

    # 1. zero-shot set prompt
    zs_prompt = build_ml_prompt(cb_dim, [])
    m, preds, tok = await score(zs_prompt, test, cb_dim, valid, args)
    conditions["zero_shot"] = {"prompt": zs_prompt, "rules": [], "test_metrics": m,
                               "test_predictions": preds, "tokens": tok}
    print(f"  zero_shot   micro {m['micro_f1']:.3f}  macro {m['macro_f1']:.3f}  exact {m['accuracy']:.3f}")

    # 2. approach_A: stock single-label ReflectAgent rules injected into set prompt
    if not args.skip_a:
        tr_ex, va_ex = _explode(train, cb_dim, valid), _explode(val, cb_dim, valid)
        opt = get_optimizer("reflect_agent", provider=args.provider, model=args.model,
                            api_key=args.api_key, budget=args.budget,
                            label_defs="\n".join(f"- {l.name}: {l.definition}" for l in cb_dim.labels),
                            seed_rules=[])
        res = await opt.optimize(initial_prompt=generate_dimension_prompt(cb_dim), dimension=dim_name,
                                 valid_labels=valid, trainset=tr_ex, valset=va_ex)
        a_rules = list((res.artifact or {}).get("rule_library") or [])
        a_prompt = build_ml_prompt(cb_dim, a_rules)
        m, preds, tok = await score(a_prompt, test, cb_dim, valid, args)
        conditions["approach_A"] = {"prompt": a_prompt, "rules": a_rules, "test_metrics": m,
                                    "test_predictions": preds, "tokens": tok + res.total_tokens}
        print(f"  approach_A  micro {m['micro_f1']:.3f}  macro {m['macro_f1']:.3f}  exact {m['accuracy']:.3f}  ({len(a_rules)} rules)")

    # 3. approach_B: native multi-label optimizer (set-F1 governor)
    b_prompt, b_rules, b_traj, b_tok = await approach_B(cb_dim, valid, train, val, args)
    m, preds, tok = await score(b_prompt, test, cb_dim, valid, args)
    conditions["approach_B"] = {"prompt": b_prompt, "rules": b_rules, "val_trajectory": b_traj,
                                "test_metrics": m, "test_predictions": preds, "tokens": tok + b_tok}
    print(f"  approach_B  micro {m['micro_f1']:.3f}  macro {m['macro_f1']:.3f}  exact {m['accuracy']:.3f}  ({len(b_rules)} rules)")

    return {
        "generated": datetime.now().strftime("%Y-%m-%d %H:%M"),
        "config": {"coder": coder, "dim": dim_name, "seed": seed, "labels": valid,
                   "model": args.model, "budget": args.budget,
                   "train_frac": args.train, "val_frac": args.val,
                   "n_items": len(items), "n_train": len(train), "n_val": len(val), "n_test": len(test)},
        "split_report": report,
        "conditions": conditions,
    }


def _preds_as_sets(cond):
    """Rebuild (golds, preds) as list[set] from a saved condition's predictions."""
    golds = [set(p["gold"]) for p in cond["test_predictions"]]
    preds = [set(p["pred"]) for p in cond["test_predictions"]]
    return golds, preds


def _is_valid_run(run):
    """A run is invalid if any OPTIMIZED condition has >50% empty predictions,
    which means the LLM calls failed en masse (quota/rate/network) and the
    metrics are a zero artifact, not a real result. Averaging such a seed in
    would silently corrupt the mean (as an OpenAI quota exhaustion once did to
    chang_seed2). Excluded seeds are reported, never hidden."""
    for cond in ("approach_A", "approach_B"):
        c = run["conditions"].get(cond)
        if not c:
            continue
        preds = c.get("test_predictions") or []
        if preds and sum(1 for p in preds if not p["pred"]) / len(preds) > 0.5:
            return False
    return True


def aggregate(all_runs, outdir):
    """Per coder: mean+/-std micro/macro over seeds, and paired bootstrap on the
    seed-0 test set for approach_B - zero_shot and approach_B - approach_A."""
    excluded = []
    for coder in list(all_runs):
        valid = []
        for r in all_runs[coder]:
            if _is_valid_run(r):
                valid.append(r)
            else:
                excluded.append(f"{coder}_seed{r['config']['seed']}")
        all_runs[coder] = valid
    all_runs = {c: rs for c, rs in all_runs.items() if rs}
    lines = ["# Rigorous multi-label evaluation (Listening strategy)\n"]
    if excluded:
        lines.append(f"**Excluded seeds (API failure, >50% empty preds):** {excluded}\n")
    lines.append("Full dataset every seed; label-balanced stratified 15/42/43 split; "
                 "3 conditions on the same split. micro-F1 (%), mean+/-std over seeds.\n")
    summary = {}
    for coder, runs in all_runs.items():
        conds = [c for c in ("zero_shot", "approach_A", "approach_B") if c in runs[0]["conditions"]]
        lines.append(f"\n## Coder: {coder}\n")
        lines.append("| Condition | micro-F1 | macro-F1 | exact-match |")
        lines.append("|---|---|---|---|")
        coder_sum = {}
        for c in conds:
            micro = [r["conditions"][c]["test_metrics"]["micro_f1"] * 100 for r in runs]
            macro = [r["conditions"][c]["test_metrics"]["macro_f1"] * 100 for r in runs]
            exact = [r["conditions"][c]["test_metrics"]["accuracy"] * 100 for r in runs]
            mu = statistics.mean(micro)
            sd = statistics.stdev(micro) if len(micro) > 1 else 0.0
            lines.append(f"| {c} | {mu:.1f} +/- {sd:.1f} | "
                         f"{statistics.mean(macro):.1f} +/- {(statistics.stdev(macro) if len(macro)>1 else 0):.1f} | "
                         f"{statistics.mean(exact):.1f} |")
            coder_sum[c] = {"micro_mean": mu, "micro_std": sd, "micro_per_seed": micro}
        # deltas
        if "zero_shot" in conds and "approach_B" in conds:
            d = coder_sum["approach_B"]["micro_mean"] - coder_sum["zero_shot"]["micro_mean"]
            lines.append(f"\n**approach_B - zero_shot (mean micro):** {d:+.1f} pp")
        if "approach_A" in conds and "approach_B" in conds:
            d = coder_sum["approach_B"]["micro_mean"] - coder_sum["approach_A"]["micro_mean"]
            lines.append(f"**approach_B - approach_A (mean micro):** {d:+.1f} pp")
        # paired bootstrap on seed-0 test set (same items for all conditions)
        r0 = runs[0]["conditions"]
        if "zero_shot" in r0 and "approach_B" in r0:
            golds, pb = _preds_as_sets(r0["approach_B"])
            _, pz = _preds_as_sets(r0["zero_shot"])
            pt, lo, hi = paired_bootstrap_delta(golds, pb, pz)
            lines.append(f"\nSeed-0 paired bootstrap, approach_B - zero_shot micro-F1: "
                         f"{pt:+.1f} pp (95% CI [{lo:+.1f}, {hi:+.1f}])")
        summary[coder] = coder_sum
    (outdir / "SUMMARY.md").write_text("\n".join(lines))
    (outdir / "summary.json").write_text(json.dumps(summary, indent=2))
    print("\n" + "\n".join(lines))
    print(f"\nWrote {outdir/'SUMMARY.md'} and {outdir/'summary.json'}")


async def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--coders", default="fiona,chang")
    ap.add_argument("--codebook", default="ai_behavior")
    ap.add_argument("--dim", default="Listening strategy")
    ap.add_argument("--seeds", default="0,1,2")
    ap.add_argument("--train", type=float, default=0.15)
    ap.add_argument("--val", type=float, default=0.42)
    ap.add_argument("--budget", type=int, default=5)
    ap.add_argument("--provider", default="openai")
    ap.add_argument("--model", default="gpt-5.4-mini")
    ap.add_argument("--concurrency", type=int, default=8)
    ap.add_argument("--skip-a", action="store_true", help="skip approach_A (stock ReflectAgent)")
    ap.add_argument("--outdir", default=str(BACKEND.parent.parent / "exp_result" / "multilabel_rigorous"))
    args = ap.parse_args()
    args.api_key = resolve_api_key(args.provider)
    if not args.api_key:
        raise SystemExit("No API key. Put OPENAI_API_KEY in annotagent/.env or the environment.")

    outdir = Path(args.outdir)
    outdir.mkdir(parents=True, exist_ok=True)

    cb = parse_codebook(json.loads((PRESETS_DIR / f"{args.codebook}.json").read_text()))
    cb_dim = next(d for d in cb.dimensions if d.name == args.dim)
    valid = [l.name for l in cb_dim.labels]

    seeds = [int(s) for s in args.seeds.split(",")]
    all_runs: dict[str, list] = {}
    for coder in args.coders.split(","):
        items = _load_items(coder, args.codebook)
        items = [it for it in items if gold_set(it, cb_dim, valid)]
        if not items:
            print(f"[skip] {coder}: no items carry '{args.dim}'")
            continue
        all_runs[coder] = []
        for seed in seeds:
            run = await run_one(coder, args.dim, valid, cb_dim, items, seed, args)
            (outdir / f"{coder}_seed{seed}.json").write_text(json.dumps(run, indent=2))
            all_runs[coder].append(run)

    aggregate(all_runs, outdir)


if __name__ == "__main__":
    asyncio.run(main())
