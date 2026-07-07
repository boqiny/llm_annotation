"""Run any baseline optimizer (gepa|mipro|opro) on the SAME splits as ReflectAgent.

Identical split/eval pipeline to run_gepa_baseline.py (production _stratified_split,
seed = SHA-256 of user|dim|k), parameterized by --optimizer. Both task and
optimizer LM = the same model. Includes an inline leakage audit of the optimized
prompt against train/val/test. Uses EXPERIMENTAL_OPENAI_API_KEY from repo .env.

  .venv/bin/python scripts/run_optimizer_baseline.py --optimizer mipro --dim "Disclosure as confession" --seed-index 0
"""
from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import os
import sys
import time
from datetime import datetime
from pathlib import Path

BACKEND = Path(__file__).resolve().parent.parent
REPO = BACKEND.parents[1]
sys.path.insert(0, str(BACKEND))
sys.path.insert(0, str(BACKEND / "scripts"))

from app.engine.codebook_parser import parse_codebook            # noqa: E402
from app.engine.metrics import compute_metrics                   # noqa: E402
from app.engine.prompt_generator import generate_dimension_prompt  # noqa: E402
from app.optimizers import evaluate_prompt, get_optimizer        # noqa: E402
from app.api.optimizers import _stratified_split                 # noqa: E402
from run_per_user_eval import _load_items, _build_examples, PRESETS_DIR  # noqa: E402


def _load_key(name: str = "EXPERIMENTAL_OPENAI_API_KEY") -> str:
    for env in (REPO / ".env", BACKEND.parent / ".env"):
        if env.exists():
            for line in env.read_text().splitlines():
                if line.strip().startswith(f"{name}="):
                    v = line.split("=", 1)[1].strip().strip('"').strip("'")
                    if v:
                        return v
    return ""


def _leak_audit(prompt: str, train, val, test) -> dict:
    p = (prompt or "").lower()
    def c(split):
        return sum(1 for e in split
                   if len((e.sentence or "").strip()) >= 25 and (e.sentence or "").strip().lower() in p)
    return {"train_memorized": c(train), "val_leak": c(val), "test_leak": c(test),
            "clean": c(val) == 0 and c(test) == 0}


async def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--optimizer", required=True, choices=["gepa", "mipro", "opro"])
    ap.add_argument("--user", default="fiona")
    ap.add_argument("--codebook", default="self_disclosure")
    ap.add_argument("--dim", required=True)
    ap.add_argument("--seed-index", type=int, default=0, dest="seed_index")
    ap.add_argument("--train-frac", type=float, default=0.15, dest="train_frac")
    ap.add_argument("--val-frac", type=float, default=0.42, dest="val_frac")
    ap.add_argument("--model", default="gpt-5.4-mini")
    ap.add_argument("--provider", default="openai")
    ap.add_argument("--auto", default="light")
    ap.add_argument("--threads", type=int, default=16)
    ap.add_argument("--opro-budget", type=int, default=8, dest="opro_budget")
    ap.add_argument("--out", default="")
    args = ap.parse_args()

    key = _load_key()
    if not key:
        raise SystemExit("No EXPERIMENTAL_OPENAI_API_KEY in repo .env")
    os.environ["OPENAI_API_KEY"] = key

    cb = parse_codebook(json.loads((PRESETS_DIR / f"{args.codebook}.json").read_text()))
    dim = next(d for d in cb.dimensions if d.name == args.dim)
    valid = [l.name for l in dim.labels]
    label_defs = "\n".join(f"- {l.name}: {l.definition}" for l in dim.labels)
    initial_prompt = generate_dimension_prompt(dim)

    items = _load_items(args.user, args.codebook)
    examples = _build_examples(items, dim, 0)
    seed = int(hashlib.sha256(f"{args.user}|{dim.name}|{args.seed_index}".encode()).hexdigest()[:8], 16)
    train, val, test, per_class = _stratified_split(
        examples, train_frac=args.train_frac, val_frac=args.val_frac, seed=seed)
    assert not ({id(x) for x in train} & {id(x) for x in val})
    assert not ({id(x) for x in val} & {id(x) for x in test})
    assert not ({id(x) for x in train} & {id(x) for x in test})

    print(f"[{args.optimizer}] dim={dim.name!r} seed_index={args.seed_index} "
          f"n={len(examples)} train={len(train)} val={len(val)} test={len(test)} | model={args.model}")

    t0 = time.perf_counter()
    zs_acc, zs_preds, zs_tok = await evaluate_prompt(
        initial_prompt, test, valid, provider=args.provider, model=args.model,
        api_key=key, max_concurrency=args.threads)
    print(f"[{args.optimizer}] zero-shot test: {zs_acc*100:.1f}%")

    budget = args.opro_budget if args.optimizer == "opro" else 0
    opt = get_optimizer(
        args.optimizer, provider=args.provider, model=args.model, api_key=key,
        budget=budget, auto_budget=args.auto, num_threads=args.threads,
        label_defs=label_defs, seed_rules=[])
    t1 = time.perf_counter()
    result = await opt.optimize(
        initial_prompt=initial_prompt, dimension=dim.name,
        valid_labels=valid, trainset=train, valset=val)
    t_opt = time.perf_counter() - t1

    t2 = time.perf_counter()
    opt_acc, opt_preds, opt_tok = await evaluate_prompt(
        result.optimized_prompt, test, valid, provider=args.provider, model=args.model,
        api_key=key, max_concurrency=args.threads)
    total_wall = time.perf_counter() - t0

    y = [e.gold for e in test]
    zs_m = compute_metrics(y, zs_preds); opt_m = compute_metrics(y, opt_preds)
    audit = _leak_audit(result.optimized_prompt, train, val, test)

    out = {
        "optimizer": args.optimizer, "user": args.user, "dimension": dim.name,
        "model_task": args.model, "model_optimizer": args.model,
        "auto_budget": args.auto if args.optimizer in ("gepa", "mipro") else None,
        "opro_budget": args.opro_budget if args.optimizer == "opro" else None,
        "seed_index": args.seed_index, "split_seed": seed,
        "n": len(examples), "n_train": len(train), "n_val": len(val), "n_test": len(test),
        "zs_test_acc": round(zs_acc, 4), "opt_test_acc": round(opt_acc, 4),
        "delta_pp": round((opt_acc - zs_acc) * 100, 2),
        "zs_macro_f1": round(zs_m["macro_f1"], 4), "opt_macro_f1": round(opt_m["macro_f1"], 4),
        "val_initial": round(result.initial_score, 4), "val_final": round(result.final_score, 4),
        "prompt_changed": result.optimized_prompt.strip() != initial_prompt.strip(),
        "prompt_words": len(result.optimized_prompt.split()),
        "n_demos": (result.artifact or {}).get("n_demos_bootstrapped"),
        "leak_audit": audit,
        "harness_tokens": zs_tok + opt_tok,
        "optimizer_tokens": result.total_tokens,
        "time_sec": {"optimize": round(t_opt, 1), "total": round(total_wall, 1)},
        "trajectory": result.trajectory,
        "optimized_prompt": result.optimized_prompt,
        "generated": datetime.now().strftime("%Y-%m-%d %H:%M"),
    }
    slug = dim.name.replace(" ", "_")
    out_path = args.out or str(BACKEND / "scripts" / f"opt_{args.optimizer}_{slug}.json")
    Path(out_path).write_text(json.dumps(out, indent=2))
    summary = {k: out[k] for k in ("optimizer", "dimension", "zs_test_acc", "opt_test_acc",
              "delta_pp", "zs_macro_f1", "opt_macro_f1", "prompt_changed", "n_demos",
              "leak_audit", "time_sec")}
    print(json.dumps(summary, indent=2))
    print(f"[{args.optimizer}] wrote {out_path}")


if __name__ == "__main__":
    asyncio.run(main())
