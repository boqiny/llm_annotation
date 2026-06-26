"""Per-user alignment evaluation (command line).

Runs the SAME pipeline as the Improve tab, but headless: for one annotator and
each codebook dimension it does a stratified train/val/test split, scores the
zero-shot starting prompt on the held-out test, runs the ReflectAgent optimizer
on train+val, then scores the optimized prompt on the SAME held-out test. The
test set is never shown to the optimizer, so the agreement numbers are honest.

It reuses the production engine (no reimplementation):
  - app.api.optimizers._stratified_split   (the split)
  - app.engine.prompt_generator.generate_dimension_prompt  (the zero-shot prompt)
  - app.optimizers.get_optimizer('reflect_agent')          (the improvement loop)
  - app.optimizers.evaluate_prompt / app.engine.metrics    (scoring)

Data: annotagent/assets/data/cleaned/<user>_self_disclosure_ground_truth.json
Codebook: app/presets/self_disclosure.json (4 dimensions)

Run from annotagent/backend with the venv python:

  ./.venv/bin/python scripts/run_per_user_eval.py                       # full, Fiona, 4 dims
  ./.venv/bin/python scripts/run_per_user_eval.py --user fiona --budget 8
  ./.venv/bin/python scripts/run_per_user_eval.py --limit 40 --budget 2 # quick smoke run
  ./.venv/bin/python scripts/run_per_user_eval.py --dims "Level of disclosure"

Output is appended/written to exp_result.md (repo root by default) after each
dimension finishes, so partial results survive an interruption.
"""
from __future__ import annotations

import argparse
import asyncio
import csv
import hashlib
import json
import re
import sys
from datetime import datetime
from pathlib import Path

BACKEND = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND))

from app.config import resolve_api_key, settings  # noqa: E402
from app.engine.codebook_parser import parse_codebook  # noqa: E402
from app.engine.metrics import compute_metrics  # noqa: E402
from app.engine.prompt_generator import generate_dimension_prompt  # noqa: E402
from app.optimizers import Example, evaluate_prompt, get_optimizer  # noqa: E402
from app.api.optimizers import _stratified_split  # noqa: E402

PRESETS_DIR = BACKEND / "app" / "presets"
DATA_DIR = BACKEND.parent / "assets" / "data" / "cleaned"
REPO_ROOT = BACKEND.parent.parent


def _norm(value: str) -> str:
    return " ".join(re.sub(r"[^0-9a-zA-Z]+", " ", str(value)).split()).casefold()


def _match_label(value: str, valid_labels: list[str]) -> str | None:
    """Map a raw annotator label to a codebook label.

    Exact (normalized) match wins; otherwise the codebook label whose tokens are
    a subset of the value's tokens, preferring the longest. This bridges the
    data's "Central layer" / "Intermediate level" to the codebook's "Central" /
    "Intermediate" while still resolving the full "No, it's not a confession".
    """
    nv = _norm(value)
    tokens = set(nv.split())
    for label in valid_labels:
        if _norm(label) == nv:
            return label
    # (a) codebook-label tokens subset of the value's (value is more specific,
    #     e.g. "Central layer" -> "Central"): prefer the longest matching label.
    best, best_len = None, -1
    for label in valid_labels:
        lt = _norm(label).split()
        if set(lt).issubset(tokens) and len(lt) > best_len:
            best, best_len = label, len(lt)
    if best:
        return best
    # (b) value's tokens subset of a codebook label (value is shorter, e.g.
    #     "Functional" -> "Functional support"): prefer the closest fit.
    best, best_extra = None, 10 ** 9
    for label in valid_labels:
        lt = set(_norm(label).split())
        if tokens and tokens.issubset(lt) and (len(lt) - len(tokens)) < best_extra:
            best, best_extra = label, len(lt) - len(tokens)
    return best


def _load_items(user: str, codebook: str) -> list[dict]:
    path = DATA_DIR / f"{user}_{codebook}_ground_truth.json"
    if not path.exists():
        raise SystemExit(f"No dataset for user '{user}' / codebook '{codebook}' at {path}")
    raw = json.loads(path.read_text())
    return raw["items"] if isinstance(raw, dict) and "items" in raw else raw


def _gold_for(item: dict, dim_name: str):
    labels = item.get("labels", {})
    if dim_name in labels:
        return labels[dim_name]
    for key, value in labels.items():
        if _norm(key) == _norm(dim_name):
            return value
    return None


def _build_examples(items: list[dict], dim, limit: int) -> list[Example]:
    """Build (sentence, gold-label) examples.

    Multi-label items (gold is a list) are exploded into one example per label,
    mirroring how the production executor handles multi-label dimensions: the same
    sentence appears once per gold label, each scored as a single-label decision.
    """
    valid = [l.name for l in dim.labels]
    examples: list[Example] = []
    for it in items:
        gold = _gold_for(it, dim.name)
        if gold is None:
            continue
        raw_labels = gold if isinstance(gold, list) else [gold]
        seen: set[str] = set()
        for raw in raw_labels:
            canon = _match_label(raw, valid)
            if canon and canon not in seen:
                seen.add(canon)
                examples.append(Example(sentence=it.get("sentence", ""), gold=canon, context=""))
    if limit and len(examples) > limit:
        examples = examples[:limit]
    return examples


async def _run_dimension(dim, items, user, args, seed=None) -> dict | None:
    valid = [l.name for l in dim.labels]
    label_defs = "\n".join(f"- {l.name}: {l.definition}" for l in dim.labels)
    initial_prompt = generate_dimension_prompt(dim)
    examples = _build_examples(items, dim, args.limit)

    if len(examples) < 15:
        print(f"  [skip] {dim.name}: only {len(examples)} usable examples (<15).")
        return None

    if seed is None:
        seed = int(hashlib.sha256(f"{user}|{dim.name}".encode()).hexdigest()[:8], 16)
    train, val, test, per_class = _stratified_split(
        examples, train_frac=args.train_frac, val_frac=args.val_frac, seed=seed,
    )
    # Same leakage guard the production executor asserts.
    assert not ({id(x) for x in train} & {id(x) for x in val})
    assert not ({id(x) for x in val} & {id(x) for x in test})
    assert not ({id(x) for x in train} & {id(x) for x in test})
    if len(train) < 5 or len(val) < 5 or not test:
        print(f"  [skip] {dim.name}: split too small train={len(train)} val={len(val)} test={len(test)}.")
        return None

    print(f"  {dim.name}: n={len(examples)} -> train={len(train)} val={len(val)} test={len(test)} | classes={[ (c, per_class[c]['n']) for c in per_class ]}")

    # Zero-shot baseline on the held-out test.
    zs_acc, zs_preds, zs_tok = await evaluate_prompt(
        initial_prompt, test, valid,
        provider=args.provider, model=args.model, api_key=args.api_key,
        max_concurrency=args.concurrency,
    )
    print(f"    zero-shot test agreement: {zs_acc:.3f}")

    # ReflectAgent optimization on train+val (test stays hidden).
    opt = get_optimizer(
        "reflect_agent",
        provider=args.provider, model=args.model, api_key=args.api_key,
        budget=args.budget, label_defs=label_defs, seed_rules=[],
    )
    result = await opt.optimize(
        initial_prompt=initial_prompt, dimension=dim.name,
        valid_labels=valid, trainset=train, valset=val,
    )

    # Score the optimized prompt on the SAME held-out test.
    opt_acc, opt_preds, opt_tok = await evaluate_prompt(
        result.optimized_prompt, test, valid,
        provider=args.provider, model=args.model, api_key=args.api_key,
        max_concurrency=args.concurrency,
    )
    print(f"    +ReflectAgent test agreement: {opt_acc:.3f}  (delta {opt_acc - zs_acc:+.3f})")

    y_true = [e.gold for e in test]
    zs_m = compute_metrics(y_true, zs_preds)
    opt_m = compute_metrics(y_true, opt_preds)
    n_rules = len((result.artifact or {}).get("rule_library") or [])

    return {
        "dimension": dim.name,
        "n": len(examples),
        "n_train": len(train), "n_val": len(val), "n_test": len(test),
        "classes": {c: per_class[c]["n"] for c in per_class},
        "zs_acc": zs_acc, "opt_acc": opt_acc,
        "zs_macro_f1": zs_m["macro_f1"], "opt_macro_f1": opt_m["macro_f1"],
        "n_rules": n_rules,
        # Per-round validation trajectory (the governor signal) for plotting the
        # improvement curve: each entry has round, val_acc, val_macro_f1, action.
        "val_initial": result.initial_score,
        "val_final": result.final_score,
        "trajectory": result.trajectory or [],
        "tokens": zs_tok + opt_tok + result.total_tokens,
    }


def _user_section(args, user: str, rows: list[dict]) -> list[str]:
    pct = lambda v: f"{v * 100:.1f}"
    lines: list[str] = []
    lines.append(f"## Target: {user}\n")
    lines.append("Agreement = accuracy against this annotator's own held-out labels.\n")
    lines.append("| Dimension | n | train/val/test | Zero-shot agree | +ReflectAgent agree | Delta pp | ZS macro-F1 | +RA macro-F1 | rules |")
    lines.append("|---|---|---|---|---|---|---|---|---|")
    for r in rows:
        delta = (r["opt_acc"] - r["zs_acc"]) * 100
        lines.append(
            f"| {r['dimension']} | {r['n']} | {r['n_train']}/{r['n_val']}/{r['n_test']} | "
            f"{pct(r['zs_acc'])}% | {pct(r['opt_acc'])}% | {delta:+.1f} | "
            f"{r['zs_macro_f1']:.3f} | {r['opt_macro_f1']:.3f} | {r['n_rules']} |"
        )
    if rows:
        avg_zs = sum(r["zs_acc"] for r in rows) / len(rows)
        avg_opt = sum(r["opt_acc"] for r in rows) / len(rows)
        lines.append(
            f"| **mean** | | | **{pct(avg_zs)}%** | **{pct(avg_opt)}%** | "
            f"**{(avg_opt - avg_zs) * 100:+.1f}** | | | |"
        )
    lines.append("")
    lines.append("Class distribution: " + "; ".join(
        f"{r['dimension']} (" + ", ".join(f"{c}: {n}" for c, n in r["classes"].items()) + ")"
        for r in rows
    ) + "\n")
    return lines


def _write_report(args, codebook_name: str, results: dict[str, list[dict]], out: Path) -> None:
    ts = datetime.now().strftime("%Y-%m-%d %H:%M")
    test_frac = 1 - args.train_frac - args.val_frac
    lines: list[str] = []
    lines.append("# Per-user alignment evaluation\n")
    lines.append(
        f"Codebook: {codebook_name} | model: `{args.model}` ({args.provider}) | optimizer: "
        f"`reflect_agent` (budget {args.budget}) | same defaults as the Improve tab.\n"
    )
    lines.append(
        f"Split: train {args.train_frac:.0%} / val {args.val_frac:.0%} / test {test_frac:.0%}, "
        f"stratified by gold class, seed from `(user, dimension)`. Test held out from the "
        f"optimizer and scored once."
        f"{'  Item cap: ' + str(args.limit) + '/dim.' if args.limit else ''}\n"
    )
    lines.append(f"Generated {ts}.\n")
    for user, rows in results.items():
        if rows:
            lines.extend(_user_section(args, user, rows))
    total_tok = sum(r["tokens"] for rows in results.values() for r in rows)
    lines.append(
        f"Run tokens: {total_tok:,}. "
        f"Reproduce: `./.venv/bin/python scripts/run_per_user_eval.py --user {args.user} "
        f"--train-frac {args.train_frac} --val-frac {args.val_frac} --budget {args.budget}` "
        f"(from annotagent/backend).\n"
    )
    out.write_text("\n".join(lines))
    print(f"  wrote {out}")


def _write_trajectories(results: dict[str, list[dict]], out: Path) -> None:
    """Write the per-round validation curve in two forms next to the report:

    - <out>.trajectories.json : full trajectory objects, keyed by user/dimension.
    - <out>.trajectories.csv  : tidy rows (user, dimension, round, val_acc, ...)
      ready to plot directly.
    """
    base = out.with_suffix("")
    payload = {
        user: {r["dimension"]: r.get("trajectory", []) for r in rows}
        for user, rows in results.items()
    }
    base.with_name(base.name + "_trajectories.json").write_text(json.dumps(payload, indent=2))

    csv_path = base.with_name(base.name + "_trajectories.csv")
    with csv_path.open("w", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(["user", "dimension", "round", "val_acc", "val_macro_f1", "action"])
        for user, rows in results.items():
            for r in rows:
                for e in r.get("trajectory", []):
                    w.writerow([
                        user, r["dimension"], e.get("round"),
                        e.get("val_acc"), e.get("val_macro_f1", ""), e.get("action", ""),
                    ])


async def main() -> None:
    ap = argparse.ArgumentParser(description="Per-user alignment eval (CLI).")
    ap.add_argument("--user", default="fiona", help="annotator(s), comma-separated: e.g. fiona,chang")
    ap.add_argument("--codebook", default="self_disclosure", help="preset codebook name (e.g. self_disclosure, ai_behavior)")
    ap.add_argument("--dims", default="", help="comma-separated dimension names (default: all in codebook)")
    ap.add_argument("--budget", type=int, default=8, help="ReflectAgent rounds")
    ap.add_argument("--train-frac", type=float, default=0.5, dest="train_frac")
    ap.add_argument("--val-frac", type=float, default=0.2, dest="val_frac")
    ap.add_argument("--limit", type=int, default=0, help="cap examples per dimension (0 = all)")
    ap.add_argument("--provider", default="openai")
    ap.add_argument("--model", default="gpt-5.4-mini")
    ap.add_argument("--concurrency", type=int, default=8)
    ap.add_argument("--out", default=str(REPO_ROOT / "exp_result.md"))
    args = ap.parse_args()

    args.api_key = resolve_api_key(args.provider)
    if not args.api_key:
        raise SystemExit(
            f"No {args.provider} API key. Set OPENAI_API_KEY in .env or the environment."
        )

    preset_path = PRESETS_DIR / f"{args.codebook}.json"
    if not preset_path.exists():
        raise SystemExit(f"No preset codebook '{args.codebook}' at {preset_path}")
    codebook = parse_codebook(json.loads(preset_path.read_text()))
    wanted = [d.strip() for d in args.dims.split(",") if d.strip()]
    dims = [d for d in codebook.dimensions if not wanted or d.name in wanted or _norm(d.name) in {_norm(w) for w in wanted}]
    if not dims:
        raise SystemExit(f"No matching dimensions. Available: {[d.name for d in codebook.dimensions]}")

    users = [u.strip() for u in args.user.split(",") if u.strip()]
    out = Path(args.out)
    print(f"Per-user alignment eval — users={users}, dims={[d.name for d in dims]}, "
          f"model={args.model}, budget={args.budget}, split={args.train_frac}/{args.val_frac}/"
          f"{1 - args.train_frac - args.val_frac:.2f}\n")

    results: dict[str, list[dict]] = {u: [] for u in users}
    for user in users:
        print(f"=== {user} ===")
        items = _load_items(user, args.codebook)
        for dim in dims:
            row = await _run_dimension(dim, items, user, args)
            if row:
                results[user].append(row)
                _write_report(args, codebook.name, results, out)  # incremental save
                _write_trajectories(results, out)                  # per-round val curve

    if not any(results.values()):
        raise SystemExit("No dimensions produced results.")
    print("\nDone.")


if __name__ == "__main__":
    asyncio.run(main())
