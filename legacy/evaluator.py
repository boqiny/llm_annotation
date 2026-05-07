# eval_utils.py
from typing import List, Dict
from collections import Counter, defaultdict
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

# ------------------------------------------------
# NEW: Comprehensive evaluation
# ------------------------------------------------
def compute_full_eval(
    y_true: List[str],
    y_pred: List[str],
    schemes: List[str],
) -> Dict:
    """
    Produce:
    - ground truth scheme distribution
    - per-scheme metrics
    - global metrics (micro)
    """

    assert len(y_true) == len(y_pred) == len(schemes)

    # -----------------------------
    # Ground truth scheme distribution
    # -----------------------------
    scheme_counts = Counter(schemes)

    # -----------------------------
    # Per-scheme metrics
    # -----------------------------
    per_scheme_metrics = {}

    # group indices by scheme
    scheme_to_indices = defaultdict(list)
    for i, s in enumerate(schemes):
        scheme_to_indices[s].append(i)

    for scheme, idxs in scheme_to_indices.items():
        y_true_s = [y_true[i] for i in idxs]
        y_pred_s = [y_pred[i] for i in idxs]

        prf = compute_prf(y_true_s, y_pred_s, average="micro")

        per_scheme_metrics[scheme] = {
            "precision": prf["precision"],
            "recall": prf["recall"],
            "f1": prf["f1"],
            "accuracy": prf["accuracy"],
            "n": len(idxs),
        }

    # -----------------------------
    # Global metrics
    # -----------------------------
    global_metrics = compute_prf(y_true, y_pred, average="micro")

    return {
        "stats": {
            "n_samples": len(set(range(len(y_true)))),
            "n_evaluated_sentences": len(y_true),
            "per_scheme_counts": dict(scheme_counts),
        },
        "per_scheme_metrics": per_scheme_metrics,
        "global_metrics": global_metrics,
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