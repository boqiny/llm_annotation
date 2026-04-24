"""Evaluate self-disclosure annotations using enhanced GEPA-optimized prompt.

Usage:
    # Evaluate agreed dataset (only sentences where Fiona and Chang agree):
    python3 eval_self_disclosure.py --dataset agreed
    
    # Evaluate subset:
    python3 eval_self_disclosure.py --dataset fiona --n_rows 100
    
    # Use specific scheme only:
    python3 eval_self_disclosure.py --scheme "Level of disclosure"
"""
from __future__ import annotations

import argparse
import json
import os
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from typing import Dict, List, Tuple, Optional

from tqdm import tqdm
import dspy
from dotenv import load_dotenv

from prompts.self_disclosure_prompt import ENHANCED_SYSTEM_PROMPT
from prompts.depth_disclosure_prompt import ENHANCED_DEPTH_PROMPT
from prompts.intimacy_disclosure_prompt import ENHANCED_INTIMACY_PROMPT
from prompts.confession_disclosure_prompt import ENHANCED_CONFESSION_PROMPT
from prompts.temporality_prompt import ENHANCED_TEMPORALITY_PROMPT
from prompts.topic_classification_prompt import TOPIC_CLASSIFICATION_PROMPT
from prompts.theme_classification_prompt import THEME_CLASSIFICATION_PROMPT
from prompts.parser import parse_answer

load_dotenv()
# Configure DSPy — 256 tokens to accommodate Topic/Theme reasoning + label
dspy.configure(lm=dspy.LM("openai/gpt-5.2", max_tokens=256))


@dataclass(frozen=True)
class EvalConfig:
    """Configuration for evaluating self-disclosure annotations."""
    dataset: str = "agreed"  # Options: "fiona", "chang", or "agreed"
    n_rows: Optional[int] = None  # Set to None to process all items
    max_workers: int = 10  # Parallel processing workers
    scheme: Optional[str] = None  # If set, only evaluate this scheme
    
    @property
    def json_path(self) -> str:
        return f"./data/cleaned/{self.dataset}_self_disclosure_ground_truth.json"
    
    @property
    def out_path(self) -> str:
        scheme_suffix = f"_{self.scheme.replace(' ', '_').lower()}" if self.scheme else ""
        return f"./results/{self.dataset}_self_disclosure_eval_results{scheme_suffix}.json"


# Define DSPy signature for Level of disclosure (enhanced prompt)
class LevelOfDisclosureSignature(dspy.Signature):
    __doc__ = ENHANCED_SYSTEM_PROMPT
    sentence: str = dspy.InputField(desc="The user message to classify")
    reasoning_and_answer: str = dspy.OutputField(
        desc="Brief reasoning followed by 'Answer: High', 'Answer: Low', or 'Answer: No'"
    )


class LevelOfDisclosureClassifier(dspy.Module):
    def __init__(self):
        super().__init__()
        self.classify = dspy.Predict(LevelOfDisclosureSignature)

    def forward(self, sentence):
        result = self.classify(sentence=sentence)
        return dspy.Prediction(reasoning_and_answer=result.reasoning_and_answer)


# Define DSPy signature for Depth of disclosure (enhanced prompt)
class DepthOfDisclosureSignature(dspy.Signature):
    __doc__ = ENHANCED_DEPTH_PROMPT
    sentence: str = dspy.InputField(desc="The user message to classify")
    reasoning_and_answer: str = dspy.OutputField(
        desc="Brief reasoning followed by 'Answer: Peripheral', 'Answer: Intermediate', or 'Answer: Central'"
    )


class DepthOfDisclosureClassifier(dspy.Module):
    def __init__(self):
        super().__init__()
        self.classify = dspy.Predict(DepthOfDisclosureSignature)

    def forward(self, sentence):
        result = self.classify(sentence=sentence)
        return dspy.Prediction(reasoning_and_answer=result.reasoning_and_answer)


# Define DSPy signature for Intimacy of self-disclosure (enhanced prompt)
class IntimacyOfDisclosureSignature(dspy.Signature):
    __doc__ = ENHANCED_INTIMACY_PROMPT
    sentence: str = dspy.InputField(desc="The user message to classify")
    reasoning_and_answer: str = dspy.OutputField(
        desc="Brief reasoning followed by 'Answer: Peripheral', 'Answer: Intermediate', 'Answer: Core', or 'Answer: N/A'"
    )


class IntimacyOfDisclosureClassifier(dspy.Module):
    def __init__(self):
        super().__init__()
        self.classify = dspy.Predict(IntimacyOfDisclosureSignature)

    def forward(self, sentence):
        result = self.classify(sentence=sentence)
        return dspy.Prediction(reasoning_and_answer=result.reasoning_and_answer)


# Define DSPy signature for Disclosure as confession (enhanced prompt)
class DisclosureAsConfessionSignature(dspy.Signature):
    __doc__ = ENHANCED_CONFESSION_PROMPT
    sentence: str = dspy.InputField(desc="The user message to classify")
    reasoning_and_answer: str = dspy.OutputField(
        desc="Brief reasoning followed by 'Answer: Yes, it's a confession' or 'Answer: No, it's not a confession'"
    )


class DisclosureAsConfessionClassifier(dspy.Module):
    def __init__(self):
        super().__init__()
        self.classify = dspy.Predict(DisclosureAsConfessionSignature)

    def forward(self, sentence):
        result = self.classify(sentence=sentence)
        return dspy.Prediction(reasoning_and_answer=result.reasoning_and_answer)


# Define DSPy signature for Temporality (Past / Now / Future)
class TemporalitySignature(dspy.Signature):
    __doc__ = ENHANCED_TEMPORALITY_PROMPT
    sentence: str = dspy.InputField(desc="The user message to classify")
    reasoning_and_answer: str = dspy.OutputField(
        desc="Brief reasoning followed by 'Answer: Past', 'Answer: Now', or 'Answer: Future'"
    )


class TemporalityClassifier(dspy.Module):
    def __init__(self):
        super().__init__()
        self.classify = dspy.Predict(TemporalitySignature)

    def forward(self, sentence):
        result = self.classify(sentence=sentence)
        return dspy.Prediction(reasoning_and_answer=result.reasoning_and_answer)


# Define DSPy signature for Topic (12-way communicative function)
class TopicSignature(dspy.Signature):
    __doc__ = TOPIC_CLASSIFICATION_PROMPT
    sentence: str = dspy.InputField(desc="The user message to classify")
    reasoning_and_answer: str = dspy.OutputField(
        desc="Brief reasoning followed by 'Answer: <topic>' where <topic> is one of the canonical topics"
    )


class TopicClassifier(dspy.Module):
    def __init__(self):
        super().__init__()
        self.classify = dspy.Predict(TopicSignature)

    def forward(self, sentence):
        result = self.classify(sentence=sentence)
        return dspy.Prediction(reasoning_and_answer=result.reasoning_and_answer)


# Define DSPy signature for Theme (holistic 5-dimension annotation used as a
# cross-check classifier — here we expose it as a single-label scheme that
# returns the Level-of-disclosure answer, since the theme prompt covers all 5
# dimensions with Level first.)
class ThemeSignature(dspy.Signature):
    __doc__ = THEME_CLASSIFICATION_PROMPT
    sentence: str = dspy.InputField(desc="The user message to classify")
    reasoning_and_answer: str = dspy.OutputField(
        desc="Brief reasoning followed by 'Answer: High', 'Answer: Low', or 'Answer: No'"
    )


class ThemeClassifier(dspy.Module):
    def __init__(self):
        super().__init__()
        self.classify = dspy.Predict(ThemeSignature)

    def forward(self, sentence):
        result = self.classify(sentence=sentence)
        return dspy.Prediction(reasoning_and_answer=result.reasoning_and_answer)


# Map scheme names to their classifiers
SCHEME_CLASSIFIERS = {
    "Level of disclosure": LevelOfDisclosureClassifier,
    "Depth of disclosure": DepthOfDisclosureClassifier,
    "Intimacy of self-disclosure": IntimacyOfDisclosureClassifier,
    "Disclosure as confession": DisclosureAsConfessionClassifier,
    "Temporality": TemporalityClassifier,
    "Topic": TopicClassifier,
    "Theme": ThemeClassifier,
}

# Some schemes are evaluated against a different GT field than their own name.
# Theme is a holistic 5-dimension prompt whose primary output is Level of
# disclosure, so its predictions are compared against Level GT.
SCHEME_GT_KEY = {
    "Theme": "Level of disclosure",
}


def _extract_gt_labels(item: dict) -> Dict[str, str]:
    """Return a merged ground-truth label dict for a single item.

    The agreed/fiona/chang JSON files store `topic` and `topic_category` at the
    top level of each item (not inside `labels`). We lift them into the label
    dict under the canonical scheme names so the evaluator can pick them up
    uniformly.
    """
    gt = dict(item.get("labels", {}))
    topic = (item.get("topic") or "").strip()
    if topic:
        gt["Topic"] = topic
    topic_cat = (item.get("topic_category") or "").strip()
    if topic_cat:
        gt["Topic thematic category"] = topic_cat
    return gt


def load_ground_truth(cfg: EvalConfig) -> List[dict]:
    with open(cfg.json_path, "r", encoding="utf-8") as f:
        payload = json.load(f)
    items = payload.get("items", [])
    return items[: cfg.n_rows] if cfg.n_rows else items


def _process_item(
    item: dict,
    index: int,
    scheme_name: str,
    classifier: dspy.Module,
) -> Tuple[dict, Tuple[str, str, str] | None]:
    """Process a single item for a specific scheme."""
    sentence = item.get("sentence", "")
    gt_labels: Dict[str, str] = _extract_gt_labels(item)

    if not sentence or not gt_labels:
        return {
            "index": index,
            "sentence": sentence,
            "ground_truth": gt_labels,
            "prediction": None,
            "error": "Missing sentence or labels",
        }, None

    try:
        # Use DSPy classifier
        result = classifier(sentence=sentence)

        raw_response = result.reasoning_and_answer.strip()
        # Theme prompt outputs Level-of-disclosure labels (High/Low/No), so
        # parse against that label set.
        parse_scheme = SCHEME_GT_KEY.get(scheme_name, scheme_name)
        pred_level = parse_answer(raw_response, parse_scheme)

        gt_key = SCHEME_GT_KEY.get(scheme_name, scheme_name)
        gt_level = gt_labels.get(gt_key, "")

        # Build result
        result_dict = {
            "index": index,
            "sentence": sentence,
            "scheme": scheme_name,
            "ground_truth": {gt_key: gt_level},
            "prediction": {
                "scheme": scheme_name,
                "level": pred_level,
                "reasoning": raw_response,
                "confidence": None,  # DSPy doesn't return confidence by default
            },
        }

        return result_dict, (scheme_name, gt_level, pred_level)
        
    except Exception as exc:
        return {
            "index": index,
            "sentence": sentence,
            "scheme": scheme_name,
            "ground_truth": gt_labels,
            "prediction": None,
            "error": str(exc),
        }, None


def evaluate_samples(samples: List[dict], cfg: EvalConfig) -> Tuple[Dict[str, dict], dict, List[dict]]:
    """Evaluate all samples using the enhanced prompt."""
    
    # scheme -> list[(y_true, y_pred)]
    scheme_pairs: Dict[str, List[Tuple[str, str]]] = {}
    results: List[dict] = []

    write_lock = threading.Lock()
    
    # Determine which schemes to evaluate
    if cfg.scheme:
        schemes_to_eval = [cfg.scheme] if cfg.scheme in SCHEME_CLASSIFIERS else []
        if not schemes_to_eval:
            print(f"Warning: Scheme '{cfg.scheme}' not available. Available: {list(SCHEME_CLASSIFIERS.keys())}")
            return {}, {"n_samples": len(samples), "n_evaluated_sentences": 0, "per_scheme_counts": {}}, []
    else:
        schemes_to_eval = list(SCHEME_CLASSIFIERS.keys())
    
    # Initialize classifiers
    classifiers = {scheme: SCHEME_CLASSIFIERS[scheme]() for scheme in schemes_to_eval}
    
    with ThreadPoolExecutor(max_workers=cfg.max_workers) as executor:
        futures = {}
        
        for idx, item in enumerate(samples, start=1):
            gt_labels: Dict[str, str] = _extract_gt_labels(item)

            for scheme_name in schemes_to_eval:
                # Only evaluate if ground truth exists for this scheme
                # (schemes may map to a different GT key via SCHEME_GT_KEY)
                gt_key = SCHEME_GT_KEY.get(scheme_name, scheme_name)
                if gt_key not in gt_labels:
                    continue
                
                classifier = classifiers[scheme_name]
                futures[
                    executor.submit(_process_item, item, idx, scheme_name, classifier)
                ] = idx

        for future in tqdm(as_completed(futures), total=len(futures), desc="Evaluating", unit="sample"):
            result, update = future.result()
            with write_lock:
                results.append(result)
                if update:
                    scheme, gt_level, pred_level = update
                    scheme_pairs.setdefault(scheme, []).append((gt_level, pred_level))
                _write_partial(cfg.out_path, results, scheme_pairs, len(samples))

    # Compute metrics
    metrics: Dict[str, dict] = {}
    counts: Dict[str, int] = {}

    for scheme, pairs in scheme_pairs.items():
        y_true = [gt for gt, _ in pairs]
        y_pred = [pred for _, pred in pairs]
        counts[scheme] = len(y_true)
        metrics[scheme] = compute_absolute_metrics(y_true=y_true, y_pred=y_pred)

    stats = {
        "n_samples": len(samples),
        "n_evaluated_sentences": sum(len(v) for v in scheme_pairs.values()),
        "per_scheme_counts": counts,
    }

    return metrics, stats, results


def main(dataset: str = "fiona", n_rows: Optional[int] = None, max_workers: int = 10, scheme: Optional[str] = None) -> None:
    cfg = EvalConfig(dataset=dataset, n_rows=n_rows, max_workers=max_workers, scheme=scheme)
    
    print("="*80)
    print("SELF-DISCLOSURE EVALUATION (Enhanced GEPA-Optimized Prompt)")
    print("="*80)
    print(f"Dataset: {cfg.dataset}")
    print(f"Input: {cfg.json_path}")
    print(f"Output: {cfg.out_path}")
    print(f"Scheme: {cfg.scheme if cfg.scheme else 'All available schemes'}")
    print(f"Processing {'all' if cfg.n_rows is None else cfg.n_rows} samples...")
    print(f"Available schemes: {list(SCHEME_CLASSIFIERS.keys())}")
    print("="*80 + "\n")
    
    samples = load_ground_truth(cfg)
    metrics, stats, results = evaluate_samples(samples, cfg)

    # Create results directory if it doesn't exist
    os.makedirs(os.path.dirname(cfg.out_path), exist_ok=True)
    
    with open(cfg.out_path, "w", encoding="utf-8") as f:
        json.dump(
            {
                "stats": stats,
                "metrics": metrics,
                "results": results,
            },
            f,
            ensure_ascii=False,
            indent=2,
        )

    print("\n=== Stats ===")
    print(json.dumps(stats, indent=2))
    print("\n=== Metrics (per scheme) ===")
    print_metrics_table(metrics)
    print(f"\nSaved results to: {cfg.out_path}")


def compute_absolute_metrics(y_true: List[str], y_pred: List[str]) -> Dict[str, float]:
    """Compute accuracy and per-class precision, recall, F1 for multi-class classification.
    
    For imbalanced datasets, use macro-averaged metrics which give equal weight to each class.
    Micro-averaged metrics give equal weight to each sample (same as accuracy).
    """
    assert len(y_true) == len(y_pred)
    
    # Overall accuracy
    accuracy = sum(yt == yp for yt, yp in zip(y_true, y_pred)) / len(y_true) if y_true else 0.0
    
    # Get all unique classes
    all_classes = sorted(set(y_true) | set(y_pred))
    
    # Per-class metrics
    per_class_metrics = {}
    class_precisions = []
    class_recalls = []
    class_f1s = []
    class_supports = []
    
    for cls in all_classes:
        # True Positives: predicted as cls and actually cls
        tp = sum((yp == cls and yt == cls) for yt, yp in zip(y_true, y_pred))
        
        # False Positives: predicted as cls but actually not cls
        fp = sum((yp == cls and yt != cls) for yt, yp in zip(y_true, y_pred))
        
        # False Negatives: predicted as not cls but actually cls
        fn = sum((yp != cls and yt == cls) for yt, yp in zip(y_true, y_pred))
        
        # True Negatives: predicted as not cls and actually not cls
        tn = sum((yp != cls and yt != cls) for yt, yp in zip(y_true, y_pred))
        
        # Support: number of true instances of this class
        support = sum(yt == cls for yt in y_true)
        
        # Precision: of all predicted as cls, how many were correct
        precision = tp / (tp + fp) if (tp + fp) > 0 else 0.0
        
        # Recall: of all actual cls, how many did we find
        recall = tp / (tp + fn) if (tp + fn) > 0 else 0.0
        
        # F1: harmonic mean of precision and recall
        f1 = (2 * precision * recall / (precision + recall)) if (precision + recall) > 0 else 0.0
        
        per_class_metrics[cls] = {
            "precision": precision,
            "recall": recall,
            "f1": f1,
            "support": support,
            "tp": tp,
            "fp": fp,
            "fn": fn,
            "tn": tn,
        }
        
        # Collect for averaging (only if class has support in ground truth)
        if support > 0:
            class_precisions.append(precision)
            class_recalls.append(recall)
            class_f1s.append(f1)
            class_supports.append(support)
    
    # Macro-averaged metrics (unweighted mean across classes)
    # Good for imbalanced datasets - treats all classes equally
    macro_precision = sum(class_precisions) / len(class_precisions) if class_precisions else 0.0
    macro_recall = sum(class_recalls) / len(class_recalls) if class_recalls else 0.0
    macro_f1 = sum(class_f1s) / len(class_f1s) if class_f1s else 0.0
    
    # Weighted-averaged metrics (weighted by support)
    # Accounts for class imbalance by weighting by number of true instances
    total_support = sum(class_supports)
    weighted_precision = sum(p * s for p, s in zip(class_precisions, class_supports)) / total_support if total_support > 0 else 0.0
    weighted_recall = sum(r * s for r, s in zip(class_recalls, class_supports)) / total_support if total_support > 0 else 0.0
    weighted_f1 = sum(f * s for f, s in zip(class_f1s, class_supports)) / total_support if total_support > 0 else 0.0
    
    # Micro-averaged metrics (aggregate TP, FP, FN across all classes)
    # Equivalent to accuracy for multi-class classification
    total_tp = sum(m["tp"] for m in per_class_metrics.values())
    total_fp = sum(m["fp"] for m in per_class_metrics.values())
    total_fn = sum(m["fn"] for m in per_class_metrics.values())
    
    micro_precision = total_tp / (total_tp + total_fp) if (total_tp + total_fp) > 0 else 0.0
    micro_recall = total_tp / (total_tp + total_fn) if (total_tp + total_fn) > 0 else 0.0
    micro_f1 = (2 * micro_precision * micro_recall / (micro_precision + micro_recall)) if (micro_precision + micro_recall) > 0 else 0.0

    return {
        "accuracy": accuracy,
        
        # Macro-averaged (best for imbalanced datasets)
        "macro_precision": macro_precision,
        "macro_recall": macro_recall,
        "macro_f1": macro_f1,
        
        # Weighted-averaged (accounts for class imbalance)
        "weighted_precision": weighted_precision,
        "weighted_recall": weighted_recall,
        "weighted_f1": weighted_f1,
        
        # Micro-averaged (equivalent to accuracy)
        "micro_precision": micro_precision,
        "micro_recall": micro_recall,
        "micro_f1": micro_f1,
        
        # Per-class metrics
        "per_class": per_class_metrics,
        
        # Summary stats
        "n": len(y_true),
        "n_classes": len(all_classes),
        "classes": all_classes,
    }


def print_metrics_table(metrics: Dict[str, dict]) -> None:
    """Print metrics in a nice table format."""

    # Overall metrics table
    print("\n--- OVERALL METRICS (Macro-averaged - best for imbalanced data) ---")
    if not metrics:
        print("(no metrics — no ground-truth labels matched the selected schemes)")
        return

    headers = ["scheme", "accuracy", "macro_p", "macro_r", "macro_f1", "n_classes", "n"]
    rows = []
    for scheme, m in sorted(metrics.items()):
        rows.append(
            [
                scheme,
                f"{m['accuracy']:.3f}",
                f"{m['macro_precision']:.3f}",
                f"{m['macro_recall']:.3f}",
                f"{m['macro_f1']:.3f}",
                str(m['n_classes']),
                str(m["n"]),
            ]
        )

    col_widths = [max([len(h)] + [len(r[i]) for r in rows]) for i, h in enumerate(headers)]
    header_line = " | ".join(h.ljust(col_widths[i]) for i, h in enumerate(headers))
    sep_line = "-+-".join("-" * col_widths[i] for i in range(len(headers)))
    print(header_line)
    print(sep_line)
    for row in rows:
        print(" | ".join(row[i].ljust(col_widths[i]) for i in range(len(headers))))
    
    # Per-class metrics for each scheme
    for scheme, m in sorted(metrics.items()):
        print(f"\n--- PER-CLASS METRICS: {scheme} ---")
        per_class = m.get("per_class", {})
        
        if not per_class:
            print("  No per-class metrics available")
            continue
        
        headers = ["class", "precision", "recall", "f1", "support", "tp", "fp", "fn"]
        rows = []
        
        for cls in sorted(per_class.keys()):
            cls_metrics = per_class[cls]
            rows.append([
                cls,
                f"{cls_metrics['precision']:.3f}",
                f"{cls_metrics['recall']:.3f}",
                f"{cls_metrics['f1']:.3f}",
                str(cls_metrics['support']),
                str(cls_metrics['tp']),
                str(cls_metrics['fp']),
                str(cls_metrics['fn']),
            ])
        
        col_widths = [max([len(h)] + [len(r[i]) for r in rows]) for i, h in enumerate(headers)]
        header_line = " | ".join(h.ljust(col_widths[i]) for i, h in enumerate(headers))
        sep_line = "-+-".join("-" * col_widths[i] for i in range(len(headers)))
        print(header_line)
        print(sep_line)
        for row in rows:
            print(" | ".join(row[i].ljust(col_widths[i]) for i in range(len(headers))))

        # Print weighted and micro averages
        print(f"\nWeighted avg: P={m['weighted_precision']:.3f}, R={m['weighted_recall']:.3f}, F1={m['weighted_f1']:.3f}")
        print(f"Micro avg:    P={m['micro_precision']:.3f}, R={m['micro_recall']:.3f}, F1={m['micro_f1']:.3f}")


def _write_partial(out_path: str, results: List[dict], scheme_pairs: Dict[str, List[Tuple[str, str]]], total: int) -> None:
    """Write partial results during processing."""
    stats = {
        "n_samples": total,
        "n_processed": len(results),
        "per_scheme_counts": {scheme: len(pairs) for scheme, pairs in scheme_pairs.items()},
    }
    ordered_results = sorted(results, key=lambda r: r.get("index", 0))
    
    # Create results directory if it doesn't exist
    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(
            {
                "stats": stats,
                "metrics": None,
                "results": ordered_results,
            },
            f,
            ensure_ascii=False,
            indent=2,
        )


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Evaluate self-disclosure annotations with enhanced GEPA prompt")
    parser.add_argument(
        "--dataset",
        type=str,
        default="agreed",
        choices=["fiona", "chang", "agreed"],
        help="Dataset to evaluate (default: agreed). 'agreed' uses only sentences where Fiona and Chang agree.",
    )
    parser.add_argument(
        "--n_rows",
        type=int,
        default=None,
        help="Number of samples to process (default: all)",
    )
    parser.add_argument(
        "--max_workers",
        type=int,
        default=10,
        help="Number of parallel workers (default: 10)",
    )
    parser.add_argument(
        "--scheme",
        type=str,
        default=None,
        help="Specific scheme to evaluate (default: all available schemes)",
    )
    
    args = parser.parse_args()
    main(dataset=args.dataset, n_rows=args.n_rows, max_workers=args.max_workers, scheme=args.scheme)
