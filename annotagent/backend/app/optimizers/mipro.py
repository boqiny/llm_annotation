"""MIPROv2 baseline — thin wrapper around `dspy.teleprompt.MIPROv2`.

Opsahl-Ong et al. (2024). Jointly optimizes instructions AND few-shot demos
via Bayesian search. Reference:
https://dspy.ai/api/optimizers/MIPROv2/
"""
from __future__ import annotations

import logging

import dspy
from dspy.teleprompt import MIPROv2

from typing import Optional

from app.optimizers.base import (
    Example, OptimizationResult, ProgressCB, PromptOptimizer,
    _emit, evaluate_prompt,
)
from app.optimizers._dspy_shim import (
    build_lm, make_classifier_module, to_dspy_examples,
    exact_match_metric, extract_prompt_with_demos,
)

logger = logging.getLogger(__name__)


class MIPROOptimizer(PromptOptimizer):
    name = "mipro"

    def __init__(
        self,
        *,
        provider: str = "openai",
        model: str = "gpt-5.4-mini",
        api_key: str = "",
        budget: int = 0,           # ignored; DSPy uses auto budget
        auto_budget: str = "light",  # "light" | "medium" | "heavy"
        num_threads: int = 0,        # 0 = DSPy default; >0 parallelizes evals
        **_ignored,
    ):
        super().__init__(provider=provider, model=model, api_key=api_key, budget=budget)
        self.auto_budget = auto_budget
        self.num_threads = num_threads

    async def optimize(
        self,
        initial_prompt: str,
        dimension: str,
        valid_labels: list[str],
        trainset: list[Example],
        valset: list[Example],
        on_progress: Optional[ProgressCB] = None,
    ) -> OptimizationResult:
        base_acc, _, base_tokens = await evaluate_prompt(
            initial_prompt, valset, valid_labels,
            provider=self.provider, model=self.model, api_key=self.api_key,
        )
        await _emit(on_progress, {
            "trajectory": [
                {"round": 0, "val_acc": base_acc, "action": "baseline"},
                {"round": 1, "action": "mipro_compiling"},
            ],
            "total_tokens": base_tokens,
            "current_round": 1, "total_rounds": 2,
            "initial_score": base_acc, "final_score": base_acc,
        })

        lm = build_lm(self.provider, self.model, self.api_key)
        dspy.configure(lm=lm)

        student = make_classifier_module(dimension, valid_labels, initial_prompt=initial_prompt)
        ds_train = to_dspy_examples(trainset)
        ds_val = to_dspy_examples(valset)

        optimizer = MIPROv2(
            metric=exact_match_metric,
            auto=self.auto_budget,
            num_threads=(self.num_threads or None),
        )

        try:
            compiled = optimizer.compile(
                student=student, trainset=ds_train, valset=ds_val,
                requires_permission_to_run=False,   # never block on an interactive prompt
            )
            # MIPRO's contribution is instruction + bootstrapped demos; fold both into
            # the evaluated prompt so the demos actually take effect (not instruction-only).
            optimized_prompt, n_demos = extract_prompt_with_demos(compiled, initial_prompt)
        except Exception as e:
            logger.warning(f"MIPROv2 compile failed: {e}")
            optimized_prompt = initial_prompt
            n_demos = 0

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
                {"round": 1, "val_acc": final_acc, "action": "post_mipro",
                 "delta": round(final_acc - base_acc, 4), "n_demos": n_demos},
            ],
            artifact={"auto_budget": self.auto_budget, "n_demos_bootstrapped": n_demos},
            total_tokens=base_tokens + extra_tokens,
        )
