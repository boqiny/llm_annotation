"""Calibration Agent — mines errors, refines prompts, re-annotates gold subset."""
from __future__ import annotations

import copy
import json
import logging
from typing import Any

from app.agents.annotation import annotate_batch
from app.engine.llm_client import call_llm
from app.engine.metrics import compute_metrics, confusion_matrix

logger = logging.getLogger(__name__)


async def run_calibration(
    predictions: list[dict[str, str]],
    gold_labels: list[dict[str, str]],
    dimensions: list[str],
    *,
    gold_items: list[dict[str, Any]] | None = None,
    steps: list[dict[str, Any]] | None = None,
    codebook_dims: dict[str, list[str]] | None = None,
    provider: str = "openai",
    model: str = "gpt-5.4-mini",
    api_key: str = "",
) -> dict[str, Any]:
    """Run the full calibration loop.

    1. Score current predictions vs gold (before metrics).
    2. Mine systematic error patterns via LLM.
    3. Inject the patterns as Calibration Notes into each step's prompt.
    4. Re-annotate the gold items with refined prompts.
    5. Score the new predictions vs gold (after metrics).
    6. Return before, after, delta, refined_steps, and generated rules.

    The re-annotation stage runs only if `gold_items`, `steps`, and `codebook_dims`
    are provided and `api_key` is set. Otherwise only the error-mining portion runs.
    """
    before = _score(predictions, gold_labels, dimensions)
    errors = _extract_errors(predictions, gold_labels, dimensions)

    error_patterns: list[dict[str, Any]] = []
    rules_generated: list[dict[str, Any]] = []

    if errors and api_key:
        error_patterns, rules_generated = await _mine_patterns(
            errors, provider=provider, model=model, api_key=api_key,
        )

    refined_steps: list[dict[str, Any]] = []
    after: dict[str, Any] = {}
    delta: dict[str, dict[str, float]] = {}

    can_reannotate = bool(
        rules_generated and gold_items and steps and codebook_dims and api_key
    )
    if can_reannotate:
        refined_steps = _inject_rules(steps, rules_generated)
        try:
            new_results = await annotate_batch(
                items=gold_items,
                steps=refined_steps,
                codebook_dims=codebook_dims,
                provider=provider, model=model, api_key=api_key,
                max_concurrency=5,
            )
            new_predictions = [r.labels for r in new_results]
            after = _score(new_predictions, gold_labels, dimensions)
            delta = _compute_delta(before, after)
        except Exception as e:
            logger.error(f"Calibration re-annotation failed: {e}")

    return {
        "before": before,
        "after": after,
        "delta": delta,
        "refined_steps": refined_steps,
        "error_patterns": error_patterns,
        "rules_generated": rules_generated,
        "total_errors": len(errors),
        "total_items": len(predictions),
        # legacy key preserved for the existing `metrics_json` column
        "metrics": before,
    }


def _score(
    predictions: list[dict[str, str]],
    gold_labels: list[dict[str, str]],
    dimensions: list[str],
) -> dict[str, Any]:
    per_dim: dict[str, Any] = {}
    for dim in dimensions:
        y_true = [g.get(dim, "") for g in gold_labels]
        y_pred = [p.get(dim, "") for p in predictions]
        pairs = [(t, p) for t, p in zip(y_true, y_pred) if t]
        if not pairs:
            continue
        yt = [p[0] for p in pairs]
        yp = [p[1] for p in pairs]
        m = compute_metrics(yt, yp)
        per_dim[dim] = {**m, "confusion_matrix": confusion_matrix(yt, yp)}
    return per_dim


def _extract_errors(
    predictions: list[dict[str, str]],
    gold_labels: list[dict[str, str]],
    dimensions: list[str],
) -> list[dict[str, Any]]:
    errors: list[dict[str, Any]] = []
    for dim in dimensions:
        for i, (g, p) in enumerate(zip(gold_labels, predictions)):
            gt = g.get(dim, "")
            pred = p.get(dim, "")
            if gt and gt != pred:
                errors.append({"dimension": dim, "index": i, "gold": gt, "predicted": pred})
    return errors


async def _mine_patterns(
    errors: list[dict[str, Any]],
    provider: str, model: str, api_key: str,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    summary = "\n".join(
        f"- [{e['dimension']}] Gold: {e['gold']}, Predicted: {e['predicted']}"
        for e in errors[:50]
    )
    meta_prompt = f"""Analyze these annotation errors and identify systematic patterns:

{summary}

For each pattern found, provide:
1. Pattern description
2. Affected dimension
3. A concrete calibration rule that tells an annotator how to avoid this confusion

Return ONLY a JSON array: [{{"pattern": "...", "dimension": "...", "rule": "..."}}]"""
    try:
        resp = await call_llm(
            messages=[
                {"role": "system", "content": "You are an annotation quality analyst."},
                {"role": "user", "content": meta_prompt},
            ],
            provider=provider, model=model, api_key=api_key, max_tokens=1024,
        )
        parsed = json.loads(resp.text)
        if not isinstance(parsed, list):
            return [{"raw_analysis": resp.text}], []
        rules = [
            {"dimension": p.get("dimension", ""), "rule": p.get("rule", "")}
            for p in parsed if p.get("rule")
        ]
        return parsed, rules
    except json.JSONDecodeError:
        return [{"raw_analysis": "LLM returned non-JSON"}], []
    except Exception as e:
        logger.error(f"Pattern mining failed: {e}")
        return [], []


def _inject_rules(
    steps: list[dict[str, Any]],
    rules: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Append a Calibration Notes block to each step's prompt for its dimensions."""
    rules_by_dim: dict[str, list[str]] = {}
    for r in rules:
        dim = r.get("dimension", "")
        rule = r.get("rule", "")
        if dim and rule:
            rules_by_dim.setdefault(dim, []).append(rule)

    refined = []
    for step in steps:
        step_copy = copy.deepcopy(step)
        applicable = []
        for dim in step.get("dimensions", []):
            for rule in rules_by_dim.get(dim, []):
                applicable.append(f"- [{dim}] {rule}")
        if applicable:
            note_block = (
                "\n\n## Calibration Notes (learned from error analysis)\n"
                "Pay special attention to the following rules:\n"
                + "\n".join(applicable)
            )
            step_copy["prompt"] = step.get("prompt", "") + note_block
        refined.append(step_copy)
    return refined


def _compute_delta(
    before: dict[str, Any], after: dict[str, Any]
) -> dict[str, dict[str, float]]:
    delta: dict[str, dict[str, float]] = {}
    for dim in set(before) | set(after):
        b = before.get(dim, {})
        a = after.get(dim, {})
        delta[dim] = {
            "accuracy_delta": round(a.get("accuracy", 0.0) - b.get("accuracy", 0.0), 4),
            "macro_f1_delta": round(a.get("macro_f1", 0.0) - b.get("macro_f1", 0.0), 4),
        }
    return delta
