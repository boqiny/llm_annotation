"""Name → PromptOptimizer class registry. Lazy-imports each backend so missing
DSPy doesn't crash the whole module."""
from __future__ import annotations

from typing import Type

from app.optimizers.base import PromptOptimizer


def _load(name: str) -> Type[PromptOptimizer]:
    if name == "reflect_agent":
        from app.optimizers.reflect_agent import ReflectAgent
        return ReflectAgent
    if name == "gepa":
        from app.optimizers.gepa import GEPAOptimizer
        return GEPAOptimizer
    if name == "mipro":
        from app.optimizers.mipro import MIPROOptimizer
        return MIPROOptimizer
    if name == "opro":
        from app.optimizers.opro import OPROOptimizer
        return OPROOptimizer
    raise KeyError(f"Unknown optimizer: {name}")


def get_optimizer(name: str, **kwargs) -> PromptOptimizer:
    cls = _load(name)
    return cls(**kwargs)


def list_optimizers() -> list[dict[str, str]]:
    return [
        {"name": "reflect_agent", "label": "ReflectAgent (ours)",
         "description": "Rule-distillation loop: mine failure patterns, emit generalizable rules, Governor-gated rollback.",
         "role": "method"},
        {"name": "gepa", "label": "GEPA (2025)",
         "description": "Evolutionary search with reflective LLM critique (via DSPy).",
         "role": "baseline"},
        {"name": "mipro", "label": "MIPROv2 (2024)",
         "description": "Joint Bayesian search over instructions and few-shot demo subsets (via DSPy).",
         "role": "baseline"},
        {"name": "opro", "label": "OPRO (2024)",
         "description": "LLM-as-optimizer: meta-prompt conditioned on (prompt, score) trajectory.",
         "role": "baseline"},
    ]
