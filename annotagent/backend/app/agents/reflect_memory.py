"""Human-feedback → reflect-rule converter.

Takes a plain-English correction note from the annotator (e.g. "the model
keeps mislabelling past-tense disclosures as Low") and converts it to
structured rules in the same schema ReflectAgent uses, then merges with the
existing rule library.
"""
from __future__ import annotations

import json
import logging
from typing import Any

from app.engine.llm_client import call_llm

logger = logging.getLogger(__name__)

_SYSTEM = """You are refining an annotation rule library based on direct human feedback.

The annotator has identified a specific issue with the current annotations. Your job is to
translate that feedback into one or more STRUCTURED RULES that would prevent the issue.

Use this exact schema:
[
  {
    "id": "short_slug",
    "target_labels": ["label_a", "label_b"],
    "boundary": "one-sentence distinction between these labels",
    "positive_cues": ["phrase or pattern that signals label_a"],
    "negative_cues": ["phrase or pattern that should NOT trigger label_a"],
    "rule": "instruction an annotator would read"
  }
]

HARD CONSTRAINTS:
1. Do NOT quote exact sentences verbatim from the feedback. Rules must generalize.
2. Each rule MUST have a `boundary` field.
3. If a matching rule already exists in the library (same `id`), return an UPDATED version.
4. Return ONLY a valid JSON array — no prose, no markdown fences."""


async def apply_human_feedback(
    *,
    feedback_text: str,
    dimension_name: str,
    label_defs: str,
    existing_rules: list[dict[str, Any]],
    provider: str,
    model: str,
    api_key: str,
) -> list[dict[str, Any]]:
    """Convert free-text human feedback to structured rules and merge with the existing library.

    Returns the merged rule list. On any LLM failure the existing rules are
    returned unchanged so the caller can still save a new version with the
    feedback recorded in `new_rules_count=0`.
    """
    existing_summary = json.dumps(existing_rules, indent=2) if existing_rules else "(empty)"
    user_msg = f"""Dimension: {dimension_name}

Label definitions:
{label_defs or "(not available)"}

Existing rule library:
{existing_summary}

Human annotator feedback:
{feedback_text}

Return a JSON array of NEW or UPDATED rules that address this feedback."""

    try:
        resp = await call_llm(
            messages=[
                {"role": "system", "content": _SYSTEM},
                {"role": "user", "content": user_msg},
            ],
            provider=provider,
            model=model,
            api_key=api_key,
            max_tokens=1024,
        )
        text = resp.text.strip()
        if text.startswith("```"):
            text = text.split("\n", 1)[1].rsplit("```", 1)[0]
        new_rules = json.loads(text)
        if not isinstance(new_rules, list):
            logger.warning("apply_human_feedback: LLM returned non-list")
            return existing_rules
        valid = [r for r in new_rules if isinstance(r, dict) and r.get("boundary")]
        return _merge_rules(existing_rules, valid)
    except Exception as e:
        logger.warning(f"apply_human_feedback failed: {e}")
        return existing_rules


_PROMPT_UPDATE_SYSTEM = """You are improving an annotation prompt by incorporating calibration rules
learned from human feedback.

INSTRUCTIONS:
1. Keep the original prompt structure and core instructions intact.
2. Integrate the rules naturally — weave them into the relevant sections rather than dumping
   them as a raw list at the end.
3. If the prompt already has a calibration or notes section, extend it. Otherwise add one.
4. Do NOT add exemplar sentences verbatim. Rules only.
5. Return ONLY the updated prompt text — no explanation, no markdown fences."""


async def apply_rules_to_prompt(
    *,
    base_prompt: str,
    rules: list[dict[str, Any]],
    dimension_name: str,
    provider: str,
    model: str,
    api_key: str,
) -> str:
    """Rewrite the base annotation prompt to incorporate structured memory rules.

    Returns the updated prompt. Falls back to base_prompt unchanged on any failure.
    """
    if not rules:
        return base_prompt

    rules_block = "\n".join(
        f"- [{r.get('id', '?')}] {r.get('boundary', r.get('rule', ''))}"
        + (f"\n  Positive cues: {', '.join(r['positive_cues'])}" if r.get("positive_cues") else "")
        + (f"\n  Negative cues: {', '.join(r['negative_cues'])}" if r.get("negative_cues") else "")
        for r in rules
    )
    user_msg = f"""Dimension: {dimension_name}

CURRENT PROMPT:
{base_prompt}

CALIBRATION RULES TO INCORPORATE:
{rules_block}

Return the updated prompt."""

    try:
        resp = await call_llm(
            messages=[
                {"role": "system", "content": _PROMPT_UPDATE_SYSTEM},
                {"role": "user", "content": user_msg},
            ],
            provider=provider,
            model=model,
            api_key=api_key,
            max_tokens=2048,
        )
        updated = resp.text.strip()
        if updated.startswith("```"):
            updated = updated.split("\n", 1)[1].rsplit("```", 1)[0].strip()
        return updated or base_prompt
    except Exception as e:
        logger.warning(f"apply_rules_to_prompt failed: {e}")
        return base_prompt


def _merge_rules(
    existing: list[dict[str, Any]],
    new: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Upsert by `id`. New version replaces old with same id."""
    by_id = {r.get("id", f"r_{i}"): r for i, r in enumerate(existing)}
    for r in new:
        rid = r.get("id") or r["boundary"][:40]
        by_id[rid] = r
    return list(by_id.values())
