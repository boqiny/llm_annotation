"""
ReflectAgent.

This module implements feedback-driven prompt refinement through rule-level
memory. It converts human corrections into reusable annotation rules and uses
those rules to update future annotation prompts.

Responsibilities:
- Read annotation feedback examples.
- Induce compact reusable memory rules.
- Maintain project-local memory state.
- Build updated prompts by injecting memory rules.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from annotation_demo.core.llm import BaseLLM
from annotation_demo.prompts.renderer import render_template


@dataclass
class MemoryRule:
    id: str
    title: str
    rule: str
    rationale: str
    applies_to: str
    confidence: float


@dataclass
class ReflectMemory:
    version: str
    rules: list[MemoryRule]


class ReflectAgent:
    def __init__(self, llm: BaseLLM):
        self.llm = llm

    def induce_rules(
        self,
        annotation_prompt: str,
        feedback_examples: list[dict[str, Any]],
        existing_memory: ReflectMemory | None = None,
    ) -> list[MemoryRule]:
        memory_rules = []
        if existing_memory is not None:
            memory_rules = [
                {
                    "id": rule.id,
                    "title": rule.title,
                    "rule": rule.rule,
                    "applies_to": rule.applies_to,
                }
                for rule in existing_memory.rules
            ]

        system_prompt = render_template(
            "reflect_agent.jinja",
            annotation_prompt=annotation_prompt,
            memory_rules=memory_rules,
            feedback_examples=feedback_examples,
        )

        response = self.llm.generate_json(
            messages=[
                {"role": "system", "content": system_prompt},
            ]
        )

        raw_rules = response.get("rules", [])
        new_rules: list[MemoryRule] = []

        start_idx = 1
        if existing_memory is not None:
            start_idx = len(existing_memory.rules) + 1

        for i, raw_rule in enumerate(raw_rules, start=start_idx):
            new_rules.append(
                MemoryRule(
                    id=f"rule_{i:03d}",
                    title=str(raw_rule.get("title", "")).strip(),
                    rule=str(raw_rule.get("rule", "")).strip(),
                    rationale=str(raw_rule.get("rationale", "")).strip(),
                    applies_to=str(raw_rule.get("applies_to", "")).strip(),
                    confidence=float(raw_rule.get("confidence", 0.0)),
                )
            )

        return new_rules

    def update_memory(
        self,
        existing_memory: ReflectMemory | None,
        new_rules: list[MemoryRule],
        new_version: str,
    ) -> ReflectMemory:
        old_rules = existing_memory.rules if existing_memory is not None else []

        return ReflectMemory(
            version=new_version,
            rules=old_rules + new_rules,
        )

    def build_prompt_with_memory(
        self,
        annotation_prompt: str,
        memory: ReflectMemory,
    ) -> str:
        if not memory.rules:
            return annotation_prompt

        memory_block = ["\n\nAdditional annotation rules from feedback memory:"]

        for rule in memory.rules:
            memory_block.append(
                f"- [{rule.id}] {rule.rule}"
            )

        return annotation_prompt + "\n".join(memory_block)


def memory_to_dict(memory: ReflectMemory) -> dict[str, Any]:
    return {
        "version": memory.version,
        "rules": [
            {
                "id": rule.id,
                "title": rule.title,
                "rule": rule.rule,
                "rationale": rule.rationale,
                "applies_to": rule.applies_to,
                "confidence": rule.confidence,
            }
            for rule in memory.rules
        ],
    }


def memory_from_dict(obj: dict[str, Any]) -> ReflectMemory:
    return ReflectMemory(
        version=obj["version"],
        rules=[
            MemoryRule(
                id=rule["id"],
                title=rule["title"],
                rule=rule["rule"],
                rationale=rule.get("rationale", ""),
                applies_to=rule.get("applies_to", ""),
                confidence=float(rule.get("confidence", 0.0)),
            )
            for rule in obj.get("rules", [])
        ],
    )