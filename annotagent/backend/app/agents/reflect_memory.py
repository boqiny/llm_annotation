"""Calibration evidence → reflect-rule converter.

Converts either direct human feedback or optimizer failure evidence into
structured rules in the same schema ReflectAgent uses, then merges with the
existing rule library.
"""
from __future__ import annotations

import json
import logging
from typing import Any

from app.engine.llm_client import call_llm

logger = logging.getLogger(__name__)

_SYSTEM = """You are refining an annotation rule library based on calibration evidence.

The evidence may be direct human feedback, positive guidance about what is already correct,
or model failures with gold labels and predictions. Your job is to translate that evidence
into general annotation principles that improve future decisions.

Use this exact schema:
[
  {
    "id": "short_slug",
    "target_labels": ["label_a", "label_b"],
    "boundary": "one-sentence distinction between these labels",
    "positive_cues": ["optional broad cue family that supports this boundary"],
    "negative_cues": ["optional broad cue family that should not trigger the target label"],
    "rule": "instruction an annotator would read"
  }
]

HARD CONSTRAINTS:
1. Do NOT quote exact sentences verbatim from the evidence. Rules must generalize.
2. Each rule MUST have a concise `boundary` field that states the general distinction.
3. If a matching rule already exists in the library (same `id`), return an UPDATED version.
4. Prefer 2-5 tight, high-leverage rules over many narrow rules.
5. Human feedback can be positive ("this is correct because...") or corrective ("this is wrong because...").
   Preserve positive guidance as a rule about when to keep or trust a label.
6. Use positive_cues and negative_cues sparingly. They should be broad signal families, not examples,
   quoted phrases, or long lists. Empty arrays are acceptable.
7. If evidence is idiosyncratic and does not generalize, skip it.
8. Return ONLY a valid JSON array — no prose, no markdown fences."""


async def apply_calibration_evidence(
    *,
    evidence_text: str,
    dimension_name: str,
    label_defs: str,
    existing_rules: list[dict[str, Any]],
    provider: str,
    model: str,
    api_key: str,
    evidence_label: str = "Calibration evidence",
    max_tokens: int = 2048,
) -> list[dict[str, Any]]:
    """Convert calibration evidence to structured rules and merge with the existing library.

    Returns the merged rule list. On any LLM failure the existing rules are
    returned unchanged so callers can still save an auditable version.
    """
    existing_summary = json.dumps(existing_rules, indent=2) if existing_rules else "(empty)"
    user_msg = f"""Dimension: {dimension_name}

Label definitions:
{label_defs or "(not available)"}

Existing rule library:
{existing_summary}

{evidence_label}:
{evidence_text}

Return a JSON array of NEW or UPDATED general rules that address this evidence."""

    try:
        resp = await call_llm(
            messages=[
                {"role": "system", "content": _SYSTEM},
                {"role": "user", "content": user_msg},
            ],
            provider=provider,
            model=model,
            api_key=api_key,
            max_tokens=max_tokens,
        )
        text = resp.text.strip()
        if text.startswith("```"):
            text = text.split("\n", 1)[1].rsplit("```", 1)[0]
        new_rules = json.loads(text)
        if not isinstance(new_rules, list):
            logger.warning("apply_calibration_evidence: LLM returned non-list")
            return existing_rules
        valid = [r for r in new_rules if isinstance(r, dict) and r.get("boundary")]
        return _merge_rules(existing_rules, valid)
    except Exception as e:
        logger.warning(f"apply_calibration_evidence failed: {e}")
        return existing_rules


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
    """Convert free-text human feedback to structured rules and merge with the existing library."""
    return await apply_calibration_evidence(
        evidence_text=feedback_text,
        dimension_name=dimension_name,
        label_defs=label_defs,
        existing_rules=existing_rules,
        provider=provider,
        model=model,
        api_key=api_key,
        evidence_label="Human annotator feedback",
        max_tokens=1024,
    )


_PROMPT_UPDATE_SYSTEM = """You are improving an annotation prompt by incorporating calibration memory
learned from human feedback and labeled-data improvement runs.

INSTRUCTIONS:
1. Keep the original prompt structure and core instructions intact.
2. Integrate the rules naturally — weave them into the relevant sections rather than dumping
   them as a raw list at the end.
3. If the prompt already has a calibration or notes section, extend it. Otherwise add one.
4. Favor short, general principles. Merge overlapping rules and remove repetition.
5. Do NOT add exemplar sentences verbatim.
6. Do NOT create separate "positive cues" or "negative cues" lists in the final prompt unless
   they are essential. Usually fold cues into a concise rule sentence instead.
7. Return ONLY the updated prompt text — no explanation, no markdown fences."""


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
        + (f"\n  Rule: {r['rule']}" if r.get("rule") and r.get("rule") != r.get("boundary") else "")
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
