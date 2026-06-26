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
from app.agents.reflect_memory import apply_calibration_evidence, apply_rules_to_prompt
from app.optimizers.base import (
    Example, OptimizationResult, ProgressCB, PromptOptimizer,
    _emit, evaluate_prompt,
)

logger = logging.getLogger(__name__)


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
    evidence_text = f"""Failure batch ({len(failures)} items):
{failures_summary}

Gold is the correct label. Pred is the model prediction. Produce general calibration rules
that would prevent systematic confusions in this batch."""

    merged_rules = await apply_calibration_evidence(
        evidence_text=evidence_text,
        dimension_name=dimension,
        label_defs=label_defs,
        existing_rules=existing_rules,
        provider=provider,
        model=model,
        api_key=api_key,
        evidence_label="Optimizer failure evidence",
    )
    existing_by_id = {r.get("id"): r for r in existing_rules}
    return [
        r for r in merged_rules
        if (
            isinstance(r, dict)
            and r.get("boundary")
            and (
                r.get("id") not in existing_by_id
                or r != existing_by_id.get(r.get("id"))
            )
        )
    ]


_DEDUP_SYSTEM = """You are auditing an annotation rule library for redundant DUPLICATES.

You will receive a JSON array of rules. Each rule has:
  id, target_labels, boundary, positive_cues, negative_cues, rule

Your job is CONSERVATIVE deduplication. Only merge two rules when ALL of
these are true:
  1. Identical target_labels.
  2. The boundaries are paraphrases of the SAME distinction (one is a
     restatement of the other in different words; they would catch the
     same examples).
  3. The positive_cues and negative_cues describe the same families of
     surface signals.

If you have ANY doubt about whether two rules describe different cases,
KEEP THEM SEPARATE. The cost of leaving a near-duplicate is small; the
cost of collapsing two distinct rules is high (we lose coverage of the
edge case the second rule was capturing).

Most rule libraries should not change much under this pass — only
truly redundant rules should be merged.

When merging:
  - keep ONE id (pick the most descriptive of the merged set)
  - union target_labels
  - keep the clearest, most general boundary phrasing
  - dedupe positive_cues and negative_cues (preserve all unique cues)
  - merge the imperative `rule` text into the clearest single statement

Output ONLY the JSON array. Same schema as input. No prose, no markdown
fences, no commentary."""


async def _dedupe_rules_semantic(
    rules: list[dict], *, provider: str, model: str, api_key: str,
) -> tuple[list[dict], int]:
    """Ask the LLM to merge near-duplicate rules. Returns (deduped, tokens).
    On any failure (LLM error, JSON parse error, schema mismatch) returns the
    input rules unchanged — never reduces the library by accident.
    """
    if len(rules) <= 1:
        return rules, 0
    try:
        resp = await call_llm(
            messages=[
                {"role": "system", "content": _DEDUP_SYSTEM},
                {"role": "user",   "content": json.dumps(rules, indent=2)},
            ],
            provider=provider, model=model, api_key=api_key, max_tokens=4096,
        )
    except Exception as e:
        logger.warning(f"Rule dedup LLM call failed: {e}")
        return rules, 0

    text = (resp.text or "").strip()
    if text.startswith("```"):
        text = text.split("\n", 1)[1].rsplit("```", 1)[0].strip()
    try:
        deduped = json.loads(text)
    except json.JSONDecodeError:
        logger.warning("Rule dedup returned non-JSON; keeping input rules")
        return rules, resp.input_tokens + resp.output_tokens

    if not isinstance(deduped, list):
        return rules, resp.input_tokens + resp.output_tokens

    valid = [
        r for r in deduped
        if isinstance(r, dict) and r.get("rule") and r.get("boundary")
    ]
    # Sanity guard: dedup is supposed to be conservative — small reductions,
    # not radical collapses. Reject any reduction beyond 1/3 of the library.
    floor = max(3, (2 * len(rules)) // 3)
    if not valid or len(valid) > len(rules) or len(valid) < floor:
        logger.warning(
            f"Rule dedup produced suspect output ({len(rules)} → {len(valid)}, "
            f"floor={floor}); keeping input rules"
        )
        return rules, resp.input_tokens + resp.output_tokens

    logger.info(f"Rule dedup: {len(rules)} → {len(valid)}")
    return valid, resp.input_tokens + resp.output_tokens


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


async def _integrate_rules_into_prompt(
    *,
    initial_prompt: str,
    rules: list[dict],
    dimension: str,
    provider: str,
    model: str,
    api_key: str,
) -> str:
    """Use the same natural rewrite mechanism as human feedback for the final prompt."""
    if not rules:
        return initial_prompt
    rewritten = await apply_rules_to_prompt(
        base_prompt=initial_prompt,
        rules=rules,
        dimension_name=dimension,
        provider=provider,
        model=model,
        api_key=api_key,
    )
    return rewritten or (initial_prompt + _compile_rules(rules))


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
        use_few_shot_demos: bool = False,
        max_demos_per_rule: int = 1,
        max_total_demos: int = 8,
        use_val_consolidation: bool = True,
        **_ignored,
    ):
        super().__init__(provider=provider, model=model, api_key=api_key, budget=budget)
        self.rollback_epsilon = rollback_epsilon
        self.label_defs = label_defs
        # Cumulative rules carried in from prior reflect runs on this (project, dim).
        self.seed_rules = list(seed_rules or [])
        # Worked examples drawn from train (always) and val (only after the
        # val-consolidation pass has run). Test never enters the prompt.
        self.use_few_shot_demos = use_few_shot_demos
        self.max_demos_per_rule = max_demos_per_rule
        self.max_total_demos = max_total_demos
        # After the governor-gated loop converges, do one final pass over val:
        # mine its failures into rules and add val to the demo pool. Val is
        # consumed exactly once (in the final pass) — never during the loop —
        # so the per-round governor signal stays honest. Test still held out.
        self.use_val_consolidation = use_val_consolidation

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
        # Cached round-1 predictions on train — used to identify "originally
        # wrong" items, which make the most instructive worked examples.
        initial_train_preds: list[str] | None = None

        # Helper: record a trajectory row AND push live progress to the UI
        async def record(entry: dict) -> None:
            trajectory.append(entry)
            await _emit(on_progress, {
                "trajectory": list(trajectory),
                "total_tokens": total_tokens,
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
        base_acc, base_preds, t = await evaluate_prompt(
            current_prompt, valset, valid_labels,
            provider=self.provider, model=self.model, api_key=self.api_key,
        )
        total_tokens += t

        current_val_acc = base_acc
        base_metrics = compute_metrics(val_y_true, base_preds)

        await record({"round": 0, "val_acc": base_acc,
                      "val_macro_f1": round(base_metrics.get("macro_f1", 0.0), 4),
                      "n_rules": len(rules),
                      "action": "baseline_seeded" if rules else "baseline"})

        for r in range(1, self.budget + 1):
            # 1. Annotate the trainset with current prompt to find failures
            train_acc, preds, t = await evaluate_prompt(
                current_prompt, trainset, valid_labels,
                provider=self.provider, model=self.model, api_key=self.api_key,
            )
            total_tokens += t

            if initial_train_preds is None:
                initial_train_preds = list(preds)

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

            # 3. Merge rules. ID-merge first (cheap upsert by id), then ONLY
            # if the library has grown enough to plausibly contain duplicates,
            # ask the LLM to consolidate near-paraphrases. Skipping dedup for
            # small libraries prevents the optimizer from collapsing distinct
            # boundaries into one rule early on.
            merged = _merge_rules(rules, new_rules)
            if len(merged) >= 10:
                candidate_rules, dedup_tok = await _dedupe_rules_semantic(
                    merged,
                    provider=self.provider, model=self.model, api_key=self.api_key,
                )
                total_tokens += dedup_tok
            else:
                candidate_rules = merged
            candidate_prompt = initial_prompt + _compile_rules(candidate_rules)

            # 4. Governor: evaluate on val
            val_acc, val_preds, t = await evaluate_prompt(
                candidate_prompt, valset, valid_labels,
                provider=self.provider, model=self.model, api_key=self.api_key,
            )
            total_tokens += t
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

        # ─── Val consolidation (one final pass over val) ───
        # Once the governor-gated loop converges, mine val failures into rules
        # exactly once. This lets the rule library learn from val without
        # contaminating the per-round governor signal (which has finished its
        # job). Test still untouched.
        n_val_failures = 0
        n_val_rules = 0
        consolidation_round = self.budget + 1
        if self.use_val_consolidation and valset:
            val_acc_pre, val_preds_pre, t = await evaluate_prompt(
                current_prompt, valset, valid_labels,
                provider=self.provider, model=self.model, api_key=self.api_key,
            )
            total_tokens += t
            val_failures = [
                {"sentence": ex.sentence, "gold": ex.gold, "pred": p}
                for ex, p in zip(valset, val_preds_pre) if p != ex.gold
            ]
            n_val_failures = len(val_failures)

            if val_failures:
                val_new_rules = await _extract_patterns(
                    dimension=dimension, label_defs=self.label_defs,
                    failures=val_failures, existing_rules=rules,
                    provider=self.provider, model=self.model, api_key=self.api_key,
                )
                n_val_rules = len(val_new_rules)
                if val_new_rules:
                    merged = _merge_rules(rules, val_new_rules)
                    if len(merged) >= 10:
                        merged, dt = await _dedupe_rules_semantic(
                            merged,
                            provider=self.provider, model=self.model, api_key=self.api_key,
                        )
                        total_tokens += dt
                    rules = merged
                    current_prompt = initial_prompt + _compile_rules(rules)

            await record({
                "round": consolidation_round,
                "val_acc": val_acc_pre,
                "val_macro_f1": round(compute_metrics(val_y_true, val_preds_pre).get("macro_f1", 0.0), 4),
                "n_rules": len(rules),
                "n_failures": n_val_failures,
                "n_candidate_rules": n_val_rules,
                "action": "val_consolidation",
            })

        # ─── Worked examples augmentation ───
        # Pool train items always; add val items only if val-consolidation ran
        # (val has now been "used" — its sentences as demos can't bias the
        # governor's signal because the governor's role is done). Test stays
        # held out.
        demo_pool = list(trainset)
        if self.use_val_consolidation and valset:
            demo_pool = list(trainset) + list(valset)

        n_demos = 0
        if self.use_few_shot_demos and rules and demo_pool:
            picked = _pick_worked_examples(
                rules, demo_pool, initial_train_preds,
                max_per_rule=self.max_demos_per_rule,
                max_total=self.max_total_demos,
            )
            demos_block = _format_worked_examples(picked, dimension)
            if demos_block:
                current_prompt = current_prompt + demos_block
                n_demos = len(picked)

                val_acc, val_preds, t = await evaluate_prompt(
                    current_prompt, valset, valid_labels,
                    provider=self.provider, model=self.model, api_key=self.api_key,
                )
                total_tokens += t
                final_metrics = compute_metrics(val_y_true, val_preds)
                current_val_acc = val_acc
                await record({
                    "round": consolidation_round + 1 if self.use_val_consolidation and valset else self.budget + 1,
                    "val_acc": val_acc,
                    "val_macro_f1": round(final_metrics.get("macro_f1", 0.0), 4),
                    "n_rules": len(rules), "n_demos": n_demos,
                    "action": "demos_appended",
                    "delta": round(val_acc - base_acc, 4),
                })

        final_prompt = await _integrate_rules_into_prompt(
            initial_prompt=initial_prompt,
            rules=rules,
            dimension=dimension,
            provider=self.provider,
            model=self.model,
            api_key=self.api_key,
        )

        if final_prompt != current_prompt:
            val_acc, val_preds, t = await evaluate_prompt(
                final_prompt, valset, valid_labels,
                provider=self.provider, model=self.model, api_key=self.api_key,
            )
            total_tokens += t
            final_metrics = compute_metrics(val_y_true, val_preds)
            current_val_acc = val_acc
            await record({
                "round": consolidation_round + 2 if self.use_val_consolidation and valset else self.budget + 2,
                "val_acc": val_acc,
                "val_macro_f1": round(final_metrics.get("macro_f1", 0.0), 4),
                "n_rules": len(rules), "n_demos": n_demos,
                "action": "prompt_integrated",
                "delta": round(val_acc - base_acc, 4),
            })

        return OptimizationResult(
            optimizer_name=self.name,
            dimension=dimension,
            initial_prompt=initial_prompt,
            optimized_prompt=final_prompt,
            initial_score=base_acc,
            final_score=current_val_acc,
            trajectory=trajectory,
            artifact={"rule_library": rules, "n_rules": len(rules), "n_demos": n_demos},
            total_tokens=total_tokens,
        )


def _pick_worked_examples(
    rules: list[dict],
    trainset: list[Example],
    initial_train_preds: list[str] | None,
    *,
    max_per_rule: int,
    max_total: int,
) -> list[tuple[dict, Example]]:
    """Pick up to ``max_total`` train items total, distributed across rules.
    Prefers items the baseline got wrong (most instructive). Each rule gets
    up to ``max_per_rule`` demos. No item appears under more than one rule.
    """
    used_idx: set[int] = set()
    out: list[tuple[dict, Example]] = []
    for rule in rules:
        if len(out) >= max_total:
            break
        targets = {str(t) for t in (rule.get("target_labels") or [])}
        if not targets:
            continue
        candidates = [
            (i, ex) for i, ex in enumerate(trainset)
            if ex.gold in targets and i not in used_idx
        ]
        if initial_train_preds:
            candidates.sort(key=lambda iex: (
                0 if (iex[0] < len(initial_train_preds)
                      and initial_train_preds[iex[0]] != iex[1].gold) else 1,
                len(iex[1].sentence),
            ))
        room = min(max_per_rule, max_total - len(out))
        for i, ex in candidates[:room]:
            used_idx.add(i)
            out.append((rule, ex))
    return out


def _format_worked_examples(
    picked: list[tuple[dict, Example]],
    dimension: str,
) -> str:
    if not picked:
        return ""
    lines = [
        "",
        "## Worked examples",
        "Real cases reviewed by the system. Each anchors one of the rules above.",
        "",
    ]
    for i, (rule, ex) in enumerate(picked, 1):
        lines.append(f"Example {i} — rule: {rule.get('id', 'unnamed')}")
        if ex.context:
            lines.append(f"  Context: {ex.context}")
        # Cap sentence length so we don't blow the prompt.
        sentence = ex.sentence if len(ex.sentence) <= 400 else ex.sentence[:400] + "…"
        lines.append(f"  Sentence: {sentence}")
        lines.append(f"  Correct answer: {ex.gold}")
        if rule.get("boundary"):
            lines.append(f"  Why: {rule['boundary']}")
        lines.append("")
    return "\n".join(lines)
