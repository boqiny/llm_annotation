"""ReflectAgent — our method.

A reflective annotation-optimizer that mines *generalizable patterns* from
failure cases and injects them as rules, NOT exemplars. Three cooperating LLM
roles over a persistent Rule Library:

  - Annotator        (the existing agent)
  - PatternExtractor (distils failure batches into structured rules)
  - Governor         (holdout-gated rollback)

Why this beats demo-centric optimizers (GEPA, MIPRO) on subtle codebooks:
the PatternExtractor is *forbidden* from quoting exemplars verbatim and must
produce a `boundary` statement — which is what generalizes across held-out
items where the surface form differs from the training set.
"""

# TODO: Move all the inline prompts to the prompt templates
# add memory
from __future__ import annotations

import copy
import json
import logging

from typing import Optional

from app.engine.llm_client import call_llm
from app.engine.metrics import compute_metrics
from app.optimizers.base import (
    Example, OptimizationResult, ProgressCB, PromptOptimizer,
    _emit, evaluate_prompt,
)

logger = logging.getLogger(__name__)


_PATTERN_EXTRACTOR_SYSTEM = """You are a senior annotation quality analyst refining a codebook.

You will see a dimension's label definitions, the current rule library, and a batch of
annotation failures (gold label vs model prediction). Your job is to distil
GENERALIZABLE RULES that would prevent the systematic confusions you observe.

HARD CONSTRAINTS:
1. Do NOT quote full failure sentences verbatim. Rules must abstract the pattern.
2. Each rule MUST include a `boundary` field stating the distinction in your own words.
3. If a failure is idiosyncratic (one-off, doesn't generalize), SKIP it — don't create a rule for every error.
4. Do NOT duplicate existing rules in the library. If an existing rule is almost right, return an UPDATED version instead.
5. Prefer 2-5 tight, high-leverage rules over 10 narrow ones.

Output ONLY valid JSON array of rules with this schema:
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
"""


async def _extract_patterns(
    *, dimension: str, label_defs: str,
    failures: list[dict], existing_rules: list[dict],
    provider: str, model: str, api_key: str,
) -> list[dict]:
    """PatternExtractor role. Returns list of rule dicts (possibly empty)."""
    if not failures:
        return []

    failures_summary = "\n".join(
        f"- Gold=[{f['gold']}]  Pred=[{f['pred']}]  Sent=\"{f['sentence'][:180]}\""
        for f in failures[:40]  # cap
    )
    existing_summary = json.dumps(existing_rules, indent=2) if existing_rules else "(empty)"

    user_msg = f"""Dimension: {dimension}

Label definitions:
{label_defs}

Existing rule library:
{existing_summary}

Failure batch ({len(failures)} items):
{failures_summary}

Return JSON array of NEW or UPDATED rules."""

    try:
        resp = await call_llm(
            messages=[
                {"role": "system", "content": _PATTERN_EXTRACTOR_SYSTEM},
                {"role": "user", "content": user_msg},
            ],
            provider=provider, model=model, api_key=api_key, max_tokens=2048,
        )
        # Strip common wrappers
        text = resp.text.strip()
        if text.startswith("```"):
            text = text.split("\n", 1)[1].rsplit("```", 1)[0]
        rules = json.loads(text)
        if not isinstance(rules, list):
            return []
        # Basic schema guard
        return [r for r in rules if isinstance(r, dict) and r.get("rule") and r.get("boundary")]
    except (json.JSONDecodeError, KeyError, IndexError, Exception) as e:
        logger.warning(f"PatternExtractor failed to emit valid JSON: {e}")
        return []


def _merge_rules(existing: list[dict], new: list[dict]) -> list[dict]:
    """Upsert by `id`. New version replaces old with same id."""
    by_id = {r.get("id", f"r_{i}"): r for i, r in enumerate(existing)}
    for r in new:
        rid = r.get("id") or r["boundary"][:40]
        by_id[rid] = r
    return list(by_id.values())


def _compile_rules(rules: list[dict]) -> str:
    """Turn rule library into an appendable prompt block. No exemplars — only rules."""
    if not rules:
        return ""
    lines = ["", "## Calibration rules (from annotator adjudication)", ""]
    for i, r in enumerate(rules, 1):
        lines.append(f"{i}. **{r.get('boundary', r.get('rule', ''))}**")
        if r.get("rule") and r.get("rule") != r.get("boundary"):
            lines.append(f"   {r['rule']}")
        if r.get("positive_cues"):
            cues = ", ".join(f'"{c}"' for c in r["positive_cues"][:5])
            lines.append(f"   Positive cues: {cues}")
        if r.get("negative_cues"):
            cues = ", ".join(f'"{c}"' for c in r["negative_cues"][:5])
            lines.append(f"   Negative cues: {cues}")
        lines.append("")
    return "\n".join(lines)


class ReflectAgent(PromptOptimizer):
    """Rule-distillation prompt optimizer. See module docstring."""
    name = "reflect_agent"

    def __init__(
        self,
        *,
        provider: str = "openai",
        model: str = "gpt-5.4-mini",
        api_key: str = "",
        budget: int = 5,              # rounds, not LLM calls
        rollback_epsilon: float = 0.005,  # val F1 regression tolerance
        label_defs: str = "",
        seed_rules: list[dict] | None = None,
        **_ignored,
    ):
        super().__init__(provider=provider, model=model, api_key=api_key, budget=budget)
        self.rollback_epsilon = rollback_epsilon
        self.label_defs = label_defs
        # Cumulative rules carried in from prior reflect runs on this (project, dim).
        # Pre-populates the rule library and seeds the initial prompt so this run
        # picks up where the last one left off.
        self.seed_rules = list(seed_rules or [])

    async def optimize(
        self,
        initial_prompt: str,
        dimension: str,
        valid_labels: list[str],
        trainset: list[Example],
        valset: list[Example],
        on_progress: Optional[ProgressCB] = None,
    ) -> OptimizationResult:
        # Seed from prior memory if any — earlier sessions' rules are already
        # validated and we want this run to extend rather than restart them.
        rules: list[dict] = list(self.seed_rules)
        trajectory: list[dict] = []
        total_tokens = 0
        total_cost = 0.0

        # Helper: record a trajectory row AND push live progress to the UI
        async def record(entry: dict) -> None:
            trajectory.append(entry)
            await _emit(on_progress, {
                "trajectory": list(trajectory),
                "total_tokens": total_tokens,
                "total_cost_usd": total_cost,
                "current_round": entry.get("round", 0),
                "total_rounds": self.budget,
                "artifact": {"rule_library": list(rules), "n_rules": len(rules)},
                "optimized_prompt": current_prompt if trajectory else initial_prompt,
                "initial_score": base_acc if trajectory else 0.0,
                "final_score": current_val_acc if trajectory else 0.0,
            })

        # Baseline = initial_prompt + already-accumulated seed rules. If seed_rules
        # is empty this is identical to the previous behavior.
        current_prompt = initial_prompt + _compile_rules(rules)
        val_y_true = [ex.gold for ex in valset]
        base_acc, base_preds, t, c = await evaluate_prompt(
            current_prompt, valset, valid_labels,
            provider=self.provider, model=self.model, api_key=self.api_key,
        )
        total_tokens += t
        total_cost += c

        current_val_acc = base_acc
        base_metrics = compute_metrics(val_y_true, base_preds)

        await record({"round": 0, "val_acc": base_acc,
                      "val_macro_f1": round(base_metrics.get("macro_f1", 0.0), 4),
                      "n_rules": len(rules),
                      "action": "baseline_seeded" if rules else "baseline"})

        for r in range(1, self.budget + 1):
            # 1. Annotate the trainset with current prompt to find failures
            train_acc, preds, t, c = await evaluate_prompt(
                current_prompt, trainset, valid_labels,
                provider=self.provider, model=self.model, api_key=self.api_key,
            )
            total_tokens += t
            total_cost += c

            failures = [
                {"sentence": ex.sentence, "gold": ex.gold, "pred": p}
                for ex, p in zip(trainset, preds) if p != ex.gold
            ]

            if not failures:
                await record({
                    "round": r, "val_acc": current_val_acc, "n_rules": len(rules),
                    "n_failures": 0, "action": "converged",
                })
                break

            # 2. PatternExtractor distils failures → new rules
            new_rules = await _extract_patterns(
                dimension=dimension, label_defs=self.label_defs,
                failures=failures, existing_rules=rules,
                provider=self.provider, model=self.model, api_key=self.api_key,
            )

            if not new_rules:
                await record({
                    "round": r, "val_acc": current_val_acc, "n_rules": len(rules),
                    "n_failures": len(failures), "action": "no_new_rules",
                })
                continue

            # 3. Merge rules + recompile prompt
            candidate_rules = _merge_rules(rules, new_rules)
            candidate_prompt = initial_prompt + _compile_rules(candidate_rules)

            # 4. Governor: evaluate on val
            val_acc, val_preds, t, c = await evaluate_prompt(
                candidate_prompt, valset, valid_labels,
                provider=self.provider, model=self.model, api_key=self.api_key,
            )
            total_tokens += t
            total_cost += c
            val_metrics = compute_metrics(val_y_true, val_preds)
            val_f1 = round(val_metrics.get("macro_f1", 0.0), 4)

            if val_acc + self.rollback_epsilon < current_val_acc:
                # Regression — rollback
                await record({
                    "round": r, "val_acc": val_acc, "val_macro_f1": val_f1,
                    "n_rules": len(rules),
                    "n_failures": len(failures), "n_candidate_rules": len(new_rules),
                    "action": "rollback", "regression": round(current_val_acc - val_acc, 4),
                })
            else:
                # Accept
                rules = candidate_rules
                current_prompt = candidate_prompt
                current_val_acc = val_acc
                await record({
                    "round": r, "val_acc": val_acc, "val_macro_f1": val_f1,
                    "n_rules": len(rules),
                    "n_failures": len(failures), "n_candidate_rules": len(new_rules),
                    "action": "accept", "delta": round(val_acc - base_acc, 4),
                })

        return OptimizationResult(
            optimizer_name=self.name,
            dimension=dimension,
            initial_prompt=initial_prompt,
            optimized_prompt=current_prompt,
            initial_score=base_acc,
            final_score=current_val_acc,
            trajectory=trajectory,
            artifact={"rule_library": rules, "n_rules": len(rules)},
            total_tokens=total_tokens,
            total_cost_usd=total_cost,
        )
