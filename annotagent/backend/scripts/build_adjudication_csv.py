"""Build an adjudication CSV for the DISPUTED (disagreed) self-disclosure items.

For each item where Fiona and Chang disagree on a dimension, the LLM acts as a
third annotator. It runs a ReflectAgent-refined prompt learned from the AGREED
subset, then emits a verdict, a confidence, a short reasoning, and the rules it
cited. The output is one CSV row per disputed item, with a blank `final_label`
column for Fiona to fill. Feeding Fiona's adjudicated labels back grows the gold
set the C2 evaluation runs on.

This is a labeling-assist tool, not an automatic adjudicator: every row still
needs a human decision.

Run from annotagent/backend:
    # one dimension
    python -m scripts.build_adjudication_csv \
        --dimension "Disclosure as confession" \
        --model gpt-5.4-mini --budget 5 \
        --out runs/adjudicate_confession.csv

    # all four dimensions (one CSV each under runs/)
    python -m scripts.build_adjudication_csv --model gpt-5.4-mini --budget 5
"""
from __future__ import annotations

import argparse
import asyncio
import csv
import json
import random
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.config import resolve_api_key
from app.engine.codebook_parser import parse_codebook
from app.engine.prompt_generator import generate_dimension_prompt
from app.engine.llm_client import call_llm
from app.engine.label_parser import parse_answer
from app.optimizers import Example, get_optimizer

DATA = Path("../assets/data/cleaned")
FIONA = DATA / "fiona_self_disclosure_ground_truth.json"
CHANG = DATA / "chang_self_disclosure_ground_truth.json"
AGREED = DATA / "agreed_self_disclosure_ground_truth.json"

ALL_DIMS = [
    "Level of disclosure",
    "Disclosure as confession",
    "Depth of disclosure",
    "Intimacy of self-disclosure",
]
# Dimensions whose raw labels read "<Canonical> layer/level"; take the first word
# so they match the preset labels (Peripheral / Intermediate / Central / Core).
_FIRSTWORD_DIMS = {"Depth of disclosure", "Intimacy of self-disclosure"}


def canon(dim: str, value) -> str | None:
    """Normalize a raw annotator label to the preset label vocabulary."""
    if value is None:
        return None
    v = str(value).strip()
    if not v:
        return None
    return v.split()[0] if dim in _FIRSTWORD_DIMS else v


def _load(path: Path) -> list[dict]:
    d = json.load(open(path))
    return d["items"] if isinstance(d, dict) else d


def disputed_items(dim: str) -> list[dict]:
    """Items (joined on sentence) where Fiona and Chang give different labels."""
    fiona = {it["sentence"]: it for it in _load(FIONA) if it.get("sentence")}
    chang = {it["sentence"]: it for it in _load(CHANG) if it.get("sentence")}
    rows: list[dict] = []
    for s in sorted(set(fiona) & set(chang)):
        fl = canon(dim, (fiona[s].get("labels") or {}).get(dim))
        cl = canon(dim, (chang[s].get("labels") or {}).get(dim))
        if fl and cl and fl != cl:
            rows.append({
                "sentence": s,
                "fiona": fl,
                "chang": cl,
            })
    return rows


def agreed_examples(dim: str) -> list[Example]:
    out: list[Example] = []
    for it in _load(AGREED):
        c = canon(dim, (it.get("labels") or {}).get(dim))
        if c:
            out.append(Example(sentence=it.get("sentence", ""), gold=c,
                               context=str(it.get("topic", ""))))
    return out


def _split(examples: list[Example], frac_train: float = 0.7, seed: int = 17):
    """Stratified train/val split (no test — we only mine rules here)."""
    by: dict[str, list[Example]] = {}
    for e in examples:
        by.setdefault(e.gold, []).append(e)
    rng = random.Random(seed)
    train: list[Example] = []
    val: list[Example] = []
    for cls in sorted(by):
        group = list(by[cls])
        rng.shuffle(group)
        n = len(group)
        if n < 2:
            train.extend(group)
            continue
        nt = min(n - 1, max(1, round(frac_train * n)))
        train.extend(group[:nt])
        val.extend(group[nt:])
    rng.shuffle(train)
    rng.shuffle(val)
    return train, val


async def refine_prompt(dim_def, dim, *, provider, model, api_key, budget):
    """ReflectAgent on the agreed subset → (refined prompt, valid labels, rules)."""
    initial = generate_dimension_prompt(dim_def)
    valid = [l.name for l in dim_def.labels]
    label_defs = "\n".join(f"- {l.name}: {l.definition}" for l in dim_def.labels)
    train, val = _split(agreed_examples(dim))
    opt = get_optimizer("reflect_agent", provider=provider, model=model,
                        api_key=api_key, budget=budget, label_defs=label_defs)
    res = await opt.optimize(initial, dim, valid, train, val)
    rules = (res.artifact or {}).get("rule_library", [])
    return res.optimized_prompt, valid, rules


_ADJ = """{prompt}

You are a third annotator helping resolve a disagreement between two trained \
human coders on the dimension "{dim}". Apply the rules and definitions above to \
THIS item only.

Respond with ONLY a JSON object and nothing else:
{{"verdict": "<one of: {labels}>", "confidence": <0.0-1.0>, \
"reasoning": "<2-3 sentences grounded in the rules above>", \
"cited_rules": ["<short phrase of each rule you relied on>"]}}"""


def _extract_json(text: str):
    m = re.search(r"\{.*\}", text or "", re.S)
    if not m:
        return None
    try:
        return json.loads(m.group(0))
    except Exception:
        return None


async def adjudicate(item, prompt, dim, valid, *, provider, model, api_key):
    sys_prompt = _ADJ.format(prompt=prompt, dim=dim, labels=", ".join(valid))
    user = f"Sentence: {item['sentence']}"
    is_binary = len(valid) == 2 and any("yes" in l.lower() for l in valid)
    try:
        resp = await call_llm(
            messages=[{"role": "system", "content": sys_prompt},
                      {"role": "user", "content": user}],
            provider=provider, model=model, api_key=api_key, max_tokens=600,
        )
        obj = _extract_json(resp.text) or {}
        verdict = str(obj.get("verdict", "")).strip() or parse_answer(
            resp.text, valid, is_binary=is_binary)
        cited = obj.get("cited_rules", [])
        cited = "; ".join(str(c) for c in cited) if isinstance(cited, list) else str(cited)
        return {
            "verdict": verdict,
            "confidence": obj.get("confidence", ""),
            "reasoning": str(obj.get("reasoning", "")).strip(),
            "cited_rules": cited,
        }
    except Exception as e:  # noqa: BLE001
        return {"verdict": "", "confidence": "", "reasoning": f"[error: {e}]",
                "cited_rules": ""}


async def process_dim(dim, codebook, args, api_key) -> None:
    dim_def = next((d for d in codebook.dimensions if d.name == dim), None)
    if dim_def is None:
        print(f"skip '{dim}': not in codebook")
        return
    disputed = disputed_items(dim)
    if args.limit:
        disputed = disputed[: args.limit]
    if not disputed:
        print(f"'{dim}': 0 disputed items — nothing to write")
        return
    print(f"'{dim}': {len(disputed)} disputed items; refining prompt on agreed "
          f"subset (budget {args.budget})...")
    prompt, valid, rules = await refine_prompt(
        dim_def, dim, provider=args.provider, model=args.model,
        api_key=api_key, budget=args.budget)
    print(f"  {len(rules)} rules learned; adjudicating {len(disputed)} items...")

    sem = asyncio.Semaphore(5)

    async def _one(it):
        async with sem:
            return it, await adjudicate(it, prompt, dim, valid,
                                        provider=args.provider, model=args.model,
                                        api_key=api_key)

    results = await asyncio.gather(*(_one(it) for it in disputed))

    out = (Path(args.out) if (args.out and args.dimension)
           else Path("runs") / f"adjudicate_{dim.replace(' ', '_')}.csv")
    out.parent.mkdir(parents=True, exist_ok=True)
    with open(out, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["#", "sentence", "final_label", "notes", "fiona_label",
                    "chang_label", "llm_verdict", "llm_confidence",
                    "llm_reasoning", "cited_rules"])
        for i, (it, a) in enumerate(results, 1):
            w.writerow([i, it["sentence"], "", "", it["fiona"], it["chang"],
                        a["verdict"], a["confidence"], a["reasoning"],
                        a["cited_rules"]])
    print(f"  wrote {out}  ({len(results)} rows)")

    rp = out.with_suffix(".rules.txt")
    with open(rp, "w") as f:
        for i, ru in enumerate(rules, 1):
            f.write(f"{i}. {ru.get('boundary', '')}\n"
                    f"   rule: {ru.get('rule', '')}\n"
                    f"   target_labels: {ru.get('target_labels')}\n"
                    f"   +cues: {ru.get('positive_cues')}\n"
                    f"   -cues: {ru.get('negative_cues')}\n\n")
    print(f"  wrote {rp}")


async def main() -> int:
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--dimension", default="", help="one dimension; omit to do all four")
    p.add_argument("--codebook", default="self_disclosure")
    p.add_argument("--provider", default="openai")
    p.add_argument("--model", default="gpt-5.4-mini")
    p.add_argument("--budget", type=int, default=5, help="ReflectAgent rounds on the agreed subset")
    p.add_argument("--limit", type=int, default=0, help="cap disputed items per dimension (smoke test)")
    p.add_argument("--out", default="", help="CSV path (only used with a single --dimension)")
    p.add_argument("--api-key", default="")
    args = p.parse_args()

    api_key = args.api_key or resolve_api_key(args.provider)
    if not api_key:
        print("error: no API key (set --api-key, OPENAI_API_KEY, or a .env)", file=sys.stderr)
        return 2

    preset = Path(__file__).resolve().parent.parent / "app" / "presets" / f"{args.codebook}.json"
    codebook = parse_codebook(json.load(open(preset)))
    dims = [args.dimension] if args.dimension else ALL_DIMS
    for d in dims:
        await process_dim(d, codebook, args, api_key)
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
