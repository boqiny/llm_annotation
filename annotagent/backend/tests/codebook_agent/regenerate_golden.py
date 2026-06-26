"""Recapture the codebook-agent golden fixtures from Self-disclosure.xlsx.

Run this ONLY to intentionally update the golden after a drafter/prompt change.
It calls the live LLM (Call A + Call B), so it needs OPENAI_API_KEY. Review the
git diff on the fixture JSONs before committing — an unexpected change means a
regression, not a new baseline.

    cd annotagent/backend && python tests/codebook_agent/regenerate_golden.py
"""
from __future__ import annotations

import asyncio
import copy
import json
import sys
from pathlib import Path

# Allow running as a standalone script: put the backend dir (…/backend) on the path.
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from app.agents import codebook_agent as CA
from app.config import resolve_api_key
from app.engine.format_parsers import parse_file

FIX = Path(__file__).parent / "fixtures"
MODEL = "gpt-5.5"


async def main() -> None:
    key = resolve_api_key("openai")
    assert key, "OPENAI_API_KEY not set"
    data = (FIX / "Self-disclosure.xlsx").read_bytes()

    ingest = await parse_file(data, "Self-disclosure.xlsx")
    draft_a, err = await CA._draft_oneshot(ingest, provider="openai", model=MODEL, api_key=key)
    assert draft_a, f"Call A failed: {err}"
    dep_map = await CA._extract_dependency_map(
        ingest, draft_a, provider="openai", model=MODEL, api_key=key
    )

    golden = copy.deepcopy(draft_a)
    if dep_map.get("gated_dimensions"):
        CA._apply_dependency_map(golden, dep_map)
    CA._clean_hierarchy(golden)

    (FIX / "call_a_draft.json").write_text(json.dumps(draft_a, ensure_ascii=False, indent=2))
    (FIX / "call_b_depmap.json").write_text(json.dumps(dep_map, ensure_ascii=False, indent=2))
    (FIX / "golden_codebook.json").write_text(json.dumps(golden, ensure_ascii=False, indent=2))

    dims = [(d["name"], len(d["labels"]), d.get("gated_by", "")) for d in golden["dimensions"]]
    print("Regenerated golden fixtures:")
    for name, n, gated in dims:
        print(f"  {name:46} {n:3} labels" + (f"  (gated by {gated})" if gated else ""))


if __name__ == "__main__":
    asyncio.run(main())
