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

def _gated_dim(g: dict) -> dict:
    gated = [d for d in g["dimensions"] if d.get("gated_by")]
    assert len(gated) == 1, f"expected exactly one gated dimension, got {[d['name'] for d in gated]}"
    return gated[0]


def test_golden_dimensions_contract():
    g = _load("golden_codebook.json")
    names = [d["name"] for d in g["dimensions"]]
    # 6 dimensions; thematic categories are NOT a separate flat dimension (they
    # live as the topic leaves' path parents + a derived output, not a dimension).
    assert len(names) == 6
    assert not any("thematic" in n.lower() for n in names)
    _gated_dim(g)  # exactly one gated dimension


def test_gated_dim_subsets_match_gate_labels():
    g = _load("golden_codebook.json")
    topics = _gated_dim(g)
    gate_dim = next(d for d in g["dimensions"] if d["name"] == topics["gated_by"])
    gate_labels = {l["name"] for l in gate_dim["labels"]}
    gate_values = set()
    for l in topics["labels"]:
        assert len(l["path"]) == 2, f"expected [gate, category], got {l['path']}"
        gate_values.add(l["path"][0])
    # the disclosure scale is High/Low/No, and the topic subsets key on exactly it
    assert gate_values == gate_labels == {"High", "Low", "No"}


def test_derived_category_dimension_is_set():
    g = _load("golden_codebook.json")
    topics = _gated_dim(g)
    assert topics.get("category_dimension"), "gated dim should name its parent-category output"
    # every leaf carries a category (path[-1]) to derive that output from
    assert all(len(l["path"]) >= 2 and l["path"][-1] for l in topics["labels"])


def test_no_self_referential_or_duplicate_topic_leaves():
    g = _load("golden_codebook.json")
    topics = _gated_dim(g)
    seen = set()
    for l in topics["labels"]:
        path_lc = [p.lower() for p in l["path"]]
        assert l["name"].lower() not in path_lc, f"self-referential leaf: {l['name']}"
        key = (l["name"].lower(), tuple(path_lc))
        assert key not in seen, f"duplicate leaf: {l['name']} @ {l['path']}"
        seen.add(key)


def test_critic_has_no_false_duplicate_warnings():
    # Same topic under different levels is legitimate, not a duplicate.
    flags = _run_critic(_load("golden_codebook.json"))
    dups = [f for f in flags if "Duplicate label name" in f["message"]]
    assert dups == [], dups


# ── the cascade wiring the runtime depends on ──

async def test_decompose_orders_and_gates_topics():
    g = _load("golden_codebook.json")
    cb = parse_codebook(g)
    steps = await decompose_codebook(cb)
    names = [s["name"] for s in steps]

    gated_name = _gated_dim(g)["name"]
    gate_name = _gated_dim(g)["gated_by"]
    assert names.index(gate_name) < names.index(gated_name)  # gate predicted first

    topic = next(s for s in steps if s["name"] == gated_name)
    assert topic.get("gate_by") == gate_name
    assert set(topic.get("conditional_prompts", {})) == {"High", "Low", "No"}

    # the per-level prompt is genuinely narrowed: pick a topic that is in High's
    # subset but NOT in No's, and assert it only shows in High's prompt.
    topics_dim = _gated_dim(g)
    high = {l["name"] for l in topics_dim["labels"] if l["path"][0] == "High"}
    no = {l["name"] for l in topics_dim["labels"] if l["path"][0] == "No"}
    high_only = sorted(high - no)
    assert high_only, "expected at least one High-only topic"
    probe = high_only[0]
    assert probe in topic["conditional_prompts"]["High"]
    assert probe not in topic["conditional_prompts"]["No"]


def test_derived_category_is_a_recognized_dimension():
    # "Topic thematic categories" must be exposed as a real dimension (for gold
    # validation + the schema UI), derived from the gated Topics dimension.
    from app.engine.gold_align import build_gold_schema, schema_for_ui

    g = _load("golden_codebook.json")
    topics = _gated_dim(g)
    cat_name = topics["category_dimension"]
    cats = []
    for l in topics["labels"]:
        if len(l["path"]) > 1 and l["path"][-1] not in cats:
            cats.append(l["path"][-1])

    schema = build_gold_schema(g)
    assert cat_name in schema["dimensions"]
    assert set(schema["dimensions"][cat_name]["labels"]) == set(cats)

    ui = schema_for_ui(g)
    ui_dim = next((d for d in ui["dimensions"] if d["name"] == cat_name), None)
    assert ui_dim is not None
    assert ui_dim.get("derived_from") == topics["name"]

    # a gold column named "Topic thematic category" (singular) must norm-match it.
    from app.engine.gold_align import _norm
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


async def test_decompose_emits_derived_category_output():
    g = _load("golden_codebook.json")
    cb = parse_codebook(g)
    steps = await decompose_codebook(cb)
    topic = next(s for s in steps if s["name"] == _gated_dim(g)["name"])
    derived = topic.get("derived_dimensions") or []
    assert len(derived) == 1
    d = derived[0]
    assert d["name"] == _gated_dim(g)["category_dimension"]
    assert d["from"] == topic["name"]
    # the map sends each topic leaf to its parent category
    assert d["map"], "derived category map should be non-empty"


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
    names = [d.name for d in cb.dimensions]
    # loose invariants that must hold regardless of LLM wording:
    assert not any("thematic" in n.lower() for n in names)        # no split thematic dim
    topics = [d for d in cb.dimensions if "topic" in d.name.lower()]
    assert len(topics) == 1                                       # one merged Topic dim
    t = topics[0]
    assert t.gated_by, "Topics should be gated by the disclosure level"
    gate_values = {l.path[0] for l in t.labels if l.path}
    assert gate_values == {"High", "Low", "No"}
    # no self-referential leaves
    for l in t.labels:
        assert l.name.lower() not in [p.lower() for p in l.path]
