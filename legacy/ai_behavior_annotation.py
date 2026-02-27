from __future__ import annotations

from dataclasses import dataclass
from typing import List, Tuple

import pandas as pd

from prompt_generator import build_messages
from llm_annotator import LLMAnnotator
from codebook_ai_behavior import AI_BEHAVIOR_CODEBOOK
from evaluator import compute_prf


@dataclass(frozen=True)
class EvalConfig:
    csv_path: str = "./data/raw/fiona/Fiona_AI behavior.csv"
    text_col: str = "Relevant quotes "
    label_col: str = "Level"
    skiprows: int = 1
    n_rows: int = 2


def normalize_label(x: str) -> str:
    """Normalize label strings for fair comparison."""
    if x is None:
        return ""
    return str(x).strip().lower()


def load_eval_data(cfg: EvalConfig) -> Tuple[List[str], List[str]]:
    """Load sentences + ground truths from CSV."""
    df = pd.read_csv(cfg.csv_path, skiprows=cfg.skiprows)

    sentences = df[cfg.text_col].tolist()[: cfg.n_rows]
    ground_truths = [normalize_label(x) for x in df[cfg.label_col].tolist()[: cfg.n_rows]]

    return sentences, ground_truths


def build_prompts(sentences: List[str]) -> List[list]:
    """Build LLM messages for each sentence."""
    return [
        build_messages(codebook=AI_BEHAVIOR_CODEBOOK, sentence=s)
        for s in sentences
    ]


def predict_levels(annotator: LLMAnnotator, prompts: List[list]) -> List[str]:
    """Run annotation and return normalized predicted levels."""
    preds: List[str] = []
    for prompt in prompts:
        out = annotator.annotate(prompt)          # dict: scheme/level/(confidence)
        preds.append(normalize_label(out["level"]))
    return preds


def run_eval(cfg: EvalConfig) -> dict:
    """End-to-end evaluation runner."""
    sentences, ground_truths = load_eval_data(cfg)
    prompts = build_prompts(sentences)

    annotator = LLMAnnotator(codebook=AI_BEHAVIOR_CODEBOOK)
    predictions = predict_levels(annotator, prompts)

    results = compute_prf(y_true=ground_truths, y_pred=predictions)

    print(f"predictions:   {predictions}")
    print(f"ground_truths: {ground_truths}")
    print(results)

    return results


if __name__ == "__main__":
    cfg = EvalConfig(n_rows=2)  # change here
    run_eval(cfg)

# TODO: Add logs and store the prompts/outputs somewhere

"""
Test outputs:

2 rows
predictions:   ['sympathetic responsiveness', 'question-asking']
ground_truths: ['offers advice, opinions, perspectives, and personal experience', 'question-asking']
{'precision': 0.5, 'recall': 0.5, 'f1': 0.5, 'accuracy': 0.5}

10 rows
predictions:   ['sympathetic responsiveness', 'question-asking', 'question-asking', 'question-asking', 'question-asking', 'question-asking', 'question-asking', 'question-asking', 'question-asking', 'question-asking']
ground_truths: ['offers advice, opinions, perspectives, and personal experience', 'question-asking', 'question-asking', 'question-asking', 'question-asking', 'question-asking', 'question-asking', 'sympathetic responsiveness', 'paraphrase', 'question-asking']
{'precision': 0.7, 'recall': 0.7, 'f1': 0.7, 'accuracy': 0.7}
"""