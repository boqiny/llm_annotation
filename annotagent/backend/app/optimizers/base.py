"""PromptOptimizer — abstract interface + shared eval harness.

All optimizers take (initial_prompt, trainset, valset) and return an
`OptimizationResult` containing the optimized prompt, per-round trajectory,
and whatever side-artifact the method produces (e.g. a Rule Library for
ReflectAgent, or a bundle of demos for MIPROv2).
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable, Optional

# Progress callback signature. Optimizers call this per round with partial state
# so the UI can poll trajectory / totals while optimization is still in flight.
ProgressCB = Callable[[dict], Awaitable[None]]

from app.engine.llm_client import call_llm
from app.engine.label_parser import parse_answer


@dataclass
class Example:
    """One (sentence, gold-label) pair for a single dimension."""
    sentence: str
    gold: str
    context: str = ""
    # Stable ID of the source data item. Lets the split guard assert
    # disjointness by item, not just by Python object identity (catches
    # duplicated rows and multi-label items exploded into several Examples).
    source_id: str = ""


@dataclass
class OptimizationResult:
    """What every optimizer returns."""
    optimizer_name: str
    dimension: str
    initial_prompt: str
    optimized_prompt: str
    initial_score: float
    final_score: float
    trajectory: list[dict[str, Any]] = field(default_factory=list)
    artifact: dict[str, Any] = field(default_factory=dict)  # Rule library, demos, …
    total_tokens: int = 0


class PromptOptimizer(ABC):
    """Abstract base. Subclasses implement optimize() and self-register via registry."""
    name: str = "abstract"

    def __init__(
        self,
        *,
        provider: str = "openai",
        model: str = "gpt-5.4-mini",
        api_key: str = "",
        budget: int = 20,
    ):
        self.provider = provider
        self.model = model
        self.api_key = api_key
        self.budget = budget

    @abstractmethod
    async def optimize(
        self,
        initial_prompt: str,
        dimension: str,
        valid_labels: list[str],
        trainset: list[Example],
        valset: list[Example],
        on_progress: Optional[ProgressCB] = None,
    ) -> OptimizationResult:
        ...


async def _emit(on_progress: Optional[ProgressCB], payload: dict) -> None:
    """Fire-and-forget helper — never raises, so optimizers can call it freely."""
    if on_progress is None:
        return
    try:
        await on_progress(payload)
    except Exception:
        # Progress reporting must not kill the optimizer
        pass


def audit_prompt_for_leakage(
    prompt: str, valset: list["Example"], testset: list["Example"], *, min_len: int = 20,
) -> dict:
    """Substring-scan the final prompt for any val/test sentence. Returns a
    dict with leak counts and offending samples. Empty findings = clean.

    ``min_len`` filters out very short sentences (a 5-char fragment may match
    by chance; we want substantive overlap). Sentences below ``min_len`` are
    counted in ``skipped_short`` so the audit's coverage is explicit.
    """
    p = (prompt or "").lower()
    val_hits: list[str] = []
    test_hits: list[str] = []
    skipped_short = 0
    for ex in valset:
        s = (ex.sentence or "").strip()
        if len(s) < min_len:
            skipped_short += 1
            continue
        if s.lower() in p:
            val_hits.append(s[:120])
    for ex in testset:
        s = (ex.sentence or "").strip()
        if len(s) < min_len:
            skipped_short += 1
            continue
        if s.lower() in p:
            test_hits.append(s[:120])
    return {
        "val_leak_count": len(val_hits),
        "test_leak_count": len(test_hits),
        "val_samples": val_hits[:5],     # first 5 examples for the UI
        "test_samples": test_hits[:5],
        "checked_val": len(valset),
        "checked_test": len(testset),
        "min_len": min_len,
        "skipped_short": skipped_short,
        "clean": len(val_hits) + len(test_hits) == 0,
    }


async def evaluate_prompt(
    prompt: str,
    examples: list[Example],
    valid_labels: list[str],
    *,
    provider: str,
    model: str,
    api_key: str,
    max_concurrency: int = 5,
) -> tuple[float, list[str], int, float]:
    """Run `prompt` on `examples`, return (accuracy, predictions, tokens, cost).

    Shared harness so every optimizer scores in the same way.
    """
    import asyncio
    semaphore = asyncio.Semaphore(max_concurrency)

    is_binary = len(valid_labels) == 2 and any("yes" in l.lower() for l in valid_labels)

    async def _score_one(ex: Example) -> tuple[str, int]:
        async with semaphore:
            user_msg = f"Sentence: {ex.sentence}"
            if ex.context:
                user_msg = f"Context: {ex.context}\n\n{user_msg}"
            try:
                resp = await call_llm(
                    messages=[
                        {"role": "system", "content": prompt},
                        {"role": "user", "content": user_msg},
                    ],
                    provider=provider, model=model, api_key=api_key, max_tokens=512,
                )
                label = parse_answer(resp.text, valid_labels, is_binary=is_binary)
                tokens = resp.input_tokens + resp.output_tokens
                return label, tokens
            except Exception:
                return "", 0

    results = await asyncio.gather(*(_score_one(ex) for ex in examples))
    preds = [r[0] for r in results]
    total_tokens = sum(r[1] for r in results)
    correct = sum(1 for p, ex in zip(preds, examples) if p == ex.gold)
    acc = correct / len(examples) if examples else 0.0
    return acc, preds, total_tokens
