"""OPRO — Large Language Models as Optimizers (Yang et al., 2024).

The LLM is shown a trajectory of past `(prompt, score)` pairs and asked to
propose a new, better prompt. No textual gradients, no demos — just
trajectory-conditioned search.

Reference: https://arxiv.org/abs/2309.03409
"""
from __future__ import annotations

import logging

from typing import Optional

from app.engine.llm_client import call_llm
from app.optimizers.base import (
    Example, OptimizationResult, ProgressCB, PromptOptimizer,
    _emit, evaluate_prompt,
)

logger = logging.getLogger(__name__)


_META_SYSTEM = """You are an expert prompt optimizer.

You will be shown past prompt candidates and their accuracy on a classification
task. Your job is to propose a NEW prompt that achieves higher accuracy.

Study the trajectory: which prompt formulations scored highly and which didn't?
Your new prompt should build on the best patterns you observe. Return ONLY the
new prompt text — no explanation, no preamble, no markdown fences."""


def _format_trajectory(trajectory: list[tuple[str, float]], k: int = 8) -> str:
    """Include up to k past (prompt, score) pairs, sorted ascending by score."""
    sorted_traj = sorted(trajectory, key=lambda x: x[1])
    if len(sorted_traj) > k:
        sorted_traj = sorted_traj[:k // 2] + sorted_traj[-(k - k // 2):]
    lines = []
    for i, (p, s) in enumerate(sorted_traj, 1):
        lines.append(f"--- Candidate {i} (accuracy: {s:.3f}) ---\n{p}\n")
    return "\n".join(lines)


class OPROOptimizer(PromptOptimizer):
    """LLM-as-optimizer: propose next prompt conditioned on trajectory."""
    name = "opro"

    def __init__(
        self,
        *,
        provider: str = "openai",
        model: str = "gpt-5.4-mini",
        api_key: str = "",
        budget: int = 8,   # proposal rounds
        **_ignored,
    ):
        super().__init__(provider=provider, model=model, api_key=api_key, budget=budget)

    async def _propose(
        self, trajectory: list[tuple[str, float]], task_description: str,
    ) -> tuple[str, int, float]:
        traj_block = _format_trajectory(trajectory)
        user_msg = f"""Task: {task_description}

Past candidates (sorted ascending by accuracy):
{traj_block}

Propose a new prompt that should outperform the best candidate above.
Return ONLY the prompt text."""

        resp = await call_llm(
            messages=[
                {"role": "system", "content": _META_SYSTEM},
                {"role": "user", "content": user_msg},
            ],
            provider=self.provider, model=self.model, api_key=self.api_key,
            max_tokens=2048,
        )
        text = resp.text.strip()
        if text.startswith("```"):
            text = text.split("\n", 1)[1].rsplit("```", 1)[0]
        tokens = resp.input_tokens + resp.output_tokens
        return text.strip(), tokens, resp.cost_usd

    async def optimize(
        self,
        initial_prompt: str,
        dimension: str,
        valid_labels: list[str],
        trainset: list[Example],
        valset: list[Example],
        on_progress: Optional[ProgressCB] = None,
    ) -> OptimizationResult:
        total_tokens = 0
        total_cost = 0.0
        trajectory_trace: list[dict] = []
        candidates: list[tuple[str, float]] = []

        async def report(current_best: str, current_best_acc: float) -> None:
            await _emit(on_progress, {
                "trajectory": list(trajectory_trace),
                "total_tokens": total_tokens,
                "total_cost_usd": total_cost,
                "current_round": trajectory_trace[-1].get("round", 0) if trajectory_trace else 0,
                "total_rounds": self.budget,
                "optimized_prompt": current_best,
                "initial_score": candidates[0][1] if candidates else 0.0,
                "final_score": current_best_acc,
            })

        # Seed the trajectory with the initial prompt
        acc, _, t, c = await evaluate_prompt(
            initial_prompt, valset, valid_labels,
            provider=self.provider, model=self.model, api_key=self.api_key,
        )
        total_tokens += t
        total_cost += c
        candidates.append((initial_prompt, acc))
        trajectory_trace.append({"round": 0, "val_acc": acc, "action": "baseline"})
        best_prompt, best_acc = initial_prompt, acc
        await report(best_prompt, best_acc)

        task_description = (
            f"Classify a sentence on the dimension '{dimension}' into one of: "
            f"{', '.join(valid_labels)}."
        )

        for r in range(1, self.budget + 1):
            try:
                new_prompt, t, c = await self._propose(candidates, task_description)
                total_tokens += t
                total_cost += c
            except Exception as e:
                logger.warning(f"OPRO proposal failed round {r}: {e}")
                trajectory_trace.append({"round": r, "action": "proposal_failed"})
                await report(best_prompt, best_acc)
                continue

            if not new_prompt or new_prompt in {p for p, _ in candidates}:
                trajectory_trace.append({"round": r, "action": "duplicate_skip"})
                await report(best_prompt, best_acc)
                continue

            acc, _, t, c = await evaluate_prompt(
                new_prompt, valset, valid_labels,
                provider=self.provider, model=self.model, api_key=self.api_key,
            )
            total_tokens += t
            total_cost += c
            candidates.append((new_prompt, acc))

            if acc > best_acc:
                best_prompt, best_acc = new_prompt, acc
                trajectory_trace.append({"round": r, "val_acc": acc, "action": "improve",
                                         "delta": round(acc - candidates[0][1], 4)})
            else:
                trajectory_trace.append({"round": r, "val_acc": acc, "action": "reject"})
            await report(best_prompt, best_acc)

        return OptimizationResult(
            optimizer_name=self.name,
            dimension=dimension,
            initial_prompt=initial_prompt,
            optimized_prompt=best_prompt,
            initial_score=candidates[0][1],
            final_score=best_acc,
            trajectory=trajectory_trace,
            artifact={"n_candidates": len(candidates)},
            total_tokens=total_tokens,
            total_cost_usd=total_cost,
        )
