# eval_utils.py
from typing import List, Dict
from sklearn.metrics import precision_recall_fscore_support, accuracy_score

def compute_prf(
    y_true: List[str],
    y_pred: List[str],
    average: str = "macro",
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
