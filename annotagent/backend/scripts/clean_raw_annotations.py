"""Clean raw Fiona/Chang annotation CSVs into per-annotator ground-truth JSON.

Mirrors the cleaned self-disclosure files: one JSON per (annotator, codebook) with
`{"items": [{"sentence", "labels": {dimension: [labels...]}}], "stats": {...}}`.
Labels are stored as lists because these codebooks are multi-label.

The raw exports are heterogeneous, so columns are found by header NAME (not a fixed
index): the header row is the one containing "Relevant quotes". Chang's export mixes
self-disclosure and AI-behavior rows in one sheet, distinguished by a "Behavior"
column, so we keep only the rows for the target behavior.

Dimensions come from the "Coding theme" column and are canonicalized to the codebook's
dimension names; the specific label is the "Level" column (kept raw, matched to codebook
labels at eval time). Rows are grouped into items by their quote text.

Usage (from annotagent/backend):
  ./.venv/bin/python scripts/clean_raw_annotations.py --codebook ai_behavior --user fiona,chang
"""
from __future__ import annotations

import argparse
import csv
import json
import re
from collections import defaultdict
from pathlib import Path

BACKEND = Path(__file__).resolve().parent.parent
REPO_ROOT = BACKEND.parent.parent
RAW_DIR = REPO_ROOT / "legacy" / "data" / "raw"
OUT_DIR = BACKEND.parent / "assets" / "data" / "cleaned"
PRESETS = BACKEND / "app" / "presets"

# (user, codebook) -> raw CSV file; behavior filter value (for sheets that mix behaviors).
RAW_FILES = {
    ("fiona", "ai_behavior"): ("fiona/Fiona_AI behavior.csv", "AI behavior"),
    ("chang", "ai_behavior"): ("chang/Chang_AI behavior.csv", "AI behavior"),
}


def _norm(value: str) -> str:
    return " ".join(re.sub(r"[^0-9a-zA-Z]+", " ", str(value)).split()).casefold()


def _codebook_dims(codebook: str) -> list[str]:
    raw = json.loads((PRESETS / f"{codebook}.json").read_text())
    return [d["name"] for d in raw["dimensions"]]


def _canon_dim(theme: str, dims: list[str]) -> str | None:
    nt = _norm(theme)
    for d in dims:
        if _norm(d) == nt:
            return d
    return None


def _find_header(rows: list[list[str]]) -> int:
    for i, r in enumerate(rows[:5]):
        if any("relevant quotes" in c.strip().casefold() for c in r):
            return i
    raise SystemExit("Could not find a header row containing 'Relevant quotes'.")


def _col_map(header: list[str]) -> dict[str, int]:
    idx: dict[str, int] = {}
    for j, name in enumerate(header):
        key = name.strip().casefold()
        if "coding theme" in key:
            idx["theme"] = j
        elif key == "level" or "subcategory" in key:
            idx["level"] = j
        elif "relevant quotes" in key:
            idx["quote"] = j
        elif key == "behavior" or key.startswith("behavior"):
            idx["behavior"] = j
    return idx


def clean(user: str, codebook: str) -> dict:
    rel, behavior_filter = RAW_FILES[(user, codebook)]
    path = RAW_DIR / rel
    dims = _codebook_dims(codebook)
    with path.open(newline="") as fh:
        rows = list(csv.reader(fh))
    h = _find_header(rows)
    cols = _col_map(rows[h])
    if "theme" not in cols or "quote" not in cols or "level" not in cols:
        raise SystemExit(f"{path}: missing required columns; found {cols}")

    # quote -> dimension -> set(labels)
    items: dict[str, dict[str, set]] = defaultdict(lambda: defaultdict(set))
    skipped_behavior = skipped_dim = skipped_noquote = 0
    for r in rows[h + 1:]:
        get = lambda k: r[cols[k]].strip() if cols.get(k) is not None and cols[k] < len(r) else ""
        if "behavior" in cols:
            beh = get("behavior")
            if beh and _norm(beh) != _norm(behavior_filter):
                skipped_behavior += 1
                continue
        quote = get("quote")
        if not quote:
            skipped_noquote += 1
            continue
        dim = _canon_dim(get("theme"), dims)
        if not dim:
            skipped_dim += 1
            continue
        # A single cell may pack several labels with "&" (Chang's export). Split
        # on "&" only — never on commas or "and", since one real label is
        # "Offers advice, opinions, perspectives, and personal experience".
        for part in get("level").split("&"):
            part = part.strip()
            if part:
                items[quote][dim].add(part)

    out_items = [
        {"sentence": q, "labels": {d: sorted(lbls) for d, lbls in dims_map.items() if lbls}}
        for q, dims_map in items.items()
    ]
    out_items = [it for it in out_items if it["labels"]]
    stats = {
        "source": str(path.relative_to(REPO_ROOT)),
        "items": len(out_items),
        "skipped_behavior": skipped_behavior,
        "skipped_unmapped_dim": skipped_dim,
        "skipped_no_quote": skipped_noquote,
    }
    return {"items": out_items, "stats": stats}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--codebook", default="ai_behavior")
    ap.add_argument("--user", default="fiona,chang")
    args = ap.parse_args()

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    for user in [u.strip() for u in args.user.split(",") if u.strip()]:
        if (user, args.codebook) not in RAW_FILES:
            print(f"  [skip] no raw file registered for ({user}, {args.codebook})")
            continue
        data = clean(user, args.codebook)
        out = OUT_DIR / f"{user}_{args.codebook}_ground_truth.json"
        out.write_text(json.dumps(data, indent=2))
        # Per-dimension label distribution for a quick sanity check.
        from collections import Counter
        per_dim: dict[str, Counter] = defaultdict(Counter)
        for it in data["items"]:
            for d, lbls in it["labels"].items():
                for l in lbls:
                    per_dim[d][l] += 1
        print(f"{out.name}: {data['stats']['items']} items  (skipped: "
              f"{data['stats']['skipped_behavior']} other-behavior, "
              f"{data['stats']['skipped_unmapped_dim']} unmapped-dim)")
        for d, c in per_dim.items():
            print(f"    {d}: {dict(c)}")


if __name__ == "__main__":
    main()
