"""Evaluate self-disclosure annotations using GPT-4o mini.

Usage:
    # Evaluate Fiona's dataset (default):
    python3 eval_self_disclosure_from_json.py
    
    # Evaluate Chang's dataset:
    python3 eval_self_disclosure_from_json.py --dataset chang
    
    # Evaluate agreed dataset (only sentences where Fiona and Chang agree):
    python3 eval_self_disclosure_from_json.py --dataset agreed
    
    # Evaluate subset:
    python3 eval_self_disclosure_from_json.py --dataset fiona --n_rows 100
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

from llm_annotator import LLMAnnotator
from self_disclosure_annotation import build_messages
from codebook import CODEBOOK, Codebook


@dataclass(frozen=True)
class EvalConfig:
    """Configuration for evaluating self-disclosure annotations.
    
    For each item in the ground truth JSON:
    - Extracts the sentence and ground truth labels
    - For each scheme (Level of disclosure, Depth of disclosure, 
      Intimacy of self-disclosure, Disclosure as confession):
        * Creates a single-scheme codebook
        * Sends to GPT-4o mini for annotation
        * Compares prediction with ground truth
    """
    dataset: str = "fiona"  # Options: "fiona", "chang", or "agreed"
    n_rows: int = None  # Set to None to process all items
    max_workers: int = 10  # Parallel processing workers
    
    @property
    def json_path(self) -> str:
        return f"./data/cleaned/{self.dataset}_self_disclosure_ground_truth.json"
    
    @property
    def out_path(self) -> str:
        return f"./results/{self.dataset}_self_disclosure_eval_results.json"


def load_ground_truth(cfg: EvalConfig) -> List[dict]:
    with open(cfg.json_path, "r", encoding="utf-8") as f:
        payload = json.load(f)
    items = payload.get("items", [])
    return items[: cfg.n_rows] if cfg.n_rows else items


GT_SCHEME_TO_CODEBOOK = {
    "Level of disclosure": "Level of disclosure",
    "Depth of disclosure": "Depth of disclosure",
    "Intimacy of self-disclosure": "Intimacy of self-disclosure",
    "Disclosure as confession": "Disclosure as confession",
}


def _build_scheme_codebook(scheme_name: str) -> Codebook:
    for scheme in CODEBOOK.schemes:
        if scheme.name == scheme_name:
            return Codebook(title=CODEBOOK.title, schemes=[scheme])
    raise ValueError(f"Unknown scheme in codebook: {scheme_name}")


def _process_item(
    item: dict,
    index: int,
    scheme_name: str,
    scheme_codebook: Codebook,
) -> Tuple[dict, Tuple[str, str, str] | None]:
    sentence = item.get("sentence", "")
    gt_labels: Dict[str, str] = item.get("labels", {})
    if not sentence or not gt_labels:
        return {
            "index": index,
            "sentence": sentence,
            "ground_truth": gt_labels,
            "prediction": None,
            "error": "Missing sentence or labels",
        }, None

    annotator = LLMAnnotator(codebook=CODEBOOK)
    prompt = build_messages(codebook=scheme_codebook, sentence=sentence)
    # print(f"\n{'='*80}\nPrompt for [{scheme_name}] - Item {index}:\n{json.dumps(prompt, indent=2)}\n{'='*80}\n")
    try:
        out = annotator.annotate(prompt)
        # print(f"Result: {json.dumps(out, indent=2)}\n")
    except ValueError as exc:
        return {
            "index": index,
            "sentence": sentence,
            "scheme": scheme_name,
            "ground_truth": gt_labels,
            "prediction": None,
            "error": str(exc),
        }, None

    pred_scheme = out.get("scheme", "")
    pred_level = out.get("level", "")
    pred_confidence = out.get("confidence", None)

    result = {
        "index": index,
        "sentence": sentence,
        "scheme": scheme_name,
        "ground_truth": {scheme_name: gt_labels.get(scheme_name, "")},
        "prediction": {
            "scheme": pred_scheme,
            "level": pred_level,
            "confidence": pred_confidence,
        },
    }
    gt_level = gt_labels.get(scheme_name, "")
    return result, (scheme_name, gt_level, pred_level)


def evaluate_samples(samples: List[dict], cfg: EvalConfig) -> Tuple[Dict[str, dict], dict, List[dict]]:

    # scheme -> list[(y_true, y_pred)]
    scheme_pairs: Dict[str, List[Tuple[str, str]]] = {}
    results: List[dict] = []

    write_lock = threading.Lock()
    scheme_codebooks = {
        gt_scheme: _build_scheme_codebook(codebook_scheme)
        for gt_scheme, codebook_scheme in GT_SCHEME_TO_CODEBOOK.items()
    }
    with ThreadPoolExecutor(max_workers=cfg.max_workers) as executor:
        futures = {}
        for idx, item in enumerate(samples, start=1):
            gt_labels: Dict[str, str] = item.get("labels", {})
            for gt_scheme in gt_labels.keys():
                codebook_scheme = GT_SCHEME_TO_CODEBOOK.get(gt_scheme)
                if not codebook_scheme:
                    results.append(
                        {
                            "index": idx,
                            "sentence": item.get("sentence", ""),
                            "scheme": gt_scheme,
                            "ground_truth": gt_labels,
                            "prediction": None,
                            "error": f"Unknown GT scheme: {gt_scheme}",
                        }
                    )
                    continue
                scheme_codebook = scheme_codebooks[gt_scheme]
                futures[
                    executor.submit(_process_item, item, idx, gt_scheme, scheme_codebook)
                ] = idx

        for future in tqdm(as_completed(futures), total=len(futures), desc="Evaluating", unit="sample"):
            result, update = future.result()
            with write_lock:
                results.append(result)
                if update:
                    scheme, gt_level, pred_level = update
                    scheme_pairs.setdefault(scheme, []).append((gt_level, pred_level))
                _write_partial(cfg.out_path, results, scheme_pairs, len(samples))

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


def main(dataset: str = "fiona", n_rows: Optional[int] = None, max_workers: int = 10) -> None:
    cfg = EvalConfig(dataset=dataset, n_rows=n_rows, max_workers=max_workers)
    
    print(f"Dataset: {cfg.dataset}")
    print(f"Input: {cfg.json_path}")
    print(f"Output: {cfg.out_path}")
    print(f"Processing {'all' if cfg.n_rows is None else cfg.n_rows} samples...\n")
    
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
    assert len(y_true) == len(y_pred)

    tp = sum(yt == yp for yt, yp in zip(y_true, y_pred))
    fp = sum(yt != yp for yt, yp in zip(y_true, y_pred))
    fn = fp

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


def print_metrics_table(metrics: Dict[str, dict]) -> None:
    headers = ["scheme", "accuracy", "n"]
    rows = []
    for scheme, m in sorted(metrics.items()):
        rows.append(
            [
                scheme,
                f"{m['accuracy']:.3f}",
                str(m["n"]),
            ]
        )

    col_widths = [max(len(h), *(len(r[i]) for r in rows)) for i, h in enumerate(headers)]
    header_line = " | ".join(h.ljust(col_widths[i]) for i, h in enumerate(headers))
    sep_line = "-+-".join("-" * col_widths[i] for i in range(len(headers)))
    print(header_line)
    print(sep_line)
    for row in rows:
        print(" | ".join(row[i].ljust(col_widths[i]) for i in range(len(headers))))


def _write_partial(out_path: str, results: List[dict], scheme_pairs: Dict[str, List[Tuple[str, str]]], total: int) -> None:
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
    parser = argparse.ArgumentParser(description="Evaluate self-disclosure annotations")
    parser.add_argument(
        "--dataset",
        type=str,
        default="fiona",
        choices=["fiona", "chang", "agreed"],
        help="Dataset to evaluate (default: fiona). 'agreed' uses only sentences where Fiona and Chang agree.",
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
    
    args = parser.parse_args()
    main(dataset=args.dataset, n_rows=args.n_rows, max_workers=args.max_workers)
