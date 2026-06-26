"""Multi-model sweep — per coworker's C3: "benchmark a few other models' performance".

Runs the same optimizer configuration across several models on the same
(codebook, dimension, gold) and writes one CSV row per model:
    model, n_train, n_val, n_test, zero_shot_test_acc, reflected_test_acc, delta_pp,
    total_tokens, wall_seconds

Example:
    python -m scripts.sweep_models \\
        --codebook goemotions \\
        --dimension Emotion \\
        --gold ../../data/cleaned/goemotions_sample.json \\
        --models openai:gpt-5.4-mini openai:gpt-5.4 anthropic:claude-sonnet-4-5 \\
        --optimizer reflect_agent \\
        --budget 4 \\
        --train-frac 0.15 --val-frac 0.42 --test-frac 0.43 \\
        --out sweep_goemotions.csv

The script respects the same 3-way split + leakage guarantee as the backend:
test items are never passed to the optimizer; every model is scored on the
same held-out test set.
"""
from __future__ import annotations

import argparse
import asyncio
import csv
import json
import os
import random
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.engine.codebook_parser import parse_codebook
from app.engine.prompt_generator import generate_dimension_prompt
from app.optimizers import Example, evaluate_prompt, get_optimizer


def _load_gold_items(path: str, dimension: str) -> list[Example]:
    with open(path) as f:
        data = json.load(f)
    items = data["items"] if isinstance(data, dict) else data
    out: list[Example] = []
    for it in items:
        labels = it.get("labels", it.get("gold_labels", {})) or {}
        if dimension not in labels:
            continue
        gold = labels[dimension]
        # multi-label values may arrive as lists — join into a canonical string
        # so evaluate_prompt's equality check works. ReflectAgent prompts the
        # LLM to emit one label at a time, so lists are flattened to the
        # first (primary) label for the sweep harness.
        if isinstance(gold, list):
            gold = gold[0] if gold else ""
        out.append(Example(
            sentence=it.get("sentence", it.get("content", "")),
            gold=str(gold).strip(),
            context=str(it.get("context", "")),
        ))
    return out


def _parse_model_spec(spec: str) -> tuple[str, str]:
    """provider:model | bare model (defaults to openai)."""
    if ":" in spec:
        provider, model = spec.split(":", 1)
        return provider.strip(), model.strip()
    return "openai", spec.strip()


async def _run_one_model(
    *,
    provider: str, model: str,
    initial_prompt: str, dimension: str, valid_labels: list[str],
    trainset: list[Example], valset: list[Example], testset: list[Example],
    optimizer_name: str, budget: int, label_defs: str,
    api_keys: dict[str, str],
) -> dict:
    api_key = api_keys.get(provider, "")
    t0 = time.perf_counter()

    # Zero-shot test (no optimization) — the honest before-number on held-out
    zs_acc, _, zs_tok = await evaluate_prompt(
        initial_prompt, testset, valid_labels,
        provider=provider, model=model, api_key=api_key,
    )

    # Optimize on train+val, then score on held-out test
    opt = get_optimizer(
        optimizer_name,
        provider=provider, model=model, api_key=api_key,
        budget=budget, label_defs=label_defs,
    )
    result = await opt.optimize(
        initial_prompt=initial_prompt,
        dimension=dimension,
        valid_labels=valid_labels,
        trainset=trainset,
        valset=valset,
    )
    # Held-out test on optimized prompt (leakage guard: testset never saw the optimizer)
    opt_acc, _, t_tok = await evaluate_prompt(
        result.optimized_prompt, testset, valid_labels,
        provider=provider, model=model, api_key=api_key,
    )

    wall = time.perf_counter() - t0

    return {
        "model": f"{provider}:{model}",
        "optimizer": optimizer_name,
        "n_train": len(trainset), "n_val": len(valset), "n_test": len(testset),
        "zero_shot_test_acc": round(zs_acc, 4),
        "reflected_test_acc": round(opt_acc, 4),
        "delta_pp": round((opt_acc - zs_acc) * 100, 2),
        "val_initial": round(result.initial_score, 4),
        "val_final": round(result.final_score, 4),
        "total_tokens": result.total_tokens + zs_tok + t_tok,
        "wall_seconds": round(wall, 1),
    }


async def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--codebook", required=True, help="preset name under app/presets/")
    p.add_argument("--dimension", required=True)
    p.add_argument("--gold", required=True)
    p.add_argument("--optimizer", default="reflect_agent",
                   choices=["reflect_agent", "gepa", "mipro", "opro"])
    p.add_argument("--models", nargs="+", required=True,
                   help="provider:model e.g. openai:gpt-5.4-mini anthropic:claude-sonnet-4-5")
    p.add_argument("--budget", type=int, default=4)
    p.add_argument("--train-frac", type=float, default=0.15)
    p.add_argument("--val-frac", type=float, default=0.42)
    p.add_argument("--test-frac", type=float, default=0.43)
    p.add_argument("--seed", type=int, default=17)
    p.add_argument("--openai-key", default=os.getenv("OPENAI_API_KEY", ""))
    p.add_argument("--anthropic-key", default=os.getenv("ANTHROPIC_API_KEY", ""))
    p.add_argument("--out", default="sweep_results.csv")
    args = p.parse_args()

    # Load codebook + examples
    preset_path = Path(__file__).resolve().parent.parent / "app" / "presets" / f"{args.codebook}.json"
    if not preset_path.exists():
        print(f"error: preset not found at {preset_path}", file=sys.stderr)
        return 2
    codebook = parse_codebook(json.load(open(preset_path)))
    dim = next((d for d in codebook.dimensions if d.name == args.dimension), None)
    if dim is None:
        print(f"error: dimension '{args.dimension}' not in codebook. "
              f"Available: {[d.name for d in codebook.dimensions]}", file=sys.stderr)
        return 2

    initial_prompt = generate_dimension_prompt(dim)
    valid_labels = [l.name for l in dim.labels]
    label_defs = "\n".join(f"- {l.name}: {l.definition}" for l in dim.labels)

    all_ex = _load_gold_items(args.gold, args.dimension)
    if len(all_ex) < 15:
        print(f"error: only {len(all_ex)} gold items for dim — need ≥ 15", file=sys.stderr)
        return 2

    # Validate split
    total = args.train_frac + args.val_frac + args.test_frac
    if abs(total - 1.0) > 0.01:
        print(f"error: train+val+test = {total:.2f}, must equal 1.0", file=sys.stderr)
        return 2

    random.Random(args.seed).shuffle(all_ex)
    n = len(all_ex)
    n_train = max(5, int(round(args.train_frac * n)))
    n_val   = max(5, int(round(args.val_frac * n)))
    n_test  = max(0, n - n_train - n_val)
    if n_test < 3 and n_train > 5:
        steal = min(3 - n_test, n_train - 5)
        n_train -= steal
        n_test  += steal

    trainset = all_ex[:n_train]
    valset   = all_ex[n_train : n_train + n_val]
    testset  = all_ex[n_train + n_val : n_train + n_val + n_test]
    assert not (set(id(x) for x in trainset) & set(id(x) for x in testset))
    assert not (set(id(x) for x in valset)   & set(id(x) for x in testset))

    print(f"=== sweep_models ===")
    print(f"codebook={args.codebook} dim={args.dimension} optimizer={args.optimizer} budget={args.budget}")
    print(f"split: train={n_train} val={n_val} test={n_test}")
    print(f"models: {args.models}")
    print()

    api_keys = {"openai": args.openai_key, "anthropic": args.anthropic_key}

    rows: list[dict] = []
    for spec in args.models:
        provider, model = _parse_model_spec(spec)
        if not api_keys.get(provider):
            print(f"skipping {provider}:{model} — no API key provided")
            continue
        print(f"→ running {provider}:{model} …", flush=True)
        try:
            row = await _run_one_model(
                provider=provider, model=model,
                initial_prompt=initial_prompt, dimension=args.dimension,
                valid_labels=valid_labels,
                trainset=trainset, valset=valset, testset=testset,
                optimizer_name=args.optimizer, budget=args.budget,
                label_defs=label_defs, api_keys=api_keys,
            )
        except Exception as e:
            print(f"  FAILED {provider}:{model}: {e}", file=sys.stderr)
            rows.append({
                "model": f"{provider}:{model}", "optimizer": args.optimizer,
                "n_train": n_train, "n_val": n_val, "n_test": n_test,
                "zero_shot_test_acc": "", "reflected_test_acc": "", "delta_pp": "",
                "val_initial": "", "val_final": "",
                "total_tokens": "", "wall_seconds": "",
                "error": str(e)[:200],
            })
            continue
        rows.append(row)
        print(
            f"  {row['model']:38s}  "
            f"ZS {row['zero_shot_test_acc']*100:5.1f}% → "
            f"OPT {row['reflected_test_acc']*100:5.1f}%  "
            f"(Δ {row['delta_pp']:+.1f} pp)  "
            f"{row['wall_seconds']}s"
        )

    if not rows:
        print("no rows written — all models skipped or failed")
        return 1

    # Write CSV
    fieldnames = list(rows[0].keys())
    for r in rows:
        for k in r.keys():
            if k not in fieldnames:
                fieldnames.append(k)
    with open(args.out, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fieldnames, extrasaction="ignore")
        w.writeheader()
        w.writerows(rows)
    print(f"\nwrote {len(rows)} rows → {args.out}")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
