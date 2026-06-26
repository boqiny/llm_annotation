# Codebook-agent golden regression test

Locks in the expected output of the codebook drafting agent for a known input,
so future edits to the agent (prompts, merge logic, cleanup, decomposer) can't
silently regress it.

## Input
`fixtures/Self-disclosure.xlsx` — a hierarchical, gated self-disclosure codebook
(Level / Depth / Intimacy / Confession + a `Topics` taxonomy gated by Level of
disclosure + Temporality).

## How it works
The agent makes two **non-deterministic** LLM calls:
- **Call A** — draft the codebook (dimensions, labels, definitions).
- **Call B** — extract the conditional-dependency (gate) map.

Their captured outputs are committed as fixtures:
- `fixtures/call_a_draft.json`
- `fixtures/call_b_depmap.json`
- `fixtures/golden_codebook.json` — the reviewed final codebook.

`test_self_disclosure_golden.py` replays the captured Call A + Call B outputs
through the **deterministic** transforms (`_apply_dependency_map`,
`_clean_hierarchy`) and the decomposer, and asserts the result equals the golden.
No LLM, no API key, no flakiness — it guards exactly the hand-written code we keep
editing.

There is also one **live** test (`test_live_agent_structural_invariants`),
skipped by default. Run it with `RUN_LLM_TESTS=1` (needs `OPENAI_API_KEY`) to
check the drafter prompts still produce the right *structure* against the real LLM.

## Running
```bash
cd annotagent/backend
.venv/bin/python -m pytest tests/codebook_agent -q            # deterministic only
RUN_LLM_TESTS=1 .venv/bin/python -m pytest tests/codebook_agent -q   # + live
```

## Updating the golden (intentional changes only)
If you deliberately change the agent and the new output is correct:
```bash
cd annotagent/backend
.venv/bin/python tests/codebook_agent/regenerate_golden.py   # needs OPENAI_API_KEY
git diff tests/codebook_agent/fixtures/                      # REVIEW before committing
```
An unexpected diff means a regression, not a new baseline.
