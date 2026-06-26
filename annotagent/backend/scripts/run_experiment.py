"""Backend-only experiment runner: baseline vs optimized, honest held-out test.

Mirrors the production `api/optimizers.py::_execute_run` path (3-way
leakage-guarded stratified split + held-out test eval) but runs entirely from
the command line against a gold JSON — no DB, no frontend. Use this to fill the
baseline-vs-optimized table.

Unlike `scripts/run_optimizer.py` (which reports val-only on a simple split),
this reports the honest TEST numbers: the optimizer sees only train + val, and
the final/initial prompts are scored once on a held-out test set it never saw.

Example:
    python -m scripts.run_experiment \
        --name reflect_agent \
        --codebook self_disclosure \
        --dimension "Depth of disclosure" \
        --gold ../assets/data/cleaned/agreed_self_disclosure_ground_truth.json \
        --model gpt-5.4-mini --budget 5 \
        --out runs/depth_agreed.json

Smoke test (cheap, 1 round):
    python -m scripts.run_experiment --name reflect_agent \
        --dimension "Depth of disclosure" \
        --gold ../assets/data/cleaned/agreed_self_disclosure_ground_truth.json \
        --budget 1
"""
from __future__ import annotations

import argparse
import asyncio
import json
import random
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.config import resolve_api_key
from app.engine.codebook_parser import parse_codebook
from app.engine.metrics import compute_metrics
from app.engine.prompt_generator import generate_dimension_prompt
from app.optimizers import Example, evaluate_prompt, get_optimizer, list_optimizers
from app.optimizers.base import audit_prompt_for_leakage


def load_gold_items(path: str, dimension: str) -> list[Example]:
    """Load (sentence, gold) pairs for one dimension, skipping unlabeled items."""
    with open(path) as f:
        data = json.load(f)
    items = data["items"] if isinstance(data, dict) else data
    out: list[Example] = []
    for it in items:
        labels = it.get("labels", it.get("gold_labels", {})) or {}
        raw = labels.get(dimension)
        if raw is None or str(raw).strip() == "":
            continue
        out.append(Example(
            sentence=it.get("sentence", it.get("content", "")),
            gold=str(raw).strip(),
            context=str(it.get("context", "")),
        ))
    return out


def stratified_split(
    examples: list[Example], *, train_frac: float, val_frac: float, seed: int,
) -> tuple[list[Example], list[Example], list[Example], dict[str, dict[str, int]]]:
    """Group by gold label, deterministic-shuffle each group, slice proportionally.

    Same logic as api/optimizers.py::_stratified_split. Classes with <3 items go
    entirely to train (the optimizer can still see them in failure mining; they
    won't appear in val/test). Guarantees ≥1 item per split for classes ≥3.
    """
    by_class: dict[str, list[Example]] = {}
    for ex in examples:
        by_class.setdefault(ex.gold, []).append(ex)

    rng = random.Random(seed)
    train: list[Example] = []
    val: list[Example] = []
    test: list[Example] = []
    per_class: dict[str, dict[str, int]] = {}

    for cls in sorted(by_class):
        group = list(by_class[cls])
        rng.shuffle(group)
        n = len(group)
        if n < 3:
            train.extend(group)
            per_class[cls] = {"n": n, "train": n, "val": 0, "test": 0}
            continue
        nt = max(1, int(round(train_frac * n)))
        nv = max(1, int(round(val_frac * n)))
        if nt + nv > n - 1:
            nv = max(1, n - nt - 1)
        nx = n - nt - nv
        train.extend(group[:nt])
        val.extend(group[nt:nt + nv])
        test.extend(group[nt + nv:])
        per_class[cls] = {"n": n, "train": nt, "val": nv, "test": nx}

    rng.shuffle(train)
    rng.shuffle(val)
    rng.shuffle(test)
    return train, val, test, per_class


async def main() -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--name", default="reflect_agent", help=f"optimizer: {[o['name'] for o in list_optimizers()]}")
    p.add_argument("--codebook", default="self_disclosure", help="preset name under app/presets/")
    p.add_argument("--dimension", required=True, help="dimension name as it appears in gold labels")
    p.add_argument("--gold", required=True, help="path to agreed/gold JSON")
    p.add_argument("--train-frac", type=float, default=0.15)
    p.add_argument("--val-frac", type=float, default=0.42)
    p.add_argument("--seed", type=int, default=17)
    p.add_argument("--limit", type=int, default=0, help="subsample N labeled examples for a quick smoke run (0 = all)")
    p.add_argument("--provider", default="openai")
    p.add_argument("--model", default="gpt-5.4-mini")
    p.add_argument("--api-key", default="", help="overrides .env / OPENAI_API_KEY")
    p.add_argument("--budget", type=int, default=5, help="optimizer rounds (use 1 for smoke)")
    p.add_argument("--out", default="", help="optional path to write a JSON report")
    args = p.parse_args()

    api_key = args.api_key or resolve_api_key(args.provider)
    if not api_key:
        print("error: no API key (set --api-key, OPENAI_API_KEY, or a .env)", file=sys.stderr)
        return 2

    # Codebook → initial prompt for this dimension
    preset_path = Path(__file__).resolve().parent.parent / "app" / "presets" / f"{args.codebook}.json"
    codebook = parse_codebook(json.load(open(preset_path)))
    dim_def = next((d for d in codebook.dimensions if d.name == args.dimension), None)
    if dim_def is None:
        print(f"error: dimension '{args.dimension}' not in codebook. Available: "
              f"{[d.name for d in codebook.dimensions]}", file=sys.stderr)
        return 2
    initial_prompt = generate_dimension_prompt(dim_def)
    valid_labels = [l.name for l in dim_def.labels]
    label_defs = "\n".join(f"- {l.name}: {l.definition}" for l in dim_def.labels)

    # Load gold, optionally subsample, then 3-way stratified split
    all_ex = load_gold_items(args.gold, args.dimension)
    if args.limit and len(all_ex) > args.limit:
        random.Random(args.seed).shuffle(all_ex)
        all_ex = all_ex[: args.limit]
    if len(all_ex) < 15:
        print(f"error: only {len(all_ex)} labeled examples for '{args.dimension}' — need ≥15 for a 3-way split",
              file=sys.stderr)
        return 2

    trainset, valset, testset, per_class = stratified_split(
        all_ex, train_frac=args.train_frac, val_frac=args.val_frac, seed=args.seed,
    )
    n_train, n_val, n_test = len(trainset), len(valset), len(testset)
    if n_train < 5 or n_val < 5:
        print(f"error: after stratification train={n_train} val={n_val} test={n_test} "
              f"(per_class={per_class}); need ≥5 train and ≥5 val", file=sys.stderr)
        return 2

    # Leakage guard — the three splits must be disjoint (object identity)
    assert len({id(x) for x in trainset} & {id(x) for x in valset}) == 0
    assert len({id(x) for x in valset} & {id(x) for x in testset}) == 0
    assert len({id(x) for x in trainset} & {id(x) for x in testset}) == 0

    print(f"Optimizer:  {args.name}   Model: {args.model}   Budget: {args.budget}")
    print(f"Dimension:  {args.dimension}  (labels: {valid_labels})")
    print(f"Gold:       {args.gold}")
    print(f"Split:      {n_train} train · {n_val} val · {n_test} test   (seed={args.seed})")
    print(f"Per-class:  {per_class}\n")

    # Optimizer sees train + val only. Test is held out.
    opt = get_optimizer(
        args.name, provider=args.provider, model=args.model, api_key=api_key,
        budget=args.budget, label_defs=label_defs,
    )
    result = await opt.optimize(initial_prompt, args.dimension, valid_labels, trainset, valset)

    print(f"[val]  initial {result.initial_score*100:5.1f}%  →  final {result.final_score*100:5.1f}%  "
          f"(Δ {100*(result.final_score - result.initial_score):+.1f}pp)  ← optimizer's internal signal\n")

    # ─── Held-out test: the honest baseline vs optimized ───
    ti_acc, ti_preds, ti_tok = await evaluate_prompt(
        initial_prompt, testset, valid_labels, provider=args.provider, model=args.model, api_key=api_key)
    tf_acc, tf_preds, tf_tok = await evaluate_prompt(
        result.optimized_prompt, testset, valid_labels, provider=args.provider, model=args.model, api_key=api_key)
    y_true = [ex.gold for ex in testset]
    ti_metrics = compute_metrics(y_true, ti_preds)
    tf_metrics = compute_metrics(y_true, tf_preds)
    audit = audit_prompt_for_leakage(result.optimized_prompt, valset, testset)

    print("════════ HELD-OUT TEST (honest baseline vs optimized) ════════")
    print(f"  baseline   acc {ti_acc*100:5.1f}%   macro-F1 {ti_metrics['macro_f1']*100:5.1f}%")
    print(f"  optimized  acc {tf_acc*100:5.1f}%   macro-F1 {tf_metrics['macro_f1']*100:5.1f}%")
    print(f"  Δ          acc {100*(tf_acc-ti_acc):+.1f}pp  macro-F1 {100*(tf_metrics['macro_f1']-ti_metrics['macro_f1']):+.1f}pp")
    print(f"  n_test={n_test}   leakage_audit={'clean' if audit['clean'] else 'FAILED'}")
    tot_tok = result.total_tokens + ti_tok + tf_tok
    print(f"  tokens={tot_tok:,}")
    if result.artifact and "rule_library" in result.artifact:
        print(f"  rule_library size: {len(result.artifact['rule_library'])}")
    print("══════════════════════════════════════════════════════════════")

    if args.out:
        out_path = Path(args.out)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        with open(out_path, "w") as f:
            json.dump({
                "optimizer": args.name, "dimension": args.dimension, "model": args.model,
                "gold": args.gold, "budget": args.budget, "seed": args.seed,
                "splits": {"n_train": n_train, "n_val": n_val, "n_test": n_test, "per_class": per_class},
                "val": {"initial": result.initial_score, "final": result.final_score},
                "test": {
                    "baseline_acc": ti_acc, "optimized_acc": tf_acc,
                    "baseline_metrics": ti_metrics, "optimized_metrics": tf_metrics,
                },
                "audit": audit,
                "trajectory": result.trajectory,
                "optimized_prompt": result.optimized_prompt,
                "total_tokens": tot_tok,
            }, f, indent=2)
        print(f"\nReport written to {out_path}")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
