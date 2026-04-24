"""Run a preset codebook against a labeled JSON dataset and print metrics.

Usage:
    python -m scripts.eval_preset \
        --preset sentiment \
        --data ../../seed/sentiment_demo.json \
        --provider openai --model gpt-4o-mini --api-key $OPENAI_API_KEY

The dataset must be a JSON array where each item has `content` and `gold_labels`.
Intended for the paper's Section 4.2 generalization evaluation and for quick
sanity checks when adding a new preset.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from pathlib import Path

# Allow running as `python -m scripts.eval_preset` from the backend dir.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.agents.annotation import annotate_batch
from app.agents.decomposition import decompose_codebook
from app.engine.codebook_parser import parse_codebook
from app.engine.metrics import compute_metrics, confusion_matrix


def _load_json(path: str) -> list[dict]:
    with open(path) as f:
        data = json.load(f)
    if not isinstance(data, list):
        raise ValueError(f"Expected a JSON list, got {type(data).__name__}")
    return data


async def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--preset", required=True, help="Preset codebook name (file stem in app/presets).")
    parser.add_argument("--data", required=True, help="Path to labeled JSON dataset (content + gold_labels).")
    parser.add_argument("--provider", default="openai")
    parser.add_argument("--model", default="gpt-4o-mini")
    parser.add_argument("--api-key", default=os.getenv("OPENAI_API_KEY", ""))
    parser.add_argument("--max-items", type=int, default=0, help="Limit items (0 = all).")
    parser.add_argument("--max-concurrency", type=int, default=5)
    parser.add_argument("--out", default="", help="Optional path to dump full report JSON.")
    args = parser.parse_args()

    if not args.api_key:
        print("error: no API key (set --api-key or OPENAI_API_KEY)", file=sys.stderr)
        return 2

    preset_path = Path(__file__).resolve().parent.parent / "app" / "presets" / f"{args.preset}.json"
    if not preset_path.exists():
        print(f"error: preset not found at {preset_path}", file=sys.stderr)
        return 2

    with open(preset_path) as f:
        codebook = parse_codebook(json.load(f))

    items = _load_json(args.data)
    if args.max_items > 0:
        items = items[: args.max_items]

    steps = await decompose_codebook(
        codebook, provider=args.provider, model=args.model, api_key=args.api_key
    )
    codebook_dims = {d.name: [l.name for l in d.labels] for d in codebook.dimensions}

    print(f"Running {args.preset} on {len(items)} items via {args.provider}/{args.model}")
    print(f"Pipeline steps: {[s['name'] for s in steps]}")

    results = await annotate_batch(
        items=[{"content": it.get("content", ""), "context": it.get("context", "")} for it in items],
        steps=steps,
        codebook_dims=codebook_dims,
        provider=args.provider, model=args.model, api_key=args.api_key,
        max_concurrency=args.max_concurrency,
    )

    total_cost = sum(r.cost_usd for r in results)
    total_tokens = sum(r.tokens_used for r in results)

    report: dict = {
        "preset": args.preset,
        "n": len(items),
        "model": args.model,
        "total_tokens": total_tokens,
        "total_cost_usd": round(total_cost, 6),
        "per_dimension": {},
    }

    print(f"\nResults (n={len(items)}):")
    print(f"  Total tokens: {total_tokens:,}  |  Est. cost: ${total_cost:.4f}")

    for dim in codebook.dimensions:
        y_true = [it.get("gold_labels", {}).get(dim.name, "") for it in items]
        y_pred = [r.labels.get(dim.name, "") for r in results]
        pairs = [(t, p) for t, p in zip(y_true, y_pred) if t]
        if not pairs:
            continue
        yt = [p[0] for p in pairs]
        yp = [p[1] for p in pairs]
        m = compute_metrics(yt, yp)
        cm = confusion_matrix(yt, yp)
        report["per_dimension"][dim.name] = {**m, "confusion_matrix": cm}
        print(
            f"  [{dim.name}] acc={m['accuracy']*100:.1f}%  "
            f"macro_f1={m['macro_f1']*100:.1f}%  n={m['n']}"
        )

    if args.out:
        with open(args.out, "w") as f:
            json.dump(report, f, indent=2)
        print(f"\nFull report written to {args.out}")

    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
