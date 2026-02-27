"""Annotate test data using two-stage approach with enhanced GEPA-optimized prompts.

Stage 1: Determine if message contains self-disclosure (is_disclosure: Yes/No)
Stage 2: If Yes, classify using 4 detailed schemes

Usage:
    # Annotate all test messages:
    python3 annotate_test_data.py
    
    # Annotate specific number of samples:
    python3 annotate_test_data.py --n_rows 50
    
    # Use more workers for faster processing:
    python3 annotate_test_data.py --max_workers 20
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
import dspy
from dotenv import load_dotenv

from prompts.is_disclosure_prompt import IS_DISCLOSURE_PROMPT
from prompts.self_disclosure_prompt import ENHANCED_SYSTEM_PROMPT
from prompts.depth_disclosure_prompt import ENHANCED_DEPTH_PROMPT
from prompts.intimacy_disclosure_prompt import ENHANCED_INTIMACY_PROMPT
from prompts.confession_disclosure_prompt import ENHANCED_CONFESSION_PROMPT

load_dotenv()
# Configure DSPy
dspy.configure(lm=dspy.LM("openai/gpt-5.2"))


@dataclass(frozen=True)
class AnnotateConfig:
    """Configuration for annotating test data with self-disclosure schemes."""
    n_rows: Optional[int] = None  # Set to None to process all items
    max_workers: int = 10  # Parallel processing workers
    json_path: str = "./data/test/cleaned/test_data.json"
    out_path: str = "./results/test_data_annotations.json"


# Define DSPy signature for Stage 1: Is Disclosure?
class IsDisclosureSignature(dspy.Signature):
    __doc__ = IS_DISCLOSURE_PROMPT
    sentence: str = dspy.InputField(desc="The user message to check")
    is_disclosure: str = dspy.OutputField(desc="Yes or No")


class IsDisclosureClassifier(dspy.Module):
    def __init__(self):
        super().__init__()
        self.classify = dspy.Predict(IsDisclosureSignature)
    
    def forward(self, sentence):
        result = self.classify(sentence=sentence)
        return dspy.Prediction(is_disclosure=result.is_disclosure)


# Define DSPy signatures and classifiers for Stage 2: Detailed classification

class LevelOfDisclosureSignature(dspy.Signature):
    __doc__ = ENHANCED_SYSTEM_PROMPT
    sentence: str = dspy.InputField(desc="The user message to classify")
    level: str = dspy.OutputField(desc="The disclosure level: High, Low, or No")


class LevelOfDisclosureClassifier(dspy.Module):
    def __init__(self):
        super().__init__()
        self.classify = dspy.Predict(LevelOfDisclosureSignature)
    
    def forward(self, sentence):
        result = self.classify(sentence=sentence)
        return dspy.Prediction(level=result.level)


class DepthOfDisclosureSignature(dspy.Signature):
    __doc__ = ENHANCED_DEPTH_PROMPT
    sentence: str = dspy.InputField(desc="The user message to classify")
    depth: str = dspy.OutputField(desc="The depth level: Peripheral layer, Intermediate layer, or Central layer")


class DepthOfDisclosureClassifier(dspy.Module):
    def __init__(self):
        super().__init__()
        self.classify = dspy.Predict(DepthOfDisclosureSignature)
    
    def forward(self, sentence):
        result = self.classify(sentence=sentence)
        return dspy.Prediction(depth=result.depth)


class IntimacyOfDisclosureSignature(dspy.Signature):
    __doc__ = ENHANCED_INTIMACY_PROMPT
    sentence: str = dspy.InputField(desc="The user message to classify")
    intimacy: str = dspy.OutputField(desc="The intimacy level: Peripheral level, Intermediate level, or Core layer")


class IntimacyOfDisclosureClassifier(dspy.Module):
    def __init__(self):
        super().__init__()
        self.classify = dspy.Predict(IntimacyOfDisclosureSignature)
    
    def forward(self, sentence):
        result = self.classify(sentence=sentence)
        return dspy.Prediction(intimacy=result.intimacy)


class DisclosureAsConfessionSignature(dspy.Signature):
    __doc__ = ENHANCED_CONFESSION_PROMPT
    sentence: str = dspy.InputField(desc="The user message to classify")
    confession: str = dspy.OutputField(desc="The answer: Yes, it's a confession OR No, it's not a confession")


class DisclosureAsConfessionClassifier(dspy.Module):
    def __init__(self):
        super().__init__()
        self.classify = dspy.Predict(DisclosureAsConfessionSignature)
    
    def forward(self, sentence):
        result = self.classify(sentence=sentence)
        return dspy.Prediction(confession=result.confession)


# Initialize classifiers
IS_DISCLOSURE_CLASSIFIER = IsDisclosureClassifier()

DETAIL_CLASSIFIERS = {
    "Level of disclosure": LevelOfDisclosureClassifier(),
    "Depth of disclosure": DepthOfDisclosureClassifier(),
    "Intimacy of self-disclosure": IntimacyOfDisclosureClassifier(),
    "Disclosure as confession": DisclosureAsConfessionClassifier(),
}


def load_test_data(cfg: AnnotateConfig) -> List[dict]:
    """Load test data from JSON file."""
    with open(cfg.json_path, "r", encoding="utf-8") as f:
        payload = json.load(f)
    items = payload.get("items", [])
    return items[: cfg.n_rows] if cfg.n_rows else items


def _annotate_single_item(item: dict, index: int) -> dict:
    """
    Two-stage annotation for a single item:
    Stage 1: Check if it contains self-disclosure
    Stage 2: If yes, classify using all 4 detailed schemes
    """
    sentence = item.get("sentence", "")
    
    result = {
        "Index": index,
        "user_id": item.get("user_id"),
        "message_index": item.get("message_index"),
        "sentence": sentence,
    }
    
    if not sentence:
        result["error"] = "Missing sentence"
        return result
    
    try:
        # Stage 1: Is this self-disclosure?
        is_disclosure_result = IS_DISCLOSURE_CLASSIFIER(sentence=sentence)
        is_disclosure = is_disclosure_result.is_disclosure.strip()
        result["is_disclosure"] = is_disclosure
        
        # Stage 2: Only do detailed classification if it's self-disclosure
        if is_disclosure == "Yes":
            # Classify with all 4 detailed schemes
            for scheme_name, classifier in DETAIL_CLASSIFIERS.items():
                try:
                    detail_result = classifier(sentence=sentence)
                    
                    # Get the appropriate field based on classifier type
                    if scheme_name == "Level of disclosure":
                        label = detail_result.level.strip()
                    elif scheme_name == "Depth of disclosure":
                        label = detail_result.depth.strip()
                    elif scheme_name == "Intimacy of self-disclosure":
                        label = detail_result.intimacy.strip()
                    elif scheme_name == "Disclosure as confession":
                        label = detail_result.confession.strip()
                    else:
                        label = None
                    
                    # Convert "N/A" to null
                    if label == "N/A":
                        result[scheme_name] = None
                    else:
                        result[scheme_name] = label
                        
                except Exception as e:
                    result[f"{scheme_name}_error"] = str(e)
                    result[scheme_name] = None
        
        # If not self-disclosure, don't include the detailed schemes
        # (they won't be in the result dict)
        
    except Exception as e:
        result["error"] = f"Stage 1 error: {str(e)}"
    
    return result


def annotate_samples(samples: List[dict], cfg: AnnotateConfig) -> List[dict]:
    """Annotate all samples using two-stage approach."""
    results: List[dict] = []
    write_lock = threading.Lock()
    
    with ThreadPoolExecutor(max_workers=cfg.max_workers) as executor:
        futures = {}
        
        # Submit all tasks
        for idx, item in enumerate(samples, start=1):
            future = executor.submit(_annotate_single_item, item, idx)
            futures[future] = idx
        
        # Collect results with progress bar
        for future in tqdm(
            as_completed(futures), 
            total=len(samples), 
            desc="Annotating", 
            unit="message"
        ):
            result = future.result()
            with write_lock:
                results.append(result)
                _write_partial(cfg.out_path, results)
    
    return results


def _write_partial(out_path: str, results: List[dict]) -> None:
    """Write partial results to file (for progress tracking)."""
    # Sort by index
    ordered_results = sorted(results, key=lambda r: r.get("Index", 0))
    
    # Count stats
    n_disclosure = sum(1 for r in results if r.get("is_disclosure") == "Yes")
    n_no_disclosure = sum(1 for r in results if r.get("is_disclosure") == "No")
    
    stats = {
        "n_processed": len(results),
        "n_disclosure": n_disclosure,
        "n_no_disclosure": n_no_disclosure,
    }
    
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


def main(n_rows: Optional[int] = None, max_workers: int = 10) -> None:
    cfg = AnnotateConfig(n_rows=n_rows, max_workers=max_workers)
    
    print("="*80)
    print("TWO-STAGE TEST DATA ANNOTATION")
    print("="*80)
    print("Stage 1: Is self-disclosure? (Yes/No)")
    print("Stage 2: Detailed classification (4 schemes, only if Yes)")
    print("="*80)
    print(f"Model: gpt-5.2 (via DSPy)")
    print(f"Input: {cfg.json_path}")
    print(f"Output: {cfg.out_path}")
    print(f"Processing {'all' if cfg.n_rows is None else cfg.n_rows} samples...")
    print("="*80 + "\n")
    
    samples = load_test_data(cfg)
    results = annotate_samples(samples, cfg)
    
    # Sort results by index
    results = sorted(results, key=lambda r: r.get("Index", 0))
    
    # Calculate final stats
    n_disclosure = sum(1 for r in results if r.get("is_disclosure") == "Yes")
    n_no_disclosure = sum(1 for r in results if r.get("is_disclosure") == "No")
    n_errors = sum(1 for r in results if "error" in r)
    
    stats = {
        "model": "gpt-5.2",
        "n_samples": len(samples),
        "n_disclosure": n_disclosure,
        "n_no_disclosure": n_no_disclosure,
        "n_errors": n_errors,
        "disclosure_rate": f"{n_disclosure / len(samples) * 100:.1f}%" if samples else "0%",
    }
    
    # Create results directory if it doesn't exist
    os.makedirs(os.path.dirname(cfg.out_path), exist_ok=True)
    
    # Final output
    with open(cfg.out_path, "w", encoding="utf-8") as f:
        json.dump(
            {
                "stats": stats,
                "results": results,
            },
            f,
            ensure_ascii=False,
            indent=2,
        )
    
    print("\n=== Stats ===")
    print(json.dumps(stats, indent=2))
    print(f"\nSaved results to: {cfg.out_path}")
    
    # Show sample results
    print("\n=== Sample Results ===")
    for i, result in enumerate(results[:5], 1):
        print(f"\nSample {i}:")
        print(f"  Sentence: {result.get('sentence', '')[:60]}...")
        print(f"  Is disclosure: {result.get('is_disclosure', 'N/A')}")
        if result.get('is_disclosure') == 'Yes':
            level = result.get('Level of disclosure')
            depth = result.get('Depth of disclosure')
            intimacy = result.get('Intimacy of self-disclosure')
            confession = result.get('Disclosure as confession')
            print(f"  Level: {level if level is not None else 'null (N/A)'}")
            print(f"  Depth: {depth if depth is not None else 'null (N/A)'}")
            print(f"  Intimacy: {intimacy if intimacy is not None else 'null (N/A)'}")
            print(f"  Confession: {confession if confession is not None else 'null (N/A)'}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Two-stage annotation with enhanced GEPA-optimized prompts"
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
    main(n_rows=args.n_rows, max_workers=args.max_workers)
