"""Multi-seed self-disclosure eval: re-run each dimension with K different split
seeds and report mean +/- std, so the per-coder agreement gains are not read as
single-split noise.

Reuses run_per_user_eval._run_dimension (same pipeline as the headline numbers),
varying only the stratified-split seed (SHA-256 of user|dim|seed_index).

Run (from annotagent/backend):
  ./.venv/bin/python scripts/run_multiseed.py --user fiona --seeds 3 --budget 5
"""
from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import sys
from datetime import datetime
from pathlib import Path

BACKEND = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from app.config import resolve_api_key  # noqa: E402
from app.engine.codebook_parser import parse_codebook  # noqa: E402
from run_per_user_eval import _run_dimension, _load_items, PRESETS_DIR  # noqa: E402

REPO_ROOT = BACKEND.parent.parent


def _ms(xs):
    m = sum(xs) / len(xs)
    sd = (sum((v - m) ** 2 for v in xs) / len(xs)) ** 0.5
    return m, sd


async def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--user", default="fiona")
    ap.add_argument("--codebook", default="self_disclosure")
    ap.add_argument("--seeds", type=int, default=3)
    ap.add_argument("--dims", default="")
    ap.add_argument("--budget", type=int, default=5)
    ap.add_argument("--train-frac", type=float, default=0.15, dest="train_frac")
    ap.add_argument("--val-frac", type=float, default=0.42, dest="val_frac")
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--provider", default="openai")
    ap.add_argument("--model", default="gpt-5.4-mini")
    ap.add_argument("--concurrency", type=int, default=8)
    ap.add_argument("--out", default=str(REPO_ROOT / "exp_result_multiseed.md"))
    args = ap.parse_args()
    args.api_key = resolve_api_key(args.provider)
    if not args.api_key:
        raise SystemExit("No API key.")

    cb = parse_codebook(json.loads((PRESETS_DIR / f"{args.codebook}.json").read_text()))
    wanted = [d.strip() for d in args.dims.split(",") if d.strip()]
    dims = [d for d in cb.dimensions if not wanted or d.name in wanted]
    items = _load_items(args.user, args.codebook)
    print(f"Multi-seed eval: user={args.user}, {len(dims)} dims, {args.seeds} seeds, budget {args.budget}\n")

    results = {}
    for dim in dims:
        print(f"=== {dim.name} ===")
        zs, opt, trajs = [], [], []
        for k in range(args.seeds):
            seed = int(hashlib.sha256(f"{args.user}|{dim.name}|{k}".encode()).hexdigest()[:8], 16)
            print(f"  seed {k+1}/{args.seeds}:")
            row = await _run_dimension(dim, items, args.user, args, seed=seed)
            if row:
                zs.append(row["zs_acc"]); opt.append(row["opt_acc"]); trajs.append(row.get("trajectory", []))
        if zs:
            results[dim.name] = {"zs": zs, "opt": opt, "trajectories": trajs}
            zm, zsd = _ms(zs); om, osd = _ms(opt)
            print(f"  -> zero-shot {zm*100:.1f}+/-{zsd*100:.1f}  +RA {om*100:.1f}+/-{osd*100:.1f}  "
                  f"delta {(om-zm)*100:+.1f}\n")
            _write(args, results)  # incremental
    print("Done.")


def _write(args, results):
    lines = [f"# Multi-seed self-disclosure ({args.user})\n",
             f"Model `{args.model}`, budget {args.budget}, split {args.train_frac}/{args.val_frac}, "
             f"{args.seeds} seeds (split seed = SHA-256 of user|dim|k). "
             f"Generated {datetime.now().strftime('%Y-%m-%d %H:%M')}.\n",
             "| Dimension | Zero-shot (mean+/-std) | +ReflectAgent (mean+/-std) | Delta pp |",
             "|---|---|---|---|"]
    z_all, o_all = [], []
    for dim, r in results.items():
        zm, zsd = _ms(r["zs"]); om, osd = _ms(r["opt"])
        z_all.append(zm); o_all.append(om)
        lines.append(f"| {dim} | {zm*100:.1f} +/- {zsd*100:.1f} | {om*100:.1f} +/- {osd*100:.1f} | {(om-zm)*100:+.1f} |")
    if z_all:
        lines.append(f"| **mean** | **{sum(z_all)/len(z_all)*100:.1f}** | **{sum(o_all)/len(o_all)*100:.1f}** | "
                     f"**{(sum(o_all)-sum(z_all))/len(z_all)*100:+.1f}** |")
    lines.append(f"\nRaw per-seed accuracies: `{json.dumps({d: {'zs': r['zs'], 'opt': r['opt']} for d, r in results.items()})}`")
    Path(args.out).write_text("\n".join(lines))
    base = str(Path(args.out).with_suffix(""))
    Path(base + "_trajectories.json").write_text(
        json.dumps({d: r.get("trajectories", []) for d, r in results.items()}, indent=2))
    print(f"  wrote {args.out} (+ {base}_trajectories.json)")


if __name__ == "__main__":
    asyncio.run(main())
