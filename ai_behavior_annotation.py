from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import List, Tuple, Dict, Any

import pandas as pd

from prompt_generator import build_messages
from llm_annotator import LLMAnnotator
from codebook_ai_behavior import AI_BEHAVIOR_CODEBOOK
from evaluator import compute_prf


# -----------------------------
# Config
# -----------------------------
@dataclass(frozen=True)
class EvalConfig:
    csv_path: str = "./data/raw/fiona/Fiona_AI behavior.csv"
    text_col: str = "Relevant quotes "
    label_col: str = "Level"
    skiprows: int = 1
    n_rows: int = 2

    # artifact output
    output_path: str = "./artifacts/ai_behavior_runs.csv"
    include_prompt_text: bool = False  # set True if you want to save system/user strings too


# -----------------------------
# Utilities
# -----------------------------
def normalize_label(x: Any) -> str:
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
    return [build_messages(codebook=AI_BEHAVIOR_CODEBOOK, sentence=s) for s in sentences]


def prompt_to_text(prompt: list) -> Tuple[str, str]:
    """Extract system/user strings from messages list (for saving/debugging)."""
    system = next((m.get("content", "") for m in prompt if m.get("role") == "system"), "")
    user = next((m.get("content", "") for m in prompt if m.get("role") == "user"), "")
    return system, user


def predict_outputs(annotator: LLMAnnotator, prompts: List[list]) -> List[Dict[str, Any]]:
    """Run annotation and return raw outputs (dicts)."""
    outputs: List[Dict[str, Any]] = []
    for prompt in prompts:
        out = annotator.annotate(prompt)  # expects dict with scheme/level/confidence (based on your validator)
        outputs.append(out)
    return outputs


def save_run_artifacts(
    cfg: EvalConfig,
    sentences: List[str],
    ground_truths: List[str],
    prompts: List[list],
    outputs: List[Dict[str, Any]],
) -> str:
    """
    Save a CSV containing sentence/gt/pred + scheme/confidence (+ optional prompt text).
    Appends to cfg.output_path (adds header if file doesn't exist).
    Returns run_id.
    """
    out_path = Path(cfg.output_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)

    run_id = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    rows: List[Dict[str, Any]] = []

    for i, (sent, gt, prompt, out) in enumerate(zip(sentences, ground_truths, prompts, outputs)):
        row = {
            "run_id": run_id,
            "row_idx": i,
            "sentence": sent,
            "ground_truth": gt,
            "pred_scheme": out.get("scheme", ""),
            "pred_level": normalize_label(out.get("level", "")),
            "confidence": out.get("confidence", None),
        }

        if cfg.include_prompt_text:
            system_txt, user_txt = prompt_to_text(prompt)
            row["system_prompt"] = system_txt
            row["user_prompt"] = user_txt

        rows.append(row)

    df_out = pd.DataFrame(rows)
    df_out.to_csv(out_path, mode="a", header=not out_path.exists(), index=False)

    return run_id


# -----------------------------
# Main runner
# -----------------------------
def run_eval(cfg: EvalConfig) -> Dict[str, float]:
    sentences, ground_truths = load_eval_data(cfg)
    prompts = build_prompts(sentences)

    annotator = LLMAnnotator(codebook=AI_BEHAVIOR_CODEBOOK)
    outputs = predict_outputs(annotator, prompts)

    predictions = [normalize_label(o.get("level", "")) for o in outputs]

    # NOTE: choose micro if you want straightforward global metrics
    results = compute_prf(y_true=ground_truths, y_pred=predictions, average="micro")

    print(f"predictions:   {predictions}")
    print(f"ground_truths: {ground_truths}")
    print(results)

    run_id = save_run_artifacts(cfg, sentences, ground_truths, prompts, outputs)
    print(f"Saved run artifacts to {cfg.output_path} (run_id={run_id})")

    return results


if __name__ == "__main__":
    cfg = EvalConfig(n_rows=2, include_prompt_text=False)
    run_eval(cfg)


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

notes:
gt label distribution skew
need to confirm how to use the examples
test with more models
would there be multi-label?
"""