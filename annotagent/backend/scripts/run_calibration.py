"""Calibration-profile specificity test (the positive personalization result).

Codebook clarification (rules) is generic; coders differ mainly in BASE RATE.
So we separate the two: the annotator returns a continuous score per item, and
we learn ONE decision threshold per target coder on a calibration split. A coder
who labels Yes rarely (Fiona, ~14%) gets a high threshold; a coder who labels Yes
often (Chang, ~53%) gets a low one. The "Calibration Profile" = shared rules +
per-coder threshold.

Because the score is shared across coders, the cross-target 2x2 falls out of
thresholding the SAME scores two ways, so it is one scoring pass plus threshold
math, repeated over several seeds to beat noise.

For a binary dimension (Yes/No). Run (from annotagent/backend):
  ./.venv/bin/python scripts/run_calibration.py --dim "Disclosure as confession" --seeds 5
"""
from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import re
import sys
from datetime import datetime
from pathlib import Path

BACKEND = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from app.config import resolve_api_key  # noqa: E402
from app.engine.codebook_parser import parse_codebook  # noqa: E402
from app.engine.llm_client import call_llm  # noqa: E402
from run_per_user_eval import _match_label, _load_items, _gold_for, PRESETS_DIR  # noqa: E402

REPO_ROOT = BACKEND.parent.parent


def _seed(*p):
    return int(hashlib.sha256("|".join(map(str, p)).encode()).hexdigest()[:8], 16)


def _yes_map(items, dim, valid, yes_label):
    out = {}
    for it in items:
        g = _gold_for(it, dim.name)
        if g is None:
            continue
        raw = g if isinstance(g, list) else [g]
        for r in raw:
            m = _match_label(r, valid)
            if m:
                out[it.get("sentence", "")] = 1 if m == yes_label else 0
                break
    return out


def _score_prompt(dim, yes_label):
    defs = "\n".join(f"- {l.name}: {l.definition}" for l in dim.labels)
    return (
        f'You rate the dimension "{dim.name}" for a self-disclosure codebook.\n{defs}\n\n'
        f'Given a sentence, output ONLY a JSON object {{"score": p}} where p in [0,1] is how '
        f'strongly the sentence is "{yes_label}" (1 = clearly yes, 0 = clearly no). No other text.'
    )


async def _score(prompt, sentences, args):
    sem = asyncio.Semaphore(args.concurrency)

    async def one(s):
        async with sem:
            try:
                resp = await call_llm(
                    messages=[{"role": "system", "content": prompt},
                              {"role": "user", "content": f"Sentence: {s}"}],
                    provider=args.provider, model=args.model, api_key=args.api_key, max_tokens=40,
                )
                m = re.search(r"[01](?:\.\d+)?", resp.text)
                return s, (float(m.group()) if m else 0.5)
            except Exception:
                return s, 0.5

    return dict(await asyncio.gather(*(one(s) for s in sentences)))


def _best_threshold(scores, yes, sentences):
    """Grid-search the threshold that maximizes accuracy vs `yes` on `sentences`."""
    best_t, best_acc = 0.5, -1.0
    for t in [i / 20 for i in range(1, 20)]:
        acc = sum(1 for s in sentences if (1 if scores[s] >= t else 0) == yes[s]) / len(sentences)
        if acc > best_acc:
            best_t, best_acc = t, acc
    return best_t


def _acc(scores, t, yes, sentences):
    return sum(1 for s in sentences if (1 if scores[s] >= t else 0) == yes[s]) / len(sentences)


async def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dim", default="Disclosure as confession")
    ap.add_argument("--codebook", default="self_disclosure")
    ap.add_argument("--seeds", type=int, default=5)
    ap.add_argument("--provider", default="openai")
    ap.add_argument("--model", default="gpt-5.4-mini")
    ap.add_argument("--concurrency", type=int, default=8)
    ap.add_argument("--out", default=str(REPO_ROOT / "exp_result_calibration.json"))
    args = ap.parse_args()
    args.api_key = resolve_api_key(args.provider)
    if not args.api_key:
        raise SystemExit("No API key.")

    cb = parse_codebook(json.loads((PRESETS_DIR / f"{args.codebook}.json").read_text()))
    dim = next(d for d in cb.dimensions if d.name == args.dim)
    valid = [l.name for l in dim.labels]
    yes_label = next((l for l in valid if "yes" in l.lower()), valid[0])
    if len(valid) != 2:
        raise SystemExit(f"Calibration test is for binary dims; '{dim.name}' has {len(valid)} labels.")

    fiona = _yes_map(_load_items("fiona", args.codebook), dim, valid, yes_label)
    chang = _yes_map(_load_items("chang", args.codebook), dim, valid, yes_label)
    shared = sorted(set(fiona) & set(chang))
    fr, cr = sum(fiona[s] for s in shared) / len(shared), sum(chang[s] for s in shared) / len(shared)
    print(f"{args.dim}: shared {len(shared)} | Fiona Yes-rate {fr*100:.0f}%, Chang Yes-rate {cr*100:.0f}%")

    # One scoring pass over all shared items (coder-agnostic continuous score).
    scores = await _score(_score_prompt(dim, yes_label), shared, args)

    # Multi-seed: split shared into calibration / test; learn per-coder threshold
    # on calibration, evaluate the 2x2 on held-out test.
    import random
    rows = {"diag_fiona": [], "diag_chang": [], "off_FF_minus_CF": [], "off_CC_minus_FC": [],
            "tF": [], "tC": [], "uncal_fiona": [], "uncal_chang": []}
    last = {}
    for k in range(args.seeds):
        sh = list(shared); random.Random(_seed(args.dim, k)).shuffle(sh)
        cut = len(sh) // 2
        calib, test = sh[:cut], sh[cut:]
        tF = _best_threshold(scores, fiona, calib)
        tC = _best_threshold(scores, chang, calib)
        aFF, aFC = _acc(scores, tF, fiona, test), _acc(scores, tF, chang, test)
        aCF, aCC = _acc(scores, tC, fiona, test), _acc(scores, tC, chang, test)
        rows["diag_fiona"].append(aFF - aCF)   # Fiona's profile beats Chang's on Fiona
        rows["diag_chang"].append(aCC - aFC)   # Chang's profile beats Fiona's on Chang
        rows["tF"].append(tF); rows["tC"].append(tC)
        rows["uncal_fiona"].append(_acc(scores, 0.5, fiona, test))
        rows["uncal_chang"].append(_acc(scores, 0.5, chang, test))
        last = {"aFF": aFF, "aFC": aFC, "aCF": aCF, "aCC": aCC, "test_n": len(test)}

    def ms(x):
        m = sum(x) / len(x)
        sd = (sum((v - m) ** 2 for v in x) / len(x)) ** 0.5
        return m, sd

    dF_m, dF_s = ms(rows["diag_fiona"]); dC_m, dC_s = ms(rows["diag_chang"])
    tF_m, _ = ms(rows["tF"]); tC_m, _ = ms(rows["tC"])
    print(f"\nLearned thresholds (mean): Fiona {tF_m:.2f}, Chang {tC_m:.2f}  (higher = more conservative Yes)")
    print(f"Last-seed 2x2 (acc %, test n={last['test_n']}):")
    print(f"                 target=Fiona   target=Chang")
    print(f"  thr=Fiona        {last['aFF']*100:5.1f}        {last['aFC']*100:5.1f}")
    print(f"  thr=Chang        {last['aCF']*100:5.1f}        {last['aCC']*100:5.1f}")
    print(f"\nSpecificity (own minus other), mean +/- std over {args.seeds} seeds:")
    print(f"  Fiona: {dF_m*100:+.1f} +/- {dF_s*100:.1f} pp")
    print(f"  Chang: {dC_m*100:+.1f} +/- {dC_s*100:.1f} pp")

    out = {
        "generated": datetime.now().strftime("%Y-%m-%d %H:%M"),
        "dim": dim.name, "model": args.model, "seeds": args.seeds, "shared_n": len(shared),
        "fiona_yes_rate": fr, "chang_yes_rate": cr,
        "threshold_mean": {"fiona": tF_m, "chang": tC_m},
        "specificity_pp": {"fiona_mean": dF_m * 100, "fiona_std": dF_s * 100,
                           "chang_mean": dC_m * 100, "chang_std": dC_s * 100},
        "per_seed": rows, "last_matrix": last,
    }
    Path(args.out).write_text(json.dumps(out, indent=2))
    print(f"\nSaved {args.out}")


if __name__ == "__main__":
    asyncio.run(main())
