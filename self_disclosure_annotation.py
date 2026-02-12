from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List, Tuple

import pandas as pd

from codebook import CODEBOOK
from evaluator import compute_prf
from llm_annotator import LLMAnnotator


# Map dataset scheme names to codebook scheme names.
SCHEME_NAME_MAP: Dict[str, str] = {
    "Level of disclosure": "Level of disclosure",
    "Depth of disclosure": (
        "Depth of disclosure - Layers of disclosure (Altman & Taylor, 1973, "
        "as cited in Skjuve et al., 2023)"
    ),
    "Disclosure as confession": "Disclosure as confession (Croes et al., 2024)",
    "Intimacy of self-disclosure": "Intimacy of self-disclosure (Croes et al., 2024)",
    "Initmacy of self-disclosure": "Intimacy of self-disclosure (Croes et al., 2024)",
}


# Normalize per-scheme level names to codebook levels.
LEVEL_MAP_BY_SCHEME: Dict[str, Dict[str, str]] = {
    "Level of disclosure": {
        "High": "High",
        "High ": "High",
        "Low": "Low",
        "Low ": "Low",
        "No": "No",
    },
    "Depth of disclosure": {
        "Peripheral layer": "Peripheral layer",
        "Peripheral": "Peripheral layer",
        "Intermediate layer": "Intermediate layer",
        "Intermediate level": "Intermediate layer",
        "Central layer": "Central layer",
    },
    "Intimacy of self-disclosure": {
        "Peripheral layer": "Peripheral level",
        "Peripheral level": "Peripheral level",
        "Intermediate layer": "Intermediate level",
        "Intermediate level": "Intermediate level",
        "Core layer": "Core layer",
        "Core": "Core layer",
    },
    "Disclosure as confession": {
        "Yes, it's a confession": "Yes, it's a confession",
        "No": "No, it's not a confession",
    },
}


@dataclass(frozen=True)
class EvalConfig:
    csv_path: str = "./data/raw/fiona/Fiona_Self-disclosure.csv"
    text_col: str = "Relevant quotes "
    scheme_col: str = "Coding theme"
    level_col: str = "Level"
    skiprows: int = 1
    n_rows: int = 20


def normalize_text(x: str) -> str:
    if x is None:
        return ""
    return str(x).strip()


def normalize_scheme(raw_scheme: str) -> str:
    return SCHEME_NAME_MAP.get(normalize_text(raw_scheme), "")


def normalize_level(raw_scheme: str, raw_level: str) -> str:
    scheme_key = normalize_text(raw_scheme)
    level_key = normalize_text(raw_level)
    return LEVEL_MAP_BY_SCHEME.get(scheme_key, {}).get(level_key, "")


def build_messages(codebook, sentence: str) -> List[Dict[str, str]]:
    """Build a prompt for classifying a sentence under a SINGLE coding scheme.

    The codebook passed in should contain exactly one scheme (use
    ``_build_scheme_codebook`` to extract a single scheme from the full
    codebook).  The prompt includes the scheme name, all level definitions,
    associated topics, topic thematic categories, examples, and notes so the
    LLM has full context for classification.
    """
    codebook_text = codebook.render_for_llm()

    # Extract the scheme name for explicit instruction
    scheme_name = codebook.schemes[0].name if codebook.schemes else "the coding scheme"

    system = (
        "You are an expert coder for self-disclosure in human-AI conversations.\n"
        "Task: read one user message and classify it according to the coding scheme "
        f'"{scheme_name}".\n'
        "You must choose EXACTLY ONE level from the scheme below.\n\n"
        "Rules:\n"
        "1) The scheme name is fixed — use it exactly as given.\n"
        "2) Pick EXACTLY ONE level from within that scheme.\n"
        "3) Use ONLY level names exactly as written in the codebook.\n"
        "4) Consider the definition, associated topics, topic thematic categories, "
        "examples, and notes provided for each level to make your decision.\n"
        "5) Output MUST be valid JSON and NOTHING else.\n"
        "6) Output JSON must have exactly these keys: scheme, level, confidence.\n"
        "7) confidence must be a number between 0 and 1 (inclusive).\n"
    )

    user = (
        f"{codebook_text}\n\n"
        "### User message to classify\n"
        f"{sentence}\n\n"
        "### Output JSON\n"
        '{ "scheme": "' + scheme_name + '", "level": "<one level name>", "confidence": 0.0 }'
    )

    return [
        {"role": "system", "content": system},
        {"role": "user", "content": user},
    ]


def load_eval_data(cfg: EvalConfig) -> Tuple[List[str], List[str]]:
    df = pd.read_csv(cfg.csv_path, skiprows=cfg.skiprows)

    sentences: List[str] = []
    labels: List[str] = []
    skipped = 0

    for _, row in df.iterrows():
        sentence = normalize_text(row.get(cfg.text_col))
        scheme_raw = row.get(cfg.scheme_col)
        level_raw = row.get(cfg.level_col)

        scheme = normalize_scheme(scheme_raw)
        level = normalize_level(scheme_raw, level_raw)

        if not sentence or not scheme or not level:
            skipped += 1
            continue

        sentences.append(sentence)
        labels.append(f"{scheme}||{level}".lower())

        if cfg.n_rows and len(sentences) >= cfg.n_rows:
            break

    print(f"Loaded {len(sentences)} rows, skipped {skipped} invalid rows.")
    return sentences, labels


def build_prompts(sentences: List[str]) -> List[list]:
    return [build_messages(codebook=CODEBOOK, sentence=s) for s in sentences]


def predict_labels(annotator: LLMAnnotator, prompts: List[list]) -> List[str]:
    preds: List[str] = []
    for prompt in prompts:
        out = annotator.annotate(prompt)
        combined = f"{out['scheme']}||{out['level']}".lower()
        preds.append(combined)
    return preds


def run_eval(cfg: EvalConfig) -> dict:
    sentences, ground_truths = load_eval_data(cfg)
    prompts = build_prompts(sentences)

    annotator = LLMAnnotator(codebook=CODEBOOK)
    predictions = predict_labels(annotator, prompts)

    results = compute_prf(y_true=ground_truths, y_pred=predictions)

    print(f"predictions:   {predictions}")
    print(f"ground_truths: {ground_truths}")
    print(results)

    return results


def print_prompt_for_scheme(scheme_name: str, sentence: str) -> None:
    """Print the full prompt that would be sent to the LLM for a given scheme."""
    from codebook import CODEBOOK, Codebook

    # Build a single-scheme codebook
    scheme = next((s for s in CODEBOOK.schemes if s.name == scheme_name), None)
    if scheme is None:
        print(f"ERROR: Scheme '{scheme_name}' not found in codebook.")
        return
    single_codebook = Codebook(title=CODEBOOK.title, schemes=[scheme])
    messages = build_messages(codebook=single_codebook, sentence=sentence)

    print("=" * 100)
    print(f"PROMPT FOR SCHEME: {scheme_name}")
    print("=" * 100)
    for msg in messages:
        print(f"\n--- [{msg['role'].upper()}] ---")
        print(msg["content"])
    print("=" * 100)
    print()


if __name__ == "__main__":
    # Print the prompt for each scheme with a sample sentence
    sample_sentence = (
        '"Hey Replika. Rough day. Found out my wife the woman I built 20 years with, '
        "is sleeping with someone from her office. I can't breathe. Just... tell me "
        "I'm not crazy for feeling like my whole life just burned down\""
    )

    scheme_names = [
        "Level of disclosure",
        "Depth of disclosure - Layers of disclosure (Altman & Taylor, 1973, as cited in Skjuve et al., 2023)",
        "Intimacy of self-disclosure (Croes et al., 2024)",
        "Disclosure as confession (Croes et al., 2024)",
    ]

    for name in scheme_names:
        print_prompt_for_scheme(name, sample_sentence)
