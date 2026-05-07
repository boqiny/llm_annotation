"""Classification metrics: accuracy, per-class P/R/F1, confusion matrix.

Refactored from eval_self_disclosure.py -- works with any label set.
"""
from __future__ import annotations

from collections import defaultdict
from typing import Any


def compute_metrics(y_true: list[str], y_pred: list[str]) -> dict[str, Any]:
    """Compute accuracy, macro/weighted/micro P/R/F1, per-class breakdown."""
    if not y_true:
        return {"accuracy": 0.0, "n": 0}

    assert len(y_true) == len(y_pred)
    n = len(y_true)
    accuracy = sum(yt == yp for yt, yp in zip(y_true, y_pred)) / n

    all_classes = sorted(set(y_true) | set(y_pred))
    per_class: dict[str, dict[str, Any]] = {}
    precisions, recalls, f1s, supports = [], [], [], []

    for cls in all_classes:
        tp = sum((yp == cls and yt == cls) for yt, yp in zip(y_true, y_pred))
        fp = sum((yp == cls and yt != cls) for yt, yp in zip(y_true, y_pred))
        fn = sum((yp != cls and yt == cls) for yt, yp in zip(y_true, y_pred))
        support = tp + fn
        precision = tp / (tp + fp) if (tp + fp) > 0 else 0.0
        recall = tp / (tp + fn) if (tp + fn) > 0 else 0.0
        f1 = (2 * precision * recall / (precision + recall)) if (precision + recall) > 0 else 0.0
        per_class[cls] = {
            "precision": precision, "recall": recall, "f1": f1,
            "support": support, "tp": tp, "fp": fp, "fn": fn,
        }
        if support > 0:
            precisions.append(precision)
            recalls.append(recall)
            f1s.append(f1)
            supports.append(support)

    total_support = sum(supports)
    macro_p = sum(precisions) / len(precisions) if precisions else 0.0
    macro_r = sum(recalls) / len(recalls) if recalls else 0.0
    macro_f1 = sum(f1s) / len(f1s) if f1s else 0.0
    weighted_f1 = (
        sum(f * s for f, s in zip(f1s, supports)) / total_support
        if total_support > 0 else 0.0
    )

    return {
        "accuracy": accuracy,
        "macro_precision": macro_p,
        "macro_recall": macro_r,
        "macro_f1": macro_f1,
        "weighted_f1": weighted_f1,
        "per_class": per_class,
        "n": n,
        "n_classes": len(all_classes),
        "classes": all_classes,
    }


def confusion_matrix(y_true: list[str], y_pred: list[str]) -> dict[str, Any]:
    """Build a confusion matrix dict: {true_label: {pred_label: count}}."""
    all_classes = sorted(set(y_true) | set(y_pred))
    matrix: dict[str, dict[str, int]] = {c: {c2: 0 for c2 in all_classes} for c in all_classes}
    for yt, yp in zip(y_true, y_pred):
        matrix[yt][yp] += 1
    return {"classes": all_classes, "matrix": matrix}


def _normalize_labels(value: Any) -> set[str]:
    """Coerce a label cell to a set of label strings (single- and multi-label)."""
    if value is None:
        return set()
    if isinstance(value, str):
        return {value} if value else set()
    if isinstance(value, (list, tuple, set)):
        return {str(v) for v in value if v is not None and str(v) != ""}
    raise ValueError(f"Unsupported label format: {type(value)}")


def _safe_div(num: float, denom: float) -> float:
    return num / denom if denom else 0.0


def compute_metrics_multilabel(
    y_true: list[Any],
    y_pred: list[Any],
) -> dict[str, Any]:
    """Compute exact-match accuracy + micro/macro P/R/F1 + per-label.

    Each y_true / y_pred element may be a string (single-label) or a list/set
    (multi-label). The result schema is comparable to ``compute_metrics`` but
    adds ``micro_*`` keys and treats supports per-label.

    Ported from ``annotation_demo/.../core/evaluation.py``.
    """
    if not y_true:
        return {"accuracy": 0.0, "n": 0, "per_label": {}, "labels": []}
    assert len(y_true) == len(y_pred)

    n = len(y_true)
    exact = 0
    tp: dict[str, int] = defaultdict(int)
    fp: dict[str, int] = defaultdict(int)
    fn: dict[str, int] = defaultdict(int)
    support: dict[str, int] = defaultdict(int)
    all_labels: set[str] = set()

    for yt_raw, yp_raw in zip(y_true, y_pred):
        yt = _normalize_labels(yt_raw)
        yp = _normalize_labels(yp_raw)
        if yt == yp:
            exact += 1
        all_labels |= yt | yp
        for lbl in yt:
            support[lbl] += 1
        for lbl in yt | yp:
            if lbl in yt and lbl in yp:
                tp[lbl] += 1
            elif lbl in yp:
                fp[lbl] += 1
            else:
                fn[lbl] += 1

    per_label: dict[str, dict[str, Any]] = {}
    total_tp = total_fp = total_fn = 0
    p_list: list[float] = []
    r_list: list[float] = []
    f_list: list[float] = []

    for lbl in sorted(all_labels):
        ltp, lfp, lfn = tp[lbl], fp[lbl], fn[lbl]
        total_tp += ltp
        total_fp += lfp
        total_fn += lfn
        precision = _safe_div(ltp, ltp + lfp)
        recall = _safe_div(ltp, ltp + lfn)
        f1 = _safe_div(2 * precision * recall, precision + recall)
        per_label[lbl] = {
            "precision": precision, "recall": recall, "f1": f1,
            "support": support[lbl], "tp": ltp, "fp": lfp, "fn": lfn,
        }
        p_list.append(precision)
        r_list.append(recall)
        f_list.append(f1)

    micro_p = _safe_div(total_tp, total_tp + total_fp)
    micro_r = _safe_div(total_tp, total_tp + total_fn)
    micro_f1 = _safe_div(2 * micro_p * micro_r, micro_p + micro_r)

    return {
        "accuracy": _safe_div(exact, n),
        "micro_precision": micro_p,
        "micro_recall": micro_r,
        "micro_f1": micro_f1,
        "macro_precision": _safe_div(sum(p_list), len(p_list)),
        "macro_recall": _safe_div(sum(r_list), len(r_list)),
        "macro_f1": _safe_div(sum(f_list), len(f_list)),
        "n": n,
        "per_label": per_label,
        "labels": sorted(all_labels),
    }
