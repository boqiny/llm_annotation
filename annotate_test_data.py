"""Annotate test data using two-stage approach with enhanced GEPA-optimized prompts.

Stage 1: Determine if message contains self-disclosure (is_disclosure: Yes/No)
Stage 2: If Yes, classify using 4 detailed schemes

Usage:
    # Annotate all test messages (default OpenAI model):
    python3 annotate_test_data.py

    # Use a Claude model:
    python3 annotate_test_data.py --dataset test_data_v2 --model claude-sonnet-4-5

    # Use a specific OpenAI model:
    python3 annotate_test_data.py --model gpt-4o

    # Full DSPy provider/model string also accepted:
    python3 annotate_test_data.py --model anthropic/claude-opus-4-5

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
from prompts.parser import parse_answer

load_dotenv()

_DEFAULT_MODEL = "gpt-5.2"


def resolve_model(model: str) -> str:
    """Return a fully-qualified DSPy provider/model string.

    If *model* already contains '/' it is used as-is.
    Otherwise the provider is inferred from the model name:
      - 'claude*'  → anthropic/
      - everything else → openai/
    """
    if "/" in model:
        return model
    if model.startswith("claude"):
        return f"anthropic/{model}"
    return f"openai/{model}"


@dataclass(frozen=True)
class AnnotateConfig:
    """Configuration for annotating test data with self-disclosure schemes."""
    n_rows: Optional[int] = None  # Set to None to process all items
    max_workers: int = 10  # Parallel processing workers
    model: str = _DEFAULT_MODEL  # Short model name or full provider/model string
    dataset: str = "test_data"  # Filename (without .json) in data/test/cleaned/
    json_path: str = "./data/test/cleaned/test_data.json"
    out_path: str = "./results/test_data_annotations.json"
    stage: int = 0  # 0 = both stages, 1 = stage 1 only, 2 = stage 2 only


# Define DSPy signature for Stage 1: Is Disclosure?
class IsDisclosureSignature(dspy.Signature):
    __doc__ = IS_DISCLOSURE_PROMPT
    sentence: str = dspy.InputField(desc="The user message to check")
    reasoning_and_answer: str = dspy.OutputField(
        desc="Brief reasoning followed by 'Answer: Yes' or 'Answer: No'"
    )


class IsDisclosureClassifier(dspy.Module):
    def __init__(self):
        super().__init__()
        self.classify = dspy.Predict(IsDisclosureSignature)

    def forward(self, sentence):
        result = self.classify(sentence=sentence)
        return dspy.Prediction(reasoning_and_answer=result.reasoning_and_answer)


# Define DSPy signatures and classifiers for Stage 2: Detailed classification

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


def _annotate_single_item(item: dict, index: int, stage: int = 0) -> dict:
    """
    Two-stage annotation for a single item:
    Stage 1: Check if it contains self-disclosure
    Stage 2: If yes, classify using all 4 detailed schemes
    stage: 0 = both, 1 = stage 1 only
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
        raw_stage1 = is_disclosure_result.reasoning_and_answer.strip()
        is_disclosure = parse_answer(raw_stage1, "is_disclosure")
        result["is_disclosure"] = is_disclosure
        result["is_disclosure_reasoning"] = raw_stage1

        # Stage 2: Only do detailed classification if it's self-disclosure
        # Skip stage 2 if running stage 1 only
        if is_disclosure == "Yes" and stage != 1:
            # Classify with all 4 detailed schemes
            for scheme_name, classifier in DETAIL_CLASSIFIERS.items():
                try:
                    detail_result = classifier(sentence=sentence)
                    raw = detail_result.reasoning_and_answer.strip()
                    label = parse_answer(raw, scheme_name)

                    result[f"{scheme_name}_reasoning"] = raw
                    # Convert "N/A" to null
                    result[scheme_name] = None if label == "N/A" else label

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
            future = executor.submit(_annotate_single_item, item, idx, cfg.stage)
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


def main(
    n_rows: Optional[int] = None,
    max_workers: int = 10,
    model: str = _DEFAULT_MODEL,
    dataset: str = "test_data",
    stage: int = 0,
) -> None:
    lm_string = resolve_model(model)
    dspy.configure(lm=dspy.LM(lm_string, max_tokens=128))

    cfg = AnnotateConfig(
        n_rows=n_rows,
        max_workers=max_workers,
        model=model,
        dataset=dataset,
        json_path=f"./data/test/cleaned/{dataset}.json",
        out_path=f"./results/{dataset}_annotations.json",
        stage=stage,
    )

    print("="*80)
    print("TWO-STAGE TEST DATA ANNOTATION")
    print("="*80)
    if stage == 1:
        print("Running Stage 1 ONLY: Is self-disclosure? (Yes/No)")
    else:
        print("Stage 1: Is self-disclosure? (Yes/No)")
        print("Stage 2: Detailed classification (4 schemes, only if Yes)")
    print("="*80)
    print(f"Model: {lm_string} (via DSPy)")
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
        "model": lm_string,
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
    
    parser.add_argument(
        "--dataset",
        type=str,
        default="test_data",
        help="Dataset filename (without .json) in data/test/cleaned/ (default: test_data)",
    )
    parser.add_argument(
        "--model",
        type=str,
        default=_DEFAULT_MODEL,
        help=(
            "Model to use. Short names are auto-prefixed: 'claude-*' → anthropic/, "
            "others → openai/. Full 'provider/model' strings are also accepted. "
            f"(default: {_DEFAULT_MODEL})"
        ),
    )
    parser.add_argument(
        "--stage",
        type=int,
        default=0,
        choices=[0, 1],
        help="0 = both stages (default), 1 = stage 1 only",
    )

    args = parser.parse_args()
    main(
        n_rows=args.n_rows,
        max_workers=args.max_workers,
        model=args.model,
        dataset=args.dataset,
        stage=args.stage,
    )
