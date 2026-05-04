"""
Evaluation utilities.

This module provides lightweight metrics for annotation outputs, including
single-label and multi-label classification evaluation.

Responsibilities:
- Normalize predicted and gold labels.
- Compute exact-match accuracy.
- Compute micro/macro precision, recall, and F1.
- Return structured evaluation results for saving or frontend display.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from typing import Any, Iterable


Label = str
LabelSet = set[Label]


@dataclass
class LabelMetrics:
    label: str
    precision: float
    recall: float
    f1: float
    support: int


@dataclass
class EvaluationResult:
    accuracy: float
    micro_precision: float
    micro_recall: float
    micro_f1: float
    macro_precision: float
    macro_recall: float
    macro_f1: float
    num_items: int
    per_label: list[LabelMetrics]


def normalize_labels(labels: Any) -> LabelSet:
    if labels is None:
        return set()

    if isinstance(labels, str):
        return {labels}

    if isinstance(labels, list | tuple | set):
        return {str(label) for label in labels}

    raise ValueError(f"Unsupported label format: {type(labels)}")


def safe_divide(numerator: float, denominator: float) -> float:
    return numerator / denominator if denominator else 0.0


def evaluate_classification(
    gold_items: list[dict[str, Any]],
    pred_items: list[dict[str, Any]],
    gold_label_key: str = "label",
    pred_label_key: str = "prediction",
    id_key: str = "item_id",
) -> EvaluationResult:
    """
    Evaluate single-label or multi-label classification.

    Expected formats:
      gold_items = [{"item_id": "1", "label": "A"}]
      pred_items = [{"item_id": "1", "prediction": "A"}]

    Multi-label:
      gold_items = [{"item_id": "1", "label": ["A", "B"]}]
      pred_items = [{"item_id": "1", "prediction": ["A"]}]
    """

    pred_by_id = {item[id_key]: item for item in pred_items}

    total = 0
    exact_match = 0

    tp = defaultdict(int)
    fp = defaultdict(int)
    fn = defaultdict(int)
    support = defaultdict(int)

    all_labels: set[str] = set()

    for gold_item in gold_items:
        item_id = gold_item[id_key]
        if item_id not in pred_by_id:
            raise ValueError(f"Missing prediction for item_id={item_id!r}")

        gold = normalize_labels(gold_item.get(gold_label_key))
        pred = normalize_labels(pred_by_id[item_id].get(pred_label_key))

        total += 1
        if gold == pred:
            exact_match += 1

        all_labels.update(gold)
        all_labels.update(pred)

        for label in gold:
            support[label] += 1

        for label in all_labels | gold | pred:
            if label in gold and label in pred:
                tp[label] += 1
            elif label not in gold and label in pred:
                fp[label] += 1
            elif label in gold and label not in pred:
                fn[label] += 1

    per_label: list[LabelMetrics] = []

    total_tp = total_fp = total_fn = 0

    for label in sorted(all_labels):
        label_tp = tp[label]
        label_fp = fp[label]
        label_fn = fn[label]

        total_tp += label_tp
        total_fp += label_fp
        total_fn += label_fn

        precision = safe_divide(label_tp, label_tp + label_fp)
        recall = safe_divide(label_tp, label_tp + label_fn)
        f1 = safe_divide(2 * precision * recall, precision + recall)

        per_label.append(
            LabelMetrics(
                label=label,
                precision=precision,
                recall=recall,
                f1=f1,
                support=support[label],
            )
        )

    micro_precision = safe_divide(total_tp, total_tp + total_fp)
    micro_recall = safe_divide(total_tp, total_tp + total_fn)
    micro_f1 = safe_divide(
        2 * micro_precision * micro_recall,
        micro_precision + micro_recall,
    )

    macro_precision = safe_divide(
        sum(m.precision for m in per_label),
        len(per_label),
    )
    macro_recall = safe_divide(
        sum(m.recall for m in per_label),
        len(per_label),
    )
    macro_f1 = safe_divide(
        sum(m.f1 for m in per_label),
        len(per_label),
    )

    return EvaluationResult(
        accuracy=safe_divide(exact_match, total),
        micro_precision=micro_precision,
        micro_recall=micro_recall,
        micro_f1=micro_f1,
        macro_precision=macro_precision,
        macro_recall=macro_recall,
        macro_f1=macro_f1,
        num_items=total,
        per_label=per_label,
    )


def result_to_dict(result: EvaluationResult) -> dict[str, Any]:
    return {
        "accuracy": result.accuracy,
        "micro_precision": result.micro_precision,
        "micro_recall": result.micro_recall,
        "micro_f1": result.micro_f1,
        "macro_precision": result.macro_precision,
        "macro_recall": result.macro_recall,
        "macro_f1": result.macro_f1,
        "num_items": result.num_items,
        "per_label": [
            {
                "label": m.label,
                "precision": m.precision,
                "recall": m.recall,
                "f1": m.f1,
                "support": m.support,
            }
            for m in result.per_label
        ],
    }
    