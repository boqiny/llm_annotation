"""Classification metrics: accuracy, per-class P/R/F1, confusion matrix.

Refactored from eval_self_disclosure.py -- works with any label set.
"""
from __future__ import annotations

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
