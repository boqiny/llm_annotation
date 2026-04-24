"""Run any registered prompt optimizer on a codebook dimension.

Example:
    python -m scripts.run_optimizer \
        --name reflect_agent \
        --codebook self_disclosure \
        --dimension "Level of disclosure" \
        --gold ../../data/cleaned/agreed_self_disclosure_ground_truth.json \
        --model gpt-5.4-mini --budget 5

Emits a JSON report with trajectory, artifact (e.g. Rule Library for
ReflectAgent), and final optimized prompt.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import random
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.engine.codebook_parser import parse_codebook
from app.engine.prompt_generator import generate_dimension_prompt
from app.optimizers import Example, get_optimizer, list_optimizers


def load_gold_items(path: str, dimension: str) -> list[Example]:
    with open(path) as f:
        data = json.load(f)
    items = data["items"] if isinstance(data, dict) else data
    out: list[Example] = []
    for it in items:
        labels = it.get("labels", it.get("gold_labels", {})) or {}
        if dimension not in labels:
            continue
        out.append(Example(
            sentence=it.get("sentence", it.get("content", "")),
            gold=str(labels[dimension]).strip(),
            context=str(it.get("context", "")),
        ))
    return out


async def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--name", required=True, help=f"one of: {[o['name'] for o in list_optimizers()]}")
    p.add_argument("--codebook", default="self_disclosure", help="preset name under app/presets/")
    p.add_argument("--dimension", required=True, help="dimension name as it appears in gold labels")
    p.add_argument("--gold", required=True, help="path to agreed/gold JSON")
    p.add_argument("--train-frac", type=float, default=0.7)
    p.add_argument("--seed", type=int, default=17)
    p.add_argument("--provider", default="openai")
    p.add_argument("--model", default="gpt-5.4-mini")
    p.add_argument("--api-key", default=os.getenv("OPENAI_API_KEY", ""))
    p.add_argument("--budget", type=int, default=5)
    p.add_argument("--out", default="")
    args = p.parse_args()

    # Load codebook + generate initial prompt for this dimension
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

    # Load + split gold
    all_ex = load_gold_items(args.gold, args.dimension)
    if len(all_ex) < 10:
        print(f"error: only {len(all_ex)} gold examples for '{args.dimension}' — need ≥ 10",
              file=sys.stderr)
        return 2
    random.Random(args.seed).shuffle(all_ex)
    n_train = max(5, int(args.train_frac * len(all_ex)))
    trainset, valset = all_ex[:n_train], all_ex[n_train:]

    print(f"Optimizer: {args.name}")
    print(f"Dimension: {args.dimension}  (labels: {len(valid_labels)})")
    print(f"Train: {len(trainset)}  Val: {len(valset)}  Model: {args.model}\n")

    opt = get_optimizer(
        args.name,
        provider=args.provider, model=args.model, api_key=args.api_key,
        budget=args.budget, label_defs=label_defs,
    )
    result = await opt.optimize(initial_prompt, args.dimension, valid_labels, trainset, valset)

    print(f"Initial val acc:  {result.initial_score*100:.1f}%")
    print(f"Final   val acc:  {result.final_score*100:.1f}%  "
          f"(Δ {100*(result.final_score - result.initial_score):+.1f} pp)")
    print(f"Tokens: {result.total_tokens:,}  Cost: ${result.total_cost_usd:.4f}")
    if result.artifact:
        print(f"\nArtifact keys: {list(result.artifact.keys())}")
        if "rule_library" in result.artifact:
            print(f"  Rule library size: {len(result.artifact['rule_library'])}")

    if args.out:
        with open(args.out, "w") as f:
            json.dump({
                "optimizer": result.optimizer_name,
                "dimension": result.dimension,
                "initial_score": result.initial_score,
                "final_score": result.final_score,
                "trajectory": result.trajectory,
                "artifact": result.artifact,
                "optimized_prompt": result.optimized_prompt,
                "total_tokens": result.total_tokens,
                "total_cost_usd": result.total_cost_usd,
            }, f, indent=2)
        print(f"\nReport written to {args.out}")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
