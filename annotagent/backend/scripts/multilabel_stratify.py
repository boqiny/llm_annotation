"""Deterministic multi-label stratification + paired bootstrap for set predictions.

Two helpers used by the rigorous multi-label rerun (see additional_exp.md):

  - ``iterative_stratification`` splits items into train/val/test so that each
    label's support is spread across the splits in the requested proportions.
    This is the standard label-balanced stratification (Sechidis et al., 2011),
    implemented dependency-free and seeded for reproducibility. It replaces the
    old random 40/30/30 split in ``multilabel_diag.py`` (which the reviewer
    flagged: non-stratified, and inconsistent N per seed).

  - ``paired_bootstrap_delta`` gives a 95% CI for the micro-F1 gap between two
    prediction conditions evaluated on the SAME test items, resampling items
    with replacement. No extra LLM calls — it reads saved per-item gold/pred.
"""
from __future__ import annotations

import random
from collections import Counter, defaultdict
from typing import Sequence


def iterative_stratification(
    label_sets: Sequence[set[str]],
    fractions: dict[str, float],
    seed: int,
) -> dict[str, list[int]]:
    """Return {split_name: [item indices]} with label support balanced by fraction.

    ``label_sets[i]`` is the set of gold labels for item ``i`` (may be empty).
    ``fractions`` must sum to 1.0 (e.g. {"train":0.15,"val":0.42,"test":0.43}).
    Deterministic given ``seed``.
    """
    assert abs(sum(fractions.values()) - 1.0) < 1e-6, "fractions must sum to 1"
    rng = random.Random(seed)
    n = len(label_sets)
    splits = list(fractions)

    # Desired total items per split, and desired items carrying each label.
    desired_n = {s: fractions[s] * n for s in splits}
    label_total = Counter(l for ls in label_sets for l in ls)
    desired_sl = {s: {l: fractions[s] * c for l, c in label_total.items()} for s in splits}

    result: dict[str, list[int]] = {s: [] for s in splits}
    remaining = set(range(n))

    def _assign(i: int, s: str) -> None:
        result[s].append(i)
        remaining.discard(i)
        desired_n[s] -= 1
        for l in label_sets[i]:
            desired_sl[s][l] -= 1

    while remaining:
        # Rarest label still present among remaining items (fewest remaining
        # occurrences) is placed first — rare labels are hardest to balance.
        rem_counts: Counter = Counter()
        for i in remaining:
            for l in label_sets[i]:
                rem_counts[l] += 1

        if rem_counts:
            label = min(rem_counts, key=lambda k: (rem_counts[k], k))
            pool = [i for i in remaining if label in label_sets[i]]
        else:  # only label-less items remain
            label = None
            pool = list(remaining)

        rng.shuffle(pool)  # deterministic tie-break within the pool
        for i in pool:
            if i not in remaining:
                continue
            if label is not None:
                # split that most wants this label; ties -> most-wanted overall
                best = max(splits, key=lambda s: (desired_sl[s][label], desired_n[s], rng.random()))
            else:
                best = max(splits, key=lambda s: (desired_n[s], rng.random()))
            _assign(i, best)

    return result


def split_report(label_sets: Sequence[set[str]], assignment: dict[str, list[int]]) -> dict:
    """Human-auditable per-split, per-label support counts."""
    rep: dict[str, dict] = {}
    for s, idxs in assignment.items():
        counts: Counter = Counter()
        for i in idxs:
            for l in label_sets[i]:
                counts[l] += 1
        rep[s] = {"n_items": len(idxs), "label_support": dict(sorted(counts.items()))}
    return rep


def _micro_f1(golds: list[set[str]], preds: list[set[str]]) -> float:
    tp = fp = fn = 0
    for g, p in zip(golds, preds):
        tp += len(g & p)
        fp += len(p - g)
        fn += len(g - p)
    if tp == 0:
        return 0.0
    prec = tp / (tp + fp)
    rec = tp / (tp + fn)
    return 2 * prec * rec / (prec + rec) if (prec + rec) else 0.0


def paired_bootstrap_delta(
    golds: list[set[str]],
    preds_a: list[set[str]],
    preds_b: list[set[str]],
    iters: int = 10000,
    seed: int = 0,
) -> tuple[float, float, float]:
    """95% CI for micro_f1(preds_a) - micro_f1(preds_b) on the same items.

    Returns (point_estimate_pp, lo_pp, hi_pp) in percentage points. Both
    conditions are resampled with the SAME bootstrap indices (paired).
    """
    n = len(golds)
    point = (_micro_f1(golds, preds_a) - _micro_f1(golds, preds_b)) * 100
    rng = random.Random(seed)
    diffs = []
    for _ in range(iters):
        idx = [rng.randrange(n) for _ in range(n)]
        g = [golds[i] for i in idx]
        a = [preds_a[i] for i in idx]
        b = [preds_b[i] for i in idx]
        diffs.append((_micro_f1(g, a) - _micro_f1(g, b)) * 100)
    diffs.sort()
    return point, diffs[int(0.025 * iters)], diffs[int(0.975 * iters)]
