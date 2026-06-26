"""GEPA baseline — thin wrapper around `dspy.GEPA`.

Agrawal et al. (2025). DSPy's GEPA evolves prompts via reflective critique
and Pareto-front selection. Reference API:
https://dspy.ai/api/optimizers/GEPA/overview/
"""
from __future__ import annotations

import logging

import dspy

from typing import Optional

from app.optimizers.base import (
    Example, OptimizationResult, ProgressCB, PromptOptimizer,
    _emit, evaluate_prompt,
)
from app.optimizers._dspy_shim import (
    build_lm, make_classifier_module, to_dspy_examples,
    exact_match_metric, extract_instruction,
)

logger = logging.getLogger(__name__)


class GEPAOptimizer(PromptOptimizer):
    name = "gepa"

    def __init__(
        self,
        *,
        provider: str = "openai",
        model: str = "gpt-5.4-mini",
        api_key: str = "",
        budget: int = 0,           # ignored; we use DSPy's auto-budget
        auto_budget: str = "light",  # "light" | "medium" | "heavy"
        **_ignored,
    ):
        super().__init__(provider=provider, model=model, api_key=api_key, budget=budget)
        self.auto_budget = auto_budget

    async def optimize(
        self,
        initial_prompt: str,
        dimension: str,
        valid_labels: list[str],
        trainset: list[Example],
        valset: list[Example],
        on_progress: Optional[ProgressCB] = None,
    ) -> OptimizationResult:
        # Baseline score with the given initial prompt (pre-optimization)
        base_acc, _, base_tokens = await evaluate_prompt(
            initial_prompt, valset, valid_labels,
            provider=self.provider, model=self.model, api_key=self.api_key,
        )
        await _emit(on_progress, {
            "trajectory": [{"round": 0, "val_acc": base_acc, "action": "baseline"}],
            "total_tokens": base_tokens,
            "current_round": 0,
            "total_rounds": 2,
            "initial_score": base_acc,
            "final_score": base_acc,
        })
        await _emit(on_progress, {
            "trajectory": [
                {"round": 0, "val_acc": base_acc, "action": "baseline"},
                {"round": 1, "action": "gepa_compiling"},
            ],
            "current_round": 1, "total_rounds": 2,
        })

        # Configure DSPy LM
        lm = build_lm(self.provider, self.model, self.api_key)
        dspy.configure(lm=lm)

        student = make_classifier_module(dimension, valid_labels)
        ds_train = to_dspy_examples(trainset)
        ds_val = to_dspy_examples(valset)

        reflection_lm = build_lm(self.provider, self.model, self.api_key)
        gepa = dspy.GEPA(
            metric=exact_match_metric,
            reflection_lm=reflection_lm,
            auto=self.auto_budget,
            track_stats=True,
        )

        try:
            compiled = gepa.compile(student=student, trainset=ds_train, valset=ds_val)
            optimized_prompt = extract_instruction(compiled, initial_prompt)
        except Exception as e:
            logger.warning(f"GEPA compile failed: {e}")
            optimized_prompt = initial_prompt

        final_acc, _, extra_tokens = await evaluate_prompt(
            optimized_prompt, valset, valid_labels,
            provider=self.provider, model=self.model, api_key=self.api_key,
        )

        return OptimizationResult(
            optimizer_name=self.name,
            dimension=dimension,
            initial_prompt=initial_prompt,
            optimized_prompt=optimized_prompt,
            initial_score=base_acc,
            final_score=final_acc,
            trajectory=[
                {"round": 0, "val_acc": base_acc, "action": "baseline"},
                {"round": 1, "val_acc": final_acc, "action": "post_gepa",
                 "delta": round(final_acc - base_acc, 4)},
            ],
            artifact={"auto_budget": self.auto_budget},
            total_tokens=base_tokens + extra_tokens,
        )
