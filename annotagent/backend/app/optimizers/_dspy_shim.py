"""Shared DSPy glue for GEPA and MIPROv2 wrappers.

Both baselines are DSPy teleprompters. This module converts our
`Example(sentence, gold, context)` list into `dspy.Example`s, sets up the LM,
defines a minimal single-signature classification module, and extracts the
final optimized instruction text so it can be returned as a plain prompt
string."""
from __future__ import annotations


import dspy

from app.optimizers.base import Example


def build_lm(provider: str, model: str, api_key: str) -> dspy.LM:
    """DSPy LM handle. DSPy expects provider-prefixed model names for non-OpenAI."""
    if provider == "anthropic":
        name = f"anthropic/{model}"
    else:
        name = f"openai/{model}"
    return dspy.LM(name, api_key=api_key, temperature=1.0, max_tokens=2048)


def make_classifier_module(
    dimension: str, valid_labels: list[str], initial_prompt: str | None = None,
) -> dspy.Module:
    """A minimal single-signature classifier. Its instruction is what we optimize.

    When ``initial_prompt`` is given, the module is seeded with the *same* prompt
    the other optimizers (e.g. ReflectAgent) start from, so the comparison is
    apples-to-apples rather than handicapping the DSPy baselines with a generic
    seed. Falls back to a minimal instruction when no prompt is supplied.
    """
    labels_str = " | ".join(valid_labels)
    seed = (initial_prompt or "").strip()
    instructions = seed or (
        f"Classify the sentence on the dimension '{dimension}'. "
        f"Choose exactly one label from: {labels_str}."
    )
    sig = dspy.Signature("sentence, context -> label", instructions=instructions)
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


def feedback_metric(gold: dspy.Example, pred, trace=None, pred_name=None, pred_trace=None):
    """GEPA feedback metric: exact-match score plus a short textual reason.

    GEPA's reflective loop is designed to consume natural-language feedback
    (``GEPAFeedbackMetric`` returns ``float | ScoreWithFeedback``). Returning a
    ``dspy.Prediction(score, feedback)`` gives the optimizer its intended signal,
    so the baseline reflects GEPA's real capability rather than a strawman.
    The score is identical to ``exact_match_metric`` so the two are comparable.
    """
    gold_label = (gold.label or "").strip()
    pred_label = (getattr(pred, "label", "") or "").strip()
    score = float(gold_label.lower() == pred_label.lower())
    if score == 1.0:
        fb = f"Correct: predicted '{pred_label}', which matches the gold label."
    else:
        fb = (
            f"Incorrect: predicted '{pred_label or '(empty/unparseable)'}' but the gold "
            f"label is '{gold_label}'. Revise the instruction so a sentence like this "
            f"is labeled '{gold_label}'; make the boundary that separates '{gold_label}' "
            f"from '{pred_label or 'other labels'}' explicit."
        )
    return dspy.Prediction(score=score, feedback=fb)


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


def extract_prompt_with_demos(
    compiled_module: dspy.Module, fallback: str, max_demos: int = 8,
) -> tuple[str, int]:
    """For MIPRO: instruction PLUS its bootstrapped few-shot demos, as one prompt.

    MIPRO's contribution is jointly the instruction AND the demos; extracting only
    the instruction would under-represent it. We append the selected demos as
    few-shot examples in the same 'Sentence: ... / Answer: ...' shape the eval
    harness feeds at inference, so the demos actually take effect when scored.
    Returns (prompt, n_demos). Demos come from the trainset (verify via the
    leakage auditor that none are val/test).
    """
    inst = fallback
    demos: list = []
    try:
        for _, sub in compiled_module.named_predictors():
            si = getattr(sub.signature, "instructions", None)
            if si:
                inst = si
            d = list(getattr(sub, "demos", []) or [])
            if d:
                demos = d
                break
    except Exception:
        return fallback, 0
    if not demos:
        return inst, 0
    lines = [inst.strip(), "", "## Examples", ""]
    used = 0
    for d in demos[:max_demos]:
        s = (getattr(d, "sentence", "") or "").strip()
        ctx = (getattr(d, "context", "") or "").strip()
        lab = (getattr(d, "label", "") or "").strip()
        if not s or not lab:
            continue
        if ctx:
            lines.append(f"Context: {ctx}")
        lines.append(f"Sentence: {s}")
        lines.append(f"Answer: {lab}")
        lines.append("")
        used += 1
    return "\n".join(lines).strip(), used
