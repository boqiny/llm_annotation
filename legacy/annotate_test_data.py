"""Annotate test data using GPT-5.2 for all self-disclosure schemes.

Usage:
    # Annotate all test messages:
    python3 annotate_test_data.py
"""
from __future__ import annotations

import argparse
import json
import os
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from typing import Dict, List, Optional

from tqdm import tqdm

from llm_annotator import LLMAnnotator
from self_disclosure_annotation import build_messages
from codebook import CODEBOOK, Codebook


@dataclass(frozen=True)
class AnnotateConfig:
    """Configuration for annotating test data with self-disclosure schemes."""
    model: str = "gpt-5.2"  # Model to use for annotation
    n_rows: Optional[int] = None  # Set to None to process all items
    max_workers: int = 10  # Parallel processing workers
    json_path: str = "./data/test/cleaned/test_data.json"
    out_path: str = "./results/test_data_annotations.json"


# All schemes to annotate
ALL_SCHEMES = [
    "Level of disclosure",
    "Depth of disclosure",
    "Intimacy of self-disclosure",
    "Disclosure as confession",
]


def load_test_data(cfg: AnnotateConfig) -> List[dict]:
    """Load test data from JSON file."""
    with open(cfg.json_path, "r", encoding="utf-8") as f:
        payload = json.load(f)
    items = payload.get("items", [])
    return items[: cfg.n_rows] if cfg.n_rows else items


def _build_scheme_codebook(scheme_name: str) -> Codebook:
    """Build a codebook containing only the specified scheme."""
    for scheme in CODEBOOK.schemes:
        if scheme.name == scheme_name:
            return Codebook(title=CODEBOOK.title, schemes=[scheme])
    raise ValueError(f"Unknown scheme in codebook: {scheme_name}")


def _process_item(
    item: dict,
    index: int,
    scheme_name: str,
    scheme_codebook: Codebook,
    model: str,
) -> dict:
    """Process a single item with a single scheme."""
    sentence = item.get("sentence", "")
    if not sentence:
        return {
            "index": index,
            "user_id": item.get("user_id"),
            "message_index": item.get("message_index"),
            "sentence": sentence,
            "scheme": scheme_name,
            "prediction": None,
            "error": "Missing sentence",
        }

    annotator = LLMAnnotator(codebook=CODEBOOK, model=model)
    prompt = build_messages(codebook=scheme_codebook, sentence=sentence)
    
    try:
        out = annotator.annotate(prompt)
    except ValueError as exc:
        return {
            "index": index,
            "user_id": item.get("user_id"),
            "message_index": item.get("message_index"),
            "sentence": sentence,
            "scheme": scheme_name,
            "prediction": None,
            "error": str(exc),
        }

    pred_scheme = out.get("scheme", "")
    pred_level = out.get("level", "")
    pred_confidence = out.get("confidence", None)

    result = {
        "index": index,
        "user_id": item.get("user_id"),
        "message_index": item.get("message_index"),
        "sentence": sentence,
        "scheme": scheme_name,
        "prediction": {
            "scheme": pred_scheme,
            "level": pred_level,
            "confidence": pred_confidence,
        },
    }
    return result


def annotate_samples(samples: List[dict], cfg: AnnotateConfig) -> List[dict]:
    """Annotate all samples with all schemes."""
    results: List[dict] = []
    write_lock = threading.Lock()
    
    # Pre-build scheme codebooks
    scheme_codebooks = {
        scheme: _build_scheme_codebook(scheme)
        for scheme in ALL_SCHEMES
    }
    
    with ThreadPoolExecutor(max_workers=cfg.max_workers) as executor:
        futures = {}
        
        # Submit all tasks
        for idx, item in enumerate(samples, start=1):
            for scheme_name in ALL_SCHEMES:
                scheme_codebook = scheme_codebooks[scheme_name]
                future = executor.submit(
                    _process_item, 
                    item, 
                    idx, 
                    scheme_name, 
                    scheme_codebook,
                    cfg.model
                )
                futures[future] = (idx, scheme_name)
        
        # Collect results with progress bar
        total_tasks = len(samples) * len(ALL_SCHEMES)
        for future in tqdm(
            as_completed(futures), 
            total=total_tasks, 
            desc="Annotating", 
            unit="annotation"
        ):
            result = future.result()
            with write_lock:
                results.append(result)
                _write_partial(cfg.out_path, results, len(samples))
    
    return results


def _write_partial(out_path: str, results: List[dict], total_samples: int) -> None:
    """Write partial results to file (for progress tracking)."""
    stats = {
        "n_samples": total_samples,
        "n_annotations_completed": len(results),
        "n_expected": total_samples * len(ALL_SCHEMES),
    }
    ordered_results = sorted(results, key=lambda r: (r.get("index", 0), r.get("scheme", "")))
    
    # Create results directory if it doesn't exist
    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(
            {
                "stats": stats,
                "results": ordered_results,
            },
            f,
            ensure_ascii=False,
            indent=2,
        )


def aggregate_by_sentence(results: List[dict]) -> List[dict]:
    """Aggregate annotations by sentence (all schemes for each sentence)."""
    sentence_map: Dict[int, dict] = {}
    
    for result in results:
        idx = result.get("index")
        scheme = result.get("scheme")
        prediction = result.get("prediction")
        
        if idx not in sentence_map:
            sentence_map[idx] = {
                "index": idx,
                "user_id": result.get("user_id"),
                "message_index": result.get("message_index"),
                "sentence": result.get("sentence"),
                "annotations": {}
            }
        
        if prediction and prediction.get("level"):
            sentence_map[idx]["annotations"][scheme] = prediction.get("level")
    
    return sorted(sentence_map.values(), key=lambda x: x["index"])


def main(model: str = "gpt-5.2", n_rows: Optional[int] = None, max_workers: int = 10) -> None:
    cfg = AnnotateConfig(model=model, n_rows=n_rows, max_workers=max_workers)
    
    print(f"Model: {cfg.model}")
    print(f"Input: {cfg.json_path}")
    print(f"Output: {cfg.out_path}")
    print(f"Processing {'all' if cfg.n_rows is None else cfg.n_rows} samples...")
    print(f"Schemes: {', '.join(ALL_SCHEMES)}\n")
    
    samples = load_test_data(cfg)
    results = annotate_samples(samples, cfg)
    
    # Aggregate results by sentence
    aggregated = aggregate_by_sentence(results)
    
    # Create results directory if it doesn't exist
    os.makedirs(os.path.dirname(cfg.out_path), exist_ok=True)
    
    # Final output
    stats = {
        "model": cfg.model,
        "n_samples": len(samples),
        "n_schemes": len(ALL_SCHEMES),
        "n_total_annotations": len(results),
        "schemes": ALL_SCHEMES,
    }
    
    with open(cfg.out_path, "w", encoding="utf-8") as f:
        json.dump(
            {
                "stats": stats,
                "results": aggregated,
            },
            f,
            ensure_ascii=False,
            indent=2,
        )
    
    print("\n=== Stats ===")
    print(json.dumps(stats, indent=2))
    print(f"\nSaved results to: {cfg.out_path}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Annotate test data with self-disclosure schemes")
    parser.add_argument(
        "--model",
        type=str,
        default="gpt-5.2",
        help="Model to use for annotation (default: gpt-5.2)",
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
    main(model=args.model, n_rows=args.n_rows, max_workers=args.max_workers)
