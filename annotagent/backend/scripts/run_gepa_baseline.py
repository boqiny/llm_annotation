"""GEPA baseline on the SAME splits as ReflectAgent (per-coder self-disclosure).

Reuses the production pipeline pieces so the train/val/test split is byte-for-byte
identical to run_per_user_eval / run_multiseed:
  - run_per_user_eval._load_items / _build_examples
  - app.api.optimizers._stratified_split   (seed = SHA-256 of user|dim|k)
  - app.engine.prompt_generator.generate_dimension_prompt   (zero-shot prompt)
  - app.optimizers.get_optimizer('gepa')                    (the GEPA loop)
  - app.optimizers.evaluate_prompt + app.engine.metrics     (held-out test scoring)

Both task LM and GEPA reflection LM = the same model (default gpt-5.4-mini).
Uses EXPERIMENTAL_OPENAI_API_KEY from the repo-level .env.

Run from annotagent/backend:
  .venv/bin/python scripts/run_gepa_baseline.py --dim "Level of disclosure" --seed-index 0
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


def _dspy_tokens() -> int:
    """Best-effort: sum prompt+completion tokens across all dspy LM histories."""
    try:
        import dspy
        total = 0
        for obj in list(globals().values()):
            pass
        # walk dspy's global LM + any LM with history
        lms = []
        cur = getattr(dspy.settings, "lm", None)
        if cur is not None:
            lms.append(cur)
        for lm in lms:
            for h in getattr(lm, "history", []) or []:
                u = h.get("usage") or {}
                total += int(u.get("total_tokens") or 0)
        return total
    except Exception:
        return 0


async def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--user", default="fiona")
    ap.add_argument("--codebook", default="self_disclosure")
    ap.add_argument("--dim", default="Level of disclosure")
    ap.add_argument("--seed-index", type=int, default=0, dest="seed_index")
    ap.add_argument("--train-frac", type=float, default=0.15, dest="train_frac")
    ap.add_argument("--val-frac", type=float, default=0.42, dest="val_frac")
    ap.add_argument("--model", default="gpt-5.4-mini")
    ap.add_argument("--provider", default="openai")
    ap.add_argument("--auto", default="light")
    ap.add_argument("--threads", type=int, default=16)
    ap.add_argument("--out", default=str(BACKEND / "scripts" / "gepa_baseline_result.json"))
    args = ap.parse_args()

    key = _load_key()
    if not key:
        raise SystemExit("No EXPERIMENTAL_OPENAI_API_KEY in repo .env")
    os.environ["OPENAI_API_KEY"] = key  # so dspy/litellm pick up the experimental key

    cb = parse_codebook(json.loads((PRESETS_DIR / f"{args.codebook}.json").read_text()))
    dim = next(d for d in cb.dimensions if d.name == args.dim)
    valid = [l.name for l in dim.labels]
    label_defs = "\n".join(f"- {l.name}: {l.definition}" for l in dim.labels)
    initial_prompt = generate_dimension_prompt(dim)

    items = _load_items(args.user, args.codebook)
    examples = _build_examples(items, dim, 0)
    seed = int(hashlib.sha256(f"{args.user}|{dim.name}|{args.seed_index}".encode()).hexdigest()[:8], 16)
    train, val, test, per_class = _stratified_split(
        examples, train_frac=args.train_frac, val_frac=args.val_frac, seed=seed,
    )
    assert not ({id(x) for x in train} & {id(x) for x in val})
    assert not ({id(x) for x in val} & {id(x) for x in test})
    assert not ({id(x) for x in train} & {id(x) for x in test})

    print(f"[gepa] user={args.user} dim={dim.name!r} seed_index={args.seed_index} "
          f"(seed={seed}) | n={len(examples)} train={len(train)} val={len(val)} test={len(test)}")
    print(f"[gepa] model={args.model} both task+reflection | auto={args.auto} threads={args.threads}")

    t0 = time.perf_counter()
    # Zero-shot baseline on held-out test (same prompt ReflectAgent starts from).
    zs_acc, zs_preds, zs_tok = await evaluate_prompt(
        initial_prompt, test, valid,
        provider=args.provider, model=args.model, api_key=key, max_concurrency=args.threads,
    )
    t_zs = time.perf_counter() - t0
    print(f"[gepa] zero-shot test agreement: {zs_acc*100:.1f}%  ({t_zs:.0f}s)")

    opt = get_optimizer(
        "gepa", provider=args.provider, model=args.model, api_key=key,
        auto_budget=args.auto, num_threads=args.threads,
        budget=0, label_defs=label_defs, seed_rules=[],
    )
    t1 = time.perf_counter()
    result = await opt.optimize(
        initial_prompt=initial_prompt, dimension=dim.name,
        valid_labels=valid, trainset=train, valset=val,
    )
    t_gepa = time.perf_counter() - t1
    print(f"[gepa] GEPA optimize wall-clock: {t_gepa:.0f}s")

    t2 = time.perf_counter()
    opt_acc, opt_preds, opt_tok = await evaluate_prompt(
        result.optimized_prompt, test, valid,
        provider=args.provider, model=args.model, api_key=key, max_concurrency=args.threads,
    )
    t_test = time.perf_counter() - t2
    total_wall = time.perf_counter() - t0

    y = [e.gold for e in test]
    zs_m = compute_metrics(y, zs_preds)
    opt_m = compute_metrics(y, opt_preds)
    prompt_changed = result.optimized_prompt.strip() != initial_prompt.strip()

    out = {
        "optimizer": "gepa",
        "user": args.user,
        "dimension": dim.name,
        "model_task": args.model,
        "model_reflection": args.model,
        "auto_budget": args.auto,
        "threads": args.threads,
        "seed_index": args.seed_index,
        "split_seed": seed,
        "n": len(examples), "n_train": len(train), "n_val": len(val), "n_test": len(test),
        "classes": {c: per_class[c]["n"] for c in per_class},
        "zs_test_acc": round(zs_acc, 4),
        "gepa_test_acc": round(opt_acc, 4),
        "delta_pp": round((opt_acc - zs_acc) * 100, 2),
        "zs_macro_f1": round(zs_m["macro_f1"], 4),
        "gepa_macro_f1": round(opt_m["macro_f1"], 4),
        "gepa_val_initial": round(result.initial_score, 4),
        "gepa_val_final": round(result.final_score, 4),
        "prompt_changed": prompt_changed,
        "harness_tokens": zs_tok + opt_tok,
        "gepa_internal_tokens_best_effort": _dspy_tokens(),
        "time_sec": {
            "zero_shot_eval": round(t_zs, 1),
            "gepa_optimize": round(t_gepa, 1),
            "test_eval": round(t_test, 1),
            "total": round(total_wall, 1),
        },
        "trajectory": result.trajectory,
        "optimized_prompt": result.optimized_prompt,
        "generated": datetime.now().strftime("%Y-%m-%d %H:%M"),
    }
    Path(args.out).write_text(json.dumps(out, indent=2))

    print("\n===== GEPA BASELINE (Level of disclosure, Fiona, seed 0) =====")
    summ = {k: out[k] for k in (
        "zs_test_acc", "gepa_test_acc", "delta_pp", "zs_macro_f1", "gepa_macro_f1",
        "gepa_val_initial", "gepa_val_final", "prompt_changed", "harness_tokens",
        "gepa_internal_tokens_best_effort", "time_sec")}
    print(json.dumps(summ, indent=2))
    print(f"[gepa] wrote {args.out}")


if __name__ == "__main__":
    asyncio.run(main())
