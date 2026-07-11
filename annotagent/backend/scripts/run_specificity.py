"""Cross-target specificity experiment (the personalization proof).

On the items BOTH annotators labeled, hold out a shared test set. Tune one prompt
on Fiona's labels and one on Chang's labels (each on their own non-test items),
then score BOTH prompts against BOTH annotators' labels on the SAME shared test
items. If personalization is real, the diagonal beats the off-diagonal: the
prompt tuned for a coder agrees with that coder more than the other coder's
prompt does.

Reuses the production engine via run_per_user_eval (split, prompts, optimizer,
scoring). Uses a stable sha256 seed (Python hash() is not stable across runs).

Run (from annotagent/backend):
  ./.venv/bin/python scripts/run_specificity.py --dim "Disclosure as confession" --budget 5
"""
from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import random
import sys
from datetime import datetime
from pathlib import Path

BACKEND = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from app.config import resolve_api_key  # noqa: E402
from app.engine.codebook_parser import parse_codebook  # noqa: E402
from app.engine.prompt_generator import generate_dimension_prompt  # noqa: E402
from app.optimizers import Example, evaluate_prompt, get_optimizer  # noqa: E402
from run_per_user_eval import _match_label, _norm, _load_items, _gold_for, PRESETS_DIR  # noqa: E402

REPO_ROOT = BACKEND.parent.parent


def _seed(*parts) -> int:
    """Stable seed across processes (unlike Python hash())."""
    h = hashlib.sha256("|".join(map(str, parts)).encode()).hexdigest()
    return int(h[:8], 16)


def _labels_for(items, dim, valid):
    """sentence -> single canonical label (first matched) for this dimension."""
    out = {}
    for it in items:
        g = _gold_for(it, dim.name)
        if g is None:
            continue
        raw = g if isinstance(g, list) else [g]
        for r in raw:
            m = _match_label(r, valid)
            if m:
                out[it.get("sentence", "")] = m
                break
    return out


def _split(sentences, seed, frac_train=0.7):
    s = list(sentences)
    random.Random(seed).shuffle(s)
    k = int(len(s) * frac_train)
    return s[:k], s[k:]


async def _tune(label_map, train_sentences, dim, valid, args):
    """Optimize a prompt on one coder's train items (stratified train/val)."""
    exs = [Example(sentence=s, gold=label_map[s], context="") for s in train_sentences]
    if args.limit:
        exs = exs[: args.limit]
    tv_parts = ["tv", dim.name] + ([args.seed] if args.seed else [])
    tr, va = _split([i for i in range(len(exs))], _seed(*tv_parts), 0.7)
    trainset = [exs[i] for i in tr]
    valset = [exs[i] for i in va]
    opt = get_optimizer(
        "reflect_agent", provider=args.provider, model=args.model, api_key=args.api_key,
        budget=args.budget, label_defs="\n".join(f"- {l.name}: {l.definition}" for l in dim.labels),
        seed_rules=[],
    )
    res = await opt.optimize(initial_prompt=generate_dimension_prompt(dim), dimension=dim.name,
                             valid_labels=valid, trainset=trainset, valset=valset)
    return res.optimized_prompt, list((res.artifact or {}).get("rule_library") or [])


async def _predict(prompt, test_sentences, valid, args):
    """ONE prediction vector per prompt on the shared test items. Both cells in
    a matrix row score this same vector, so row-wise comparisons are paired and
    never mix two stochastic prediction runs of the same prompt."""
    exs = [Example(sentence=s, gold="", context="") for s in test_sentences]
    _, preds, *_ = await evaluate_prompt(prompt, exs, valid, provider=args.provider,
                                         model=args.model, api_key=args.api_key,
                                         max_concurrency=args.concurrency)
    return preds


def _score(preds, test_sentences, label_map):
    pairs = [(p, label_map[s]) for p, s in zip(preds, test_sentences) if s in label_map]
    if not pairs:
        return 0.0, 0
    return sum(1 for p, g in pairs if p == g) / len(pairs), len(pairs)


def _paired_bootstrap_delta(preds_a, preds_b, test_sentences, label_map, iters=10000, seed=0):
    """95% CI for acc(preds_a) - acc(preds_b) against the same labels, paired
    by item (both prompts are scored on identical items in each resample)."""
    idxs = [i for i, s in enumerate(test_sentences) if s in label_map]
    golds = [label_map[test_sentences[i]] for i in idxs]
    a = [1 if preds_a[i] == g else 0 for i, g in zip(idxs, golds)]
    b = [1 if preds_b[i] == g else 0 for i, g in zip(idxs, golds)]
    n = len(golds)
    rng = random.Random(seed)
    diffs = sorted(
        sum(a[j] - b[j] for j in (rng.randrange(n) for _ in range(n))) / n
        for _ in range(iters)
    )
    return diffs[int(0.025 * iters)], diffs[int(0.975 * iters)]


async def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dim", default="Disclosure as confession")
    ap.add_argument("--codebook", default="self_disclosure")
    ap.add_argument("--budget", type=int, default=5)
    ap.add_argument("--limit", type=int, default=160, help="cap train items per coder")
    ap.add_argument("--provider", default="openai")
    ap.add_argument("--model", default="gpt-5.4-mini")
    ap.add_argument("--concurrency", type=int, default=8)
    ap.add_argument("--out", default=str(REPO_ROOT / "exp_result_specificity.json"))
    ap.add_argument("--seed", type=int, default=0, help="split seed index; 0 reproduces the original run")
    args = ap.parse_args()
    args.api_key = resolve_api_key(args.provider)
    if not args.api_key:
        raise SystemExit("No API key.")

    cb = parse_codebook(json.loads((PRESETS_DIR / f"{args.codebook}.json").read_text()))
    dim = next(d for d in cb.dimensions if d.name == args.dim)
    valid = [l.name for l in dim.labels]

    fiona = _labels_for(_load_items("fiona", args.codebook), dim, valid)
    chang = _labels_for(_load_items("chang", args.codebook), dim, valid)
    shared = sorted(set(fiona) & set(chang))
    raw_agree = sum(1 for s in shared if fiona[s] == chang[s]) / len(shared) if shared else 0.0
    print(f"{args.dim}: fiona {len(fiona)}, chang {len(chang)}, shared {len(shared)} "
          f"(raw inter-coder agreement {raw_agree*100:.1f}%)")

    # Hold out a shared test set; each coder trains on their own non-test items.
    shared_parts = ["shared", args.dim] + ([args.seed] if args.seed else [])
    sh_train, sh_test = _split(shared, _seed(*shared_parts), 0.5)
    test_block = set(sh_test)
    f_train = [s for s in fiona if s not in test_block]
    c_train = [s for s in chang if s not in test_block]

    pF, rF = await _tune(fiona, f_train, dim, valid, args)
    pC, rC = await _tune(chang, c_train, dim, valid, args)

    # 2x2: prompt (F,C) x target labels (F,C) on the SAME shared test items.
    # One cached prediction vector per prompt; every cell scores from the cache.
    predsF = await _predict(pF, sh_test, valid, args)
    predsC = await _predict(pC, sh_test, valid, args)
    aFF, n = _score(predsF, sh_test, fiona)
    aCF, _ = _score(predsC, sh_test, fiona)
    aFC, _ = _score(predsF, sh_test, chang)
    aCC, _ = _score(predsC, sh_test, chang)

    # Paired bootstrap for the diagonal advantage (own prompt vs other prompt,
    # same target labels, same items).
    ci_fiona = _paired_bootstrap_delta(predsF, predsC, sh_test, fiona)
    ci_chang = _paired_bootstrap_delta(predsC, predsF, sh_test, chang)

    print(f"\nShared test n={n}")
    print(f"                 target=Fiona   target=Chang")
    print(f"  prompt=Fiona      {aFF*100:5.1f}         {aFC*100:5.1f}")
    print(f"  prompt=Chang      {aCF*100:5.1f}         {aCC*100:5.1f}")
    print(f"\nSpecificity (own minus other): Fiona {(aFF-aCF)*100:+.1f}pp "
          f"(95% CI [{ci_fiona[0]*100:+.1f}, {ci_fiona[1]*100:+.1f}]), "
          f"Chang {(aCC-aFC)*100:+.1f}pp "
          f"(95% CI [{ci_chang[0]*100:+.1f}, {ci_chang[1]*100:+.1f}])")

    out = {
        "generated": datetime.now().strftime("%Y-%m-%d %H:%M"),
        "dim": dim.name, "model": args.model, "budget": args.budget,
        "shared_n": len(shared), "raw_inter_coder_agreement": raw_agree, "test_n": n,
        "matrix": {"prompt_fiona": {"target_fiona": aFF, "target_chang": aFC},
                   "prompt_chang": {"target_fiona": aCF, "target_chang": aCC}},
        "specificity_pp": {"fiona": (aFF - aCF) * 100, "chang": (aCC - aFC) * 100},
        "specificity_ci95_pp": {
            "fiona": [ci_fiona[0] * 100, ci_fiona[1] * 100],
            "chang": [ci_chang[0] * 100, ci_chang[1] * 100],
        },
        # Per-item predictions so any pairing/bootstrap can be recomputed offline.
        "test_sentences": list(sh_test),
        "predictions": {"prompt_fiona": list(predsF), "prompt_chang": list(predsC)},
        "gold": {"fiona": {s: fiona.get(s) for s in sh_test},
                 "chang": {s: chang.get(s) for s in sh_test}},
        "rules_fiona": rF, "rules_chang": rC,
    }
    Path(args.out).write_text(json.dumps(out, indent=2))
    print(f"\nSaved {args.out}")


if __name__ == "__main__":
    asyncio.run(main())
