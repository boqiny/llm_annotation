"""
Compare test data annotations with ground truth.
Evaluates Stage 1 (is_disclosure) and Stage 2 (detailed schemes) separately.
"""

import json
from typing import Dict, List, Tuple


def load_json(filepath: str) -> dict:
    """Load JSON file."""
    with open(filepath, 'r', encoding='utf-8') as f:
        return json.load(f)


def normalize_label(label) -> str:
    """Normalize label (handle None and strip whitespace)."""
    if label is None:
        return "N/A"
    return str(label).strip()


def compute_metrics(y_true: List[str], y_pred: List[str]) -> Dict[str, float]:
    """Compute accuracy and per-class metrics."""
    assert len(y_true) == len(y_pred)
    
    if not y_true:
        return {"accuracy": 0.0, "n": 0}
    
    # Overall accuracy
    correct = sum(yt == yp for yt, yp in zip(y_true, y_pred))
    accuracy = correct / len(y_true)
    
    # Get all unique classes
    all_classes = sorted(set(y_true) | set(y_pred))
    
    # Per-class metrics
    per_class_metrics = {}
    
    for cls in all_classes:
        tp = sum((yp == cls and yt == cls) for yt, yp in zip(y_true, y_pred))
        fp = sum((yp == cls and yt != cls) for yt, yp in zip(y_true, y_pred))
        fn = sum((yp != cls and yt == cls) for yt, yp in zip(y_true, y_pred))
        support = sum(yt == cls for yt in y_true)
        
        precision = tp / (tp + fp) if (tp + fp) > 0 else 0.0
        recall = tp / (tp + fn) if (tp + fn) > 0 else 0.0
        f1 = (2 * precision * recall / (precision + recall)) if (precision + recall) > 0 else 0.0
        
        per_class_metrics[cls] = {
            "precision": precision,
            "recall": recall,
            "f1": f1,
            "support": support,
            "tp": tp,
            "fp": fp,
            "fn": fn,
        }
    
    # Macro-averaged metrics
    class_metrics = [m for m in per_class_metrics.values() if m["support"] > 0]
    macro_precision = sum(m["precision"] for m in class_metrics) / len(class_metrics) if class_metrics else 0.0
    macro_recall = sum(m["recall"] for m in class_metrics) / len(class_metrics) if class_metrics else 0.0
    macro_f1 = sum(m["f1"] for m in class_metrics) / len(class_metrics) if class_metrics else 0.0
    
    return {
        "accuracy": accuracy,
        "macro_precision": macro_precision,
        "macro_recall": macro_recall,
        "macro_f1": macro_f1,
        "per_class": per_class_metrics,
        "n": len(y_true),
        "n_correct": correct,
        "n_incorrect": len(y_true) - correct,
    }


def compare_results(gt_path: str, pred_path: str):
    """Compare ground truth with predictions."""
    
    print("="*80)
    print("TWO-STAGE ANNOTATION EVALUATION")
    print("="*80)
    print(f"Ground Truth: {gt_path}")
    print(f"Predictions:  {pred_path}")
    print("="*80 + "\n")
    
    # Load data
    gt_data = load_json(gt_path)
    pred_data = load_json(pred_path)
    
    gt_results = gt_data.get("results", [])
    pred_results = pred_data.get("results", [])
    
    # Create lookup by Index
    gt_map = {r["Index"]: r for r in gt_results}
    pred_map = {r["Index"]: r for r in pred_results}
    
    # Find common indices
    common_indices = sorted(set(gt_map.keys()) & set(pred_map.keys()))
    
    print(f"Ground truth items: {len(gt_results)}")
    print(f"Predicted items: {len(pred_results)}")
    print(f"Common items: {len(common_indices)}\n")
    
    # ========================================================================
    # STAGE 1: Is Disclosure?
    # ========================================================================
    
    print("="*80)
    print("STAGE 1 EVALUATION: Is Disclosure?")
    print("="*80 + "\n")
    
    stage1_gt = []
    stage1_pred = []
    
    for idx in common_indices:
        gt_item = gt_map[idx]
        pred_item = pred_map[idx]
        
        gt_is_disclosure = normalize_label(gt_item.get("is_disclosure"))
        pred_is_disclosure = normalize_label(pred_item.get("is_disclosure"))
        
        stage1_gt.append(gt_is_disclosure)
        stage1_pred.append(pred_is_disclosure)
    
    stage1_metrics = compute_metrics(stage1_gt, stage1_pred)
    
    print(f"Accuracy: {stage1_metrics['accuracy']:.1%} ({stage1_metrics['n_correct']}/{stage1_metrics['n']})")
    print(f"Macro F1: {stage1_metrics['macro_f1']:.3f}")
    print(f"Macro Precision: {stage1_metrics['macro_precision']:.3f}")
    print(f"Macro Recall: {stage1_metrics['macro_recall']:.3f}\n")
    
    print("Per-class metrics:")
    print("-"*80)
    for cls, metrics in sorted(stage1_metrics['per_class'].items()):
        print(f"  {cls}:")
        print(f"    Precision: {metrics['precision']:.3f}")
        print(f"    Recall: {metrics['recall']:.3f}")
        print(f"    F1: {metrics['f1']:.3f}")
        print(f"    Support: {metrics['support']}")
    
    # Show errors
    print("\nStage 1 Errors:")
    print("-"*80)
    error_count = 0
    for idx in common_indices:
        gt_item = gt_map[idx]
        pred_item = pred_map[idx]
        
        gt_is = normalize_label(gt_item.get("is_disclosure"))
        pred_is = normalize_label(pred_item.get("is_disclosure"))
        
        if gt_is != pred_is:
            error_count += 1
            if error_count <= 10:  # Show first 10 errors
                print(f"  [{idx}] Gold: {gt_is}, Predicted: {pred_is}")
                print(f"      Sentence: {gt_item.get('sentence', '')[:80]}...")
    
    if error_count > 10:
        print(f"  ... and {error_count - 10} more errors")
    elif error_count == 0:
        print("  No errors!")
    
    # ========================================================================
    # STAGE 2: Detailed Schemes (only for is_disclosure = "Yes")
    # ========================================================================
    
    print("\n" + "="*80)
    print("STAGE 2 EVALUATION: Detailed Schemes (only items with is_disclosure=Yes)")
    print("="*80 + "\n")
    
    # Filter to only items where BOTH gt and pred have is_disclosure = "Yes"
    disclosure_indices = [
        idx for idx in common_indices
        if normalize_label(gt_map[idx].get("is_disclosure")) == "Yes"
        and normalize_label(pred_map[idx].get("is_disclosure")) == "Yes"
    ]
    
    print(f"Items with is_disclosure=Yes in both GT and predictions: {len(disclosure_indices)}\n")
    
    # Evaluate each scheme
    schemes = [
        "Level of disclosure",
        "Depth of disclosure",
        "Intimacy of self-disclosure",
        "Disclosure as confession",
    ]
    
    scheme_metrics = {}
    
    for scheme in schemes:
        y_true = []
        y_pred = []
        
        for idx in disclosure_indices:
            gt_item = gt_map[idx]
            pred_item = pred_map[idx]
            
            gt_label = normalize_label(gt_item.get(scheme))
            pred_label = normalize_label(pred_item.get(scheme))
            
            # Only evaluate if ground truth has a label for this scheme
            if gt_label != "N/A":
                y_true.append(gt_label)
                y_pred.append(pred_label)
        
        if y_true:
            metrics = compute_metrics(y_true, y_pred)
            scheme_metrics[scheme] = metrics
            
            print(f"--- {scheme} ---")
            print(f"Accuracy: {metrics['accuracy']:.1%} ({metrics['n_correct']}/{metrics['n']})")
            print(f"Macro F1: {metrics['macro_f1']:.3f}")
            print(f"Macro Precision: {metrics['macro_precision']:.3f}")
            print(f"Macro Recall: {metrics['macro_recall']:.3f}\n")
            
            print("Per-class metrics:")
            for cls, cls_metrics in sorted(metrics['per_class'].items()):
                if cls_metrics['support'] > 0:
                    print(f"  {cls}: P={cls_metrics['precision']:.3f}, R={cls_metrics['recall']:.3f}, F1={cls_metrics['f1']:.3f}, Support={cls_metrics['support']}")
            
            # Show errors for this scheme
            print("\nErrors:")
            error_count = 0
            for idx in disclosure_indices:
                gt_label = normalize_label(gt_map[idx].get(scheme))
                pred_label = normalize_label(pred_map[idx].get(scheme))
                
                if gt_label != "N/A" and gt_label != pred_label:
                    error_count += 1
                    if error_count <= 5:  # Show first 5 errors per scheme
                        print(f"  [{idx}] Gold: {gt_label}, Predicted: {pred_label}")
                        print(f"      Sentence: {gt_map[idx].get('sentence', '')[:80]}...")
            
            if error_count > 5:
                print(f"  ... and {error_count - 5} more errors")
            elif error_count == 0:
                print("  No errors!")
            
            print()
        else:
            print(f"--- {scheme} ---")
            print("No labeled data available for evaluation\n")
    
    # ========================================================================
    # SUMMARY
    # ========================================================================
    
    print("="*80)
    print("SUMMARY")
    print("="*80)
    print(f"\nStage 1 (Is Disclosure):")
    print(f"  Accuracy: {stage1_metrics['accuracy']:.1%}")
    print(f"  Macro F1: {stage1_metrics['macro_f1']:.3f}")
    
    print(f"\nStage 2 (Detailed Schemes):")
    for scheme, metrics in scheme_metrics.items():
        print(f"  {scheme}:")
        print(f"    Accuracy: {metrics['accuracy']:.1%}, Macro F1: {metrics['macro_f1']:.3f}")
    
    print("\n" + "="*80)


if __name__ == "__main__":
    import argparse
    
    parser = argparse.ArgumentParser(description="Compare test annotations with ground truth")
    parser.add_argument(
        "--dataset",
        type=str,
        default=None,
        help="Dataset name (without .json) — sets --pred to ./results/<dataset>_annotations.json and --gt to ./results/<dataset>_gt.json",
    )
    parser.add_argument(
        "--gt",
        type=str,
        default=None,
        help="Path to ground truth JSON (overrides --dataset if set)",
    )
    parser.add_argument(
        "--pred",
        type=str,
        default=None,
        help="Path to predictions JSON (overrides --dataset if set)",
    )

    args = parser.parse_args()

    if args.pred:
        pred_path = args.pred
    elif args.dataset:
        pred_path = f"./results/{args.dataset}_annotations.json"
    else:
        pred_path = "./results/test_data_annotations.json"

    if args.gt:
        gt_path = args.gt
    elif args.dataset:
        gt_path = f"./results/{args.dataset}_gt.json"
    else:
        gt_path = "./results/test_data_gt.json"

    compare_results(gt_path, pred_path)
