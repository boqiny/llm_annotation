"""Prompt optimization workbench: a pluggable `PromptOptimizer` interface
with 3 SOTA baselines (GEPA, MIPROv2, OPRO) and our method (ReflectAgent)."""
from app.optimizers.base import (
    Example, OptimizationResult, PromptOptimizer, evaluate_prompt,
)
from app.optimizers.registry import get_optimizer, list_optimizers

__all__ = [
    "Example",
    "OptimizationResult",
    "PromptOptimizer",
    "evaluate_prompt",
    "get_optimizer",
    "list_optimizers",
]
