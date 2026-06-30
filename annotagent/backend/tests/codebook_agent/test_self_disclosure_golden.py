"""Golden regression test for the codebook agent on ``Self-disclosure.xlsx``.

The two LLM calls — Call A (draft) and Call B (dependency map) — are
NON-deterministic, so this test does NOT invoke them. Instead it replays their
CAPTURED outputs (``fixtures/call_a_draft.json`` + ``fixtures/call_b_depmap.json``)
through the DETERMINISTIC transforms we keep editing (``_apply_dependency_map``,
``_clean_hierarchy``) and the decomposer, and asserts the result equals the
reviewed golden codebook. This guards every hand-written transform without LLM
flakiness or an API key.

To intentionally refresh the golden after a prompt/agent change, run
``python tests/codebook_agent/regenerate_golden.py`` (needs OPENAI_API_KEY) and
review the diff before committing.
"""
from __future__ import annotations

import copy
import json
import os
from pathlib import Path

import pytest

from app.agents.codebook_agent import (
    _apply_dependency_map,
    _clean_hierarchy,
    _run_critic,
    run_codebook_agent,
)
from app.agents.decomposition import decompose_codebook
from app.engine.codebook_parser import parse_codebook

FIX = Path(__file__).parent / "fixtures"


def _load(name: str) -> dict:
    return json.loads((FIX / name).read_text())


def _rebuild_from_captured() -> dict:
    """Deterministically rebuild the codebook from the captured LLM call outputs."""
    draft = copy.deepcopy(_load("call_a_draft.json"))
    dep = _load("call_b_depmap.json")
    if dep.get("gated_dimensions"):
        _apply_dependency_map(draft, dep)
    _clean_hierarchy(draft)
    return draft


# ── the strong guard: deterministic replay must reproduce the golden exactly ──

def test_deterministic_pipeline_matches_golden():
    assert _rebuild_from_captured() == _load("golden_codebook.json")


# ── reviewed contract: the structural intent of the golden ──
# These assertions derive dimension names FROM the golden rather than hard-coding
# them, because the drafting LLM varies its exact wording/casing run to run; what
# must hold is the STRUCTURE, not the strings.
#
# Topic taxonomy is a TWO-step gated cascade off the disclosure level:
#   Level of disclosure (gate) -> Topics (gated) -> Topic thematic categories
#       (gated by the same level, predicted with the chosen Topic as context).

def _gated_dims(g: dict) -> list[dict]:
    return [d for d in g["dimensions"] if d.get("gated_by")]


def _topics_dim(g: dict) -> dict:
    cands = [d for d in _gated_dims(g) if not d.get("context_dims")]
    assert len(cands) == 1, f"expected one fine gated dim, got {[d['name'] for d in cands]}"
    return cands[0]


def _category_dim(g: dict) -> dict:
    cands = [d for d in _gated_dims(g) if d.get("context_dims")]
    assert len(cands) == 1, f"expected one context-gated category dim, got {[d['name'] for d in cands]}"
    return cands[0]


def test_golden_dimensions_contract():
    g = _load("golden_codebook.json")
    names = [d["name"] for d in g["dimensions"]]
    # 4 disclosure themes + Topics + Temporality + Topic thematic categories.
    assert len(names) == 7
    # Exactly two gated dimensions, both gated by the same disclosure level.
    topics, cat = _topics_dim(g), _category_dim(g)
    assert topics["gated_by"] == cat["gated_by"]
    # The category is PREDICTED (gated), with the topic injected as context — not a
    # derived rollup.
    assert cat["context_dims"] == [topics["name"]]
    assert "thematic" in cat["name"].lower()
    assert not any(d.get("derived_from") for d in g["dimensions"])
    assert not any(d.get("category_dimension") for d in g["dimensions"])


def test_topics_subsets_key_on_gate_labels():
    g = _load("golden_codebook.json")
    topics = _topics_dim(g)
    gate_dim = next(d for d in g["dimensions"] if d["name"] == topics["gated_by"])
    gate_labels = {l["name"] for l in gate_dim["labels"]}
    gate_values = set()
    for l in topics["labels"]:
        assert len(l["path"]) == 1, f"expected [gate], got {l['path']}"
        gate_values.add(l["path"][0])
    assert gate_values == gate_labels == {"High", "Low", "No"}


def test_category_subsets_key_on_gate_labels():
    g = _load("golden_codebook.json")
    cat = _category_dim(g)
    gate_dim = next(d for d in g["dimensions"] if d["name"] == cat["gated_by"])
    gate_labels = {l["name"] for l in gate_dim["labels"]}
    gate_values = set()
    for l in cat["labels"]:
        assert len(l["path"]) == 1, f"expected [gate], got {l['path']}"
        gate_values.add(l["path"][0])
    assert gate_values == gate_labels == {"High", "Low", "No"}
    # the per-level category subset narrows: High discloses broader topical range
    # than No, so High lists strictly more categories.
    high = [l["name"] for l in cat["labels"] if l["path"][0] == "High"]
    no = [l["name"] for l in cat["labels"] if l["path"][0] == "No"]
    assert len(high) > len(no)


def test_no_self_referential_or_duplicate_topic_leaves():
    g = _load("golden_codebook.json")
    topics = _topics_dim(g)
    seen = set()
    for l in topics["labels"]:
        path_lc = [p.lower() for p in l["path"]]
        assert l["name"].lower() not in path_lc, f"self-referential leaf: {l['name']}"
        key = (l["name"].lower(), tuple(path_lc))
        assert key not in seen, f"duplicate leaf: {l['name']} @ {l['path']}"
        seen.add(key)


def test_critic_has_no_false_duplicate_warnings():
    # Same topic/category under different levels is legitimate, not a duplicate.
    flags = _run_critic(_load("golden_codebook.json"))
    dups = [f for f in flags if "Duplicate label name" in f["message"]]
    assert dups == [], dups


# ── the cascade wiring the runtime depends on ──

async def test_decompose_orders_and_gates_topics():
    g = _load("golden_codebook.json")
    cb = parse_codebook(g)
    steps = await decompose_codebook(cb)
    names = [s["name"] for s in steps]

    topics, cat = _topics_dim(g), _category_dim(g)
    gate_name = topics["gated_by"]
    # Level predicted first, then Topics, then the category (which needs Topics).
    assert names.index(gate_name) < names.index(topics["name"]) < names.index(cat["name"])

    ts = next(s for s in steps if s["name"] == topics["name"])
    assert ts.get("gate_by") == gate_name
    assert set(ts.get("conditional_prompts", {})) == {"High", "Low", "No"}

    # the per-level prompt is genuinely narrowed: pick a topic that is in High's
    # subset but NOT in No's, and assert it only shows in High's prompt.
    high = {l["name"] for l in topics["labels"] if l["path"][0] == "High"}
    no = {l["name"] for l in topics["labels"] if l["path"][0] == "No"}
    high_only = sorted(high - no)
    assert high_only, "expected at least one High-only topic"
    probe = high_only[0]
    assert probe in ts["conditional_prompts"]["High"]
    assert probe not in ts["conditional_prompts"]["No"]


async def test_decompose_category_is_gated_with_topic_context():
    g = _load("golden_codebook.json")
    cb = parse_codebook(g)
    steps = await decompose_codebook(cb)
    topics, cat = _topics_dim(g), _category_dim(g)

    cs = next(s for s in steps if s["name"] == cat["name"])
    assert cs.get("gate_by") == cat["gated_by"]
    assert cs.get("context_from") == [topics["name"]]          # topic injected as context
    assert set(cs.get("conditional_labels", {})) == {"High", "Low", "No"}

    # category is narrowed per level: every No-category is among the codebook's
    # categories, and High offers options No does not.
    high = set(cs["conditional_labels"]["High"])
    no = set(cs["conditional_labels"]["No"])
    assert high - no, "High should offer categories No does not"

    # the topic step no longer carries a derived category output — it is predicted.
    ts = next(s for s in steps if s["name"] == topics["name"])
    assert not ts.get("derived_dimensions")


def test_category_is_a_recognized_gated_dimension():
    # "Topic thematic categories" must be a real dimension for gold validation +
    # the schema UI, with the distinct categories as its labels.
    from app.engine.gold_align import _norm, build_gold_schema, schema_for_ui

    g = _load("golden_codebook.json")
    cat = _category_dim(g)
    cat_name = cat["name"]
    cats = {l["name"] for l in cat["labels"]}

    schema = build_gold_schema(g)
    assert cat_name in schema["dimensions"]
    assert set(schema["dimensions"][cat_name]["labels"]) == cats

    ui = schema_for_ui(g)
    assert any(d["name"] == cat_name for d in ui["dimensions"])

    # a gold column named "Topic thematic category" (singular) must norm-match it.
    assert schema["norm_dims"].get(_norm("Topic thematic category")) == cat_name


def test_golden_captured_examples():
    # The drafter should preserve the source's example/quote cells as few-shot
    # examples on the disclosure dimensions (identified by content, not header).
    g = _load("golden_codebook.json")
    total = sum(len(l.get("examples") or []) for d in g["dimensions"] for l in d["labels"])
    assert total > 0, "expected the drafter to capture example/quote cells"


async def test_few_shot_toggle_changes_prompt():
    cb = parse_codebook(_load("golden_codebook.json"))
    on = await decompose_codebook(cb, few_shot=True)
    off = await decompose_codebook(cb, few_shot=False)
    has_block = lambda steps: any("## Examples" in s["prompt"] for s in steps)
    assert has_block(on), "few_shot=True should add a '## Examples' block"
    assert not has_block(off), "few_shot=False should not inject examples"


# ── optional live test: actually run the agent (LLM + network + API key) ──

@pytest.mark.skipif(
    not os.environ.get("RUN_LLM_TESTS"),
    reason="live LLM test — set RUN_LLM_TESTS=1 (needs OPENAI_API_KEY) to run",
)
async def test_live_agent_structural_invariants():
    from app.config import resolve_api_key

    key = resolve_api_key("openai")
    data = (FIX / "Self-disclosure.xlsx").read_bytes()
    res = await run_codebook_agent(
        file_bytes=data, filename="Self-disclosure.xlsx",
        provider="openai", model="gpt-5.5", api_key=key,
    )
    assert res.ok, res.error_message
    cb = parse_codebook(res.draft_json)
    # loose invariants that must hold regardless of LLM wording: a "thematic"
    # dimension must be the gated (predicted) category, not a flat split or rollup.
    for d in cb.dimensions:
        if "thematic" in d.name.lower():
            assert d.gated_by, f"thematic dim {d.name!r} must be gated/predicted"
            assert d.context_dims, f"thematic dim {d.name!r} should take the topic as context"
    topics = [d for d in cb.dimensions
              if "topic" in d.name.lower() and "thematic" not in d.name.lower()]
    assert len(topics) == 1                                       # one merged Topic dim
    t = topics[0]
    assert t.gated_by, "Topics should be gated by the disclosure level"
    gate_values = {l.path[0] for l in t.labels if l.path}
    assert gate_values == {"High", "Low", "No"}
    for l in t.labels:                                            # no self-referential leaves
        assert l.name.lower() not in [p.lower() for p in l.path]
