# eval_utils.py
from typing import List, Dict
from sklearn.metrics import precision_recall_fscore_support, accuracy_score

def compute_prf(
    y_true: List[str],
    y_pred: List[str],
    average: str = "micro",
) -> Dict[str, float]:
    """
    Compute precision / recall / F1 for single-label classification.

    average:
        - "macro": unweighted mean over labels (recommended for research)
        - "micro": global TP/FP/FN (good for imbalance)
        - "weighted": weighted by support
    """
    precision, recall, f1, _ = precision_recall_fscore_support(
        y_true,
        y_pred,
        average=average,
        zero_division=0,
    )
    acc = accuracy_score(y_true, y_pred)

    return {
        "precision": precision,
        "recall": recall,
        "f1": f1,
        "accuracy": acc,
    }

def compute_absolute_metrics(
    y_true: List[str],
    y_pred: List[str],
) -> Dict[str, float]:
    """
    Compute straightforward (global) precision / recall / F1 / accuracy
    by aggregating TP / FP / FN across all labels.
    """
    assert len(y_true) == len(y_pred)

    tp = sum(yt == yp for yt, yp in zip(y_true, y_pred))
    fp = sum(yt != yp for yt, yp in zip(y_true, y_pred))
    fn = fp  # for single-label classification, FP == FN globally

    precision = tp / (tp + fp) if (tp + fp) > 0 else 0.0
    recall = tp / (tp + fn) if (tp + fn) > 0 else 0.0
    f1 = (
        2 * precision * recall / (precision + recall)
        if (precision + recall) > 0
        else 0.0
    )
    accuracy = tp / len(y_true) if y_true else 0.0

    return {
        "precision": precision,
        "recall": recall,
        "f1": f1,
        "accuracy": accuracy,
        "tp": tp,
        "fp": fp,
        "fn": fn,
        "n": len(y_true),
    }