"""Shared DSPy glue for GEPA and MIPROv2 wrappers.

Both baselines are DSPy teleprompters. This module converts our
`Example(sentence, gold, context)` list into `dspy.Example`s, sets up the LM,
defines a minimal single-signature classification module, and extracts the
final optimized instruction text so it can be returned as a plain prompt
string."""
from __future__ import annotations

from typing import Callable

import dspy

from app.optimizers.base import Example


def build_lm(provider: str, model: str, api_key: str) -> dspy.LM:
    """DSPy LM handle. DSPy expects provider-prefixed model names for non-OpenAI."""
    if provider == "anthropic":
        name = f"anthropic/{model}"
    else:
        name = f"openai/{model}"
    return dspy.LM(name, api_key=api_key, temperature=1.0, max_tokens=2048)


def make_classifier_module(dimension: str, valid_labels: list[str]) -> dspy.Module:
    """A minimal ChainOfThought classifier. Its instruction is what we optimize."""
    labels_str = " | ".join(valid_labels)
    sig = dspy.Signature(
        "sentence, context -> label",
        instructions=(
            f"Classify the sentence on the dimension '{dimension}'. "
            f"Choose exactly one label from: {labels_str}."
        ),
    )
    return dspy.Predict(sig)


def to_dspy_examples(examples: list[Example]) -> list[dspy.Example]:
    out = []
    for ex in examples:
        e = dspy.Example(
            sentence=ex.sentence,
            context=ex.context or "",
            label=ex.gold,
        ).with_inputs("sentence", "context")
        out.append(e)
    return out


def exact_match_metric(gold: dspy.Example, pred, trace=None, pred_name=None, pred_trace=None):
    """Exact-match accuracy, returned as float for DSPy compatibility."""
    gold_label = (gold.label or "").strip().lower()
    pred_label = (getattr(pred, "label", "") or "").strip().lower()
    return float(gold_label == pred_label)


def extract_instruction(compiled_module: dspy.Module, fallback: str) -> str:
    """Pull the optimized instruction text out of a compiled DSPy module."""
    try:
        # Predict modules expose .signature.instructions
        for _, sub in compiled_module.named_predictors():
            inst = getattr(sub.signature, "instructions", None)
            if inst:
                return inst
    except Exception:
        pass
    return fallback
