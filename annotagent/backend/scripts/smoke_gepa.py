"""Smoke test for the GEPA baseline optimizer.

Runs the real `dspy.GEPA` loop (auto="light") on a tiny subset of the
self-disclosure seed for one single-label dimension, to verify the wiring
end-to-end: fair seeding from the initial prompt, the {score, feedback}
metric, compile, instruction extraction, and before/after scoring through the
shared eval harness.

Run from the backend dir:
    .venv/bin/python scripts/smoke_gepa.py
"""
from __future__ import annotations

import asyncio
import json
import os
import sys
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]
REPO = BACKEND.parents[1]
sys.path.insert(0, str(BACKEND))


def _load_key() -> str:
    # Key lives in the repo-level .env per the user.
    for env in (REPO / ".env", BACKEND.parent / ".env"):
        if env.exists():
            for line in env.read_text().splitlines():
                if line.strip().startswith("OPENAI_API_KEY="):
                    val = line.split("=", 1)[1].strip().strip('"').strip("'")
                    if val:
                        return val
    return os.environ.get("OPENAI_API_KEY", "")


DIMENSION = "Level of disclosure"
LABELS = ["No", "Low", "High"]
INITIAL_PROMPT = (
    "You are annotating the LEVEL OF DISCLOSURE of a user message in a conversation. "
    "Choose exactly one label: No, Low, or High. "
    "'No' = an empty or generic reaction with no personal content. "
    "'Low' = the speaker shares a preference, opinion, or minor personal detail. "
    "'High' = the speaker shares significant personal experience, feelings, or sensitive "
    "information. Answer with only the label."
)


def _build_examples():
    from app.optimizers.base import Example
    records = json.loads((BACKEND.parent / "seed" / "self_disclosure_demo.json").read_text())
    exs = []
    for r in records:
        gold = (r.get("gold_labels") or {}).get(DIMENSION)
        if gold in LABELS:
            exs.append(Example(sentence=r["content"], gold=gold, context=r.get("context", "")))
    # tiny split: first 6 train, rest val
    return exs[:6], exs[6:]


async def main() -> None:
    key = _load_key()
    if not key:
        print("FAIL: no OPENAI_API_KEY found in repo .env")
        sys.exit(1)
    os.environ["OPENAI_API_KEY"] = key

    from app.optimizers.gepa import GEPAOptimizer

    train, val = _build_examples()
    print(f"[smoke] dimension={DIMENSION!r} labels={LABELS} | train={len(train)} val={len(val)}")
    if not train or not val:
        print("FAIL: not enough labeled examples in seed")
        sys.exit(1)

    opt = GEPAOptimizer(
        provider="openai", model="gpt-5.4-mini", api_key=key, auto_budget="light",
    )

    events: list[dict] = []

    async def on_progress(payload: dict) -> None:
        cur = payload.get("current_round")
        events.append({"round": cur, "keys": sorted(payload.keys())})

    result = await opt.optimize(
        initial_prompt=INITIAL_PROMPT,
        dimension=DIMENSION,
        valid_labels=LABELS,
        trainset=train,
        valset=val,
        on_progress=on_progress,
    )

    out = {
        "optimizer": result.optimizer_name,
        "dimension": result.dimension,
        "initial_score": round(result.initial_score, 4),
        "final_score": round(result.final_score, 4),
        "delta": round(result.final_score - result.initial_score, 4),
        "total_tokens": result.total_tokens,
        "trajectory": result.trajectory,
        "artifact": result.artifact,
        "initial_prompt": result.initial_prompt,
        "optimized_prompt": result.optimized_prompt,
        "seeded_from_initial": result.optimized_prompt.strip() != INITIAL_PROMPT.strip(),
        "n_train": len(train),
        "n_val": len(val),
    }
    print("\n===== GEPA SMOKE RESULT =====")
    print(json.dumps({k: v for k, v in out.items() if k != "optimized_prompt"}, indent=2))
    print("\n--- optimized prompt (first 600 chars) ---")
    print(result.optimized_prompt[:600])

    Path(BACKEND / "scripts" / "smoke_gepa_result.json").write_text(json.dumps(out, indent=2))
    print("\n[smoke] wrote scripts/smoke_gepa_result.json")
    print("[smoke] PASS" if result.final_score >= 0 else "[smoke] CHECK")


if __name__ == "__main__":
    asyncio.run(main())
