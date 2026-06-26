"""Validate uploaded labeled (gold) data against a codebook schema, and align it
when it does not match — via a deterministic, LLM-proposed transform spec.

No code execution: the LLM only emits a JSON *mapping* (column/dimension renames,
per-dimension label remaps, multi-label split rules). Python applies it. The
auto-fix is a ReAct loop: validate -> propose spec -> apply -> re-validate.
"""
from __future__ import annotations

import json
import logging
import re
from typing import Any

from app.engine.codebook_parser import parse_codebook
from app.engine.llm_client import call_llm

logger = logging.getLogger(__name__)

MAX_AUTOFIX_ROUNDS = 3
LLM_SAMPLE_ROWS = 12            # rows shown to the proposer LLM
ISSUE_SAMPLE_CAP = 50          # offending rows returned to the UI
AUTOFIX_MAX_TOKENS = 2000


# ─── normalization ──────────────────────────────────────────────────────────

def _norm(value: Any) -> str:
    """Case/space/punctuation-insensitive key for matching dimension & label names."""
    text = re.sub(r"[^0-9a-zA-Z]+", " ", str(value or "").casefold())
    return " ".join(text.split())


# ─── schema ─────────────────────────────────────────────────────────────────

def build_gold_schema(codebook_raw: dict[str, Any]) -> dict[str, Any]:
    """{dim_name: {type, labels:[...], norm_dim, norm_labels:{norm->canonical}}} plus
    a top-level norm_dims map for matching incoming dimension names."""
    parsed = parse_codebook(codebook_raw)
    dims: dict[str, Any] = {}
    for d in parsed.dimensions:
        label_names = [l.name for l in d.labels]
        dims[d.name] = {
            "type": d.dim_type or "single_label",
            "labels": label_names,
            "norm_labels": {_norm(l): l for l in label_names},
        }
    return {
        "dimensions": dims,
        "norm_dims": {_norm(name): name for name in dims},
    }


def schema_for_ui(codebook_raw: dict[str, Any]) -> dict[str, Any]:
    """Compact, display-friendly view of the expected schema for the frontend."""
    parsed = parse_codebook(codebook_raw)
    return {
        "name": parsed.name,
        "dimensions": [
            {"name": d.name, "type": d.dim_type or "single_label",
             "labels": [l.name for l in d.labels]}
            for d in parsed.dimensions
        ],
    }


# ─── validation ─────────────────────────────────────────────────────────────

def _as_list(value: Any) -> list[Any]:
    if value is None:
        return []
    return value if isinstance(value, list) else [value]


def validate_items(items: list[dict[str, Any]], schema: dict[str, Any]) -> dict[str, Any]:
    """Check each item's gold_labels against the codebook schema.

    error-level: missing content, unknown label value, single-label cardinality.
    warn-level:  unknown dimension (would be dropped), missing dimension.
    A value that only differs by case/spacing/punctuation is NOT an error — it
    matches the canonical label and will be canonicalized on commit.
    """
    dims = schema["dimensions"]
    norm_dims = schema["norm_dims"]

    issues: list[dict[str, Any]] = []
    unknown_label_values: dict[str, dict[str, int]] = {}
    unknown_dimensions: dict[str, int] = {}
    summary = {"missing_content": 0, "unknown_dimension": 0, "unknown_label": 0,
               "cardinality": 0, "missing_dimension": 0, "unmatched_row": 0}
    n_error_items = 0

    def add(row, severity, kind, message, dimension="", value=""):
        if len(issues) < ISSUE_SAMPLE_CAP:
            issues.append({"row": row, "severity": severity, "kind": kind,
                           "dimension": dimension, "value": value, "message": message})

    for it in items:
        row = it.get("index", 0)
        row_has_error = False

        if not str(it.get("content") or "").strip():
            summary["missing_content"] += 1
            add(row, "error", "missing_content", "Row has no content/text.")
            row_has_error = True

        gold = it.get("gold_labels") or {}
        present_norm = set()
        for dim_name, value in gold.items():
            canonical = dims.get(dim_name) and dim_name or norm_dims.get(_norm(dim_name))
            if canonical is None:
                summary["unknown_dimension"] += 1
                unknown_dimensions[dim_name] = unknown_dimensions.get(dim_name, 0) + 1
                add(row, "warn", "unknown_dimension",
                    f"Dimension {dim_name!r} is not in the codebook (will be dropped).",
                    dimension=dim_name)
                continue
            present_norm.add(_norm(canonical))
            spec = dims[canonical]
            values = _as_list(value)

            if spec["type"] in ("single_label", "binary") and len(values) > 1:
                summary["cardinality"] += 1
                add(row, "error", "cardinality",
                    f"{canonical!r} is single-label but row has {len(values)} values.",
                    dimension=canonical, value=values)
                row_has_error = True

            for v in values:
                if _norm(v) not in spec["norm_labels"]:
                    summary["unknown_label"] += 1
                    bucket = unknown_label_values.setdefault(canonical, {})
                    bucket[str(v)] = bucket.get(str(v), 0) + 1
                    add(row, "error", "unknown_label",
                        f"{str(v)!r} is not a label of {canonical!r}.",
                        dimension=canonical, value=v)
                    row_has_error = True

        # Coverage: a labeled row that matches NONE of the codebook dimensions is a
        # mismatch (usually renamed dimensions) — flag it so the fix path triggers
        # instead of silently dropping every label.
        if gold and not present_norm:
            summary["unmatched_row"] += 1
            add(row, "error", "unmatched_row",
                "None of this row's dimensions match the codebook.")
            row_has_error = True

        for norm_dim, canonical in norm_dims.items():
            if norm_dim not in present_norm:
                summary["missing_dimension"] += 1  # warn-level, no per-row issue spam

        if row_has_error:
            n_error_items += 1

    n_errors = sum(1 for i in issues if i["severity"] == "error")
    return {
        "ok": summary["missing_content"] == 0 and summary["unknown_label"] == 0
              and summary["cardinality"] == 0 and summary["unmatched_row"] == 0,
        "n_items": len(items),
        "n_error_items": n_error_items,
        "n_errors_shown": n_errors,
        "summary": summary,
        "issues": issues,
        "unknown_label_values": unknown_label_values,
        "unknown_dimensions": unknown_dimensions,
    }


# ─── deterministic transform ────────────────────────────────────────────────

def apply_transform(items: list[dict[str, Any]], spec: dict[str, Any],
                    schema: dict[str, Any]) -> list[dict[str, Any]]:
    """Apply a transform spec to items, producing a new aligned list.

    spec = {
      content_from: str|null,                 # metadata key to use as content if empty
      dimension_map: {src_dim: canonical_dim},
      label_map: {canonical_dim: {src_label: canonical_label}},  # matched by norm
      multi_split: [str, ...],                # split a string value into multi labels
      drop_dimensions: [src_dim, ...],
    }
    """
    dims = schema["dimensions"]
    norm_dims = schema["norm_dims"]
    content_from = spec.get("content_from")
    dim_map = {_norm(k): v for k, v in (spec.get("dimension_map") or {}).items()}
    drop = {_norm(d) for d in (spec.get("drop_dimensions") or [])}
    splits = [s for s in (spec.get("multi_split") or []) if s]
    # normalize label_map keys for lookup: {canonical_dim: {norm_src: canonical_label}}
    label_map: dict[str, dict[str, str]] = {}
    for dim_key, mapping in (spec.get("label_map") or {}).items():
        canonical_dim = dims.get(dim_key) and dim_key or norm_dims.get(_norm(dim_key))
        if canonical_dim is None:
            continue
        label_map[canonical_dim] = {_norm(k): v for k, v in (mapping or {}).items()}

    out: list[dict[str, Any]] = []
    for it in items:
        new = dict(it)
        meta = it.get("metadata") or {}

        content = str(it.get("content") or "").strip()
        if not content and content_from:
            content = str(meta.get(content_from, "") or "").strip()
        new["content"] = content

        new_gold: dict[str, Any] = {}
        for dim_name, value in (it.get("gold_labels") or {}).items():
            nd = _norm(dim_name)
            if nd in drop:
                continue
            canonical_dim = dim_map.get(nd) or (dims.get(dim_name) and dim_name) or norm_dims.get(nd)
            if canonical_dim is None or canonical_dim not in dims:
                continue
            spec_dim = dims[canonical_dim]

            # split string -> list for multi-label dims
            values = _as_list(value)
            if spec_dim["type"] not in ("single_label", "binary") and splits:
                expanded: list[Any] = []
                for v in values:
                    if isinstance(v, str):
                        parts = [v]
                        for sep in splits:
                            parts = [p for chunk in parts for p in chunk.split(sep)]
                        expanded.extend(p.strip() for p in parts if p.strip())
                    else:
                        expanded.append(v)
                values = expanded

            remap = label_map.get(canonical_dim, {})
            canon_values = []
            for v in values:
                mapped = remap.get(_norm(v)) or spec_dim["norm_labels"].get(_norm(v)) or v
                if mapped not in canon_values:
                    canon_values.append(mapped)

            if spec_dim["type"] in ("single_label", "binary"):
                new_gold[canonical_dim] = canon_values[0] if canon_values else None
            else:
                new_gold[canonical_dim] = canon_values

        new["gold_labels"] = new_gold
        out.append(new)
    return out


def canonicalize_items(items: list[dict[str, Any]], schema: dict[str, Any]) -> list[dict[str, Any]]:
    """Commit-time pass: drop unknown dims and snap labels to canonical spelling by
    norm-match. Equivalent to apply_transform with an empty spec."""
    return apply_transform(items, {}, schema)


# ─── LLM proposer + ReAct loop ──────────────────────────────────────────────

_PROPOSER_SYSTEM = """You align a user's labeled dataset to a fixed annotation codebook.

You are given: the TARGET SCHEMA (dimensions, each with a type and its allowed
labels), a SAMPLE of the user's rows, and the VALIDATION ERRORS. Produce a JSON
TRANSFORM SPEC that maps the user's data onto the schema. You do NOT write code.

Output STRICT JSON with these keys (omit a key if unused):
{
  "content_from": "<metadata key holding the text, if rows are missing content>",
  "dimension_map": {"<user dimension name>": "<exact schema dimension name>"},
  "label_map": {"<schema dimension name>": {"<user label value>": "<exact schema label>"}},
  "multi_split": ["<separator>", ...],
  "drop_dimensions": ["<user dimension to drop>"]
}

Rules:
- Map every UNKNOWN label value to the closest allowed label of that dimension.
  Use the schema's EXACT label spelling on the right-hand side.
- Common case: a binary gold value "Yes"/"No" must map to the schema's full label
  (e.g. "Yes" -> "Yes, it's a confession").
- Only add multi_split if a single cell packs several labels (e.g. "A & B").
- Map or drop dimensions the codebook does not define; never invent dimensions.
- No prose, no markdown fences. JSON object only."""


def _proposer_user_message(schema: dict[str, Any], sample: list[dict[str, Any]],
                           report: dict[str, Any]) -> str:
    dims = schema["dimensions"]
    schema_lines = ["TARGET SCHEMA:"]
    for name, spec in dims.items():
        schema_lines.append(f"- {name} [{spec['type']}]: {spec['labels']}")

    err_lines = ["\nVALIDATION ERRORS:"]
    if report["unknown_dimensions"]:
        err_lines.append(f"Unknown dimensions (not in codebook): {report['unknown_dimensions']}")
    if report["unknown_label_values"]:
        err_lines.append("Unknown label values per dimension (value: count):")
        for dim, vals in report["unknown_label_values"].items():
            err_lines.append(f"  {dim}: {vals}")
    if report["summary"]["missing_content"]:
        err_lines.append(f"{report['summary']['missing_content']} rows missing content.")
    if report["summary"]["cardinality"]:
        err_lines.append(f"{report['summary']['cardinality']} single-label rows carry multiple values.")

    sample_lines = ["\nSAMPLE ROWS (content + gold_labels + metadata keys):"]
    for it in sample[:LLM_SAMPLE_ROWS]:
        sample_lines.append(json.dumps({
            "content": (str(it.get("content") or "")[:120]),
            "gold_labels": it.get("gold_labels") or {},
            "metadata_keys": list((it.get("metadata") or {}).keys()),
        }, ensure_ascii=False))

    return "\n".join(schema_lines + err_lines + sample_lines +
                     ["\nReturn the transform spec as STRICT JSON now."])


def _extract_json(text: str) -> dict[str, Any] | None:
    s = (text or "").strip()
    if s.startswith("```"):
        s = s.split("\n", 1)[-1].rsplit("```", 1)[0].strip()
    try:
        obj = json.loads(s)
        return obj if isinstance(obj, dict) else None
    except json.JSONDecodeError:
        m = re.search(r"\{.*\}", s, flags=re.DOTALL)
        if not m:
            return None
        try:
            return json.loads(m.group(0))
        except json.JSONDecodeError:
            return None


async def propose_transform(schema, sample, report, *, provider, model, api_key) -> dict[str, Any] | None:
    resp = await call_llm(
        messages=[
            {"role": "system", "content": _PROPOSER_SYSTEM},
            {"role": "user", "content": _proposer_user_message(schema, sample, report)},
        ],
        provider=provider, model=model, api_key=api_key, max_tokens=AUTOFIX_MAX_TOKENS,
    )
    return _extract_json(resp.text)


async def autofix_items(items, schema, *, provider, model, api_key,
                        max_rounds: int = MAX_AUTOFIX_ROUNDS) -> dict[str, Any]:
    """ReAct loop: validate -> propose spec -> apply -> re-validate, until clean or
    no further progress. Returns {items, trace, report}."""
    current = items
    report = validate_items(current, schema)
    trace: list[dict[str, Any]] = []

    for r in range(max_rounds):
        if report["ok"]:
            break
        try:
            spec = await propose_transform(
                schema, current, report, provider=provider, model=model, api_key=api_key,
            )
        except Exception as e:
            logger.warning(f"autofix proposer failed (round {r + 1}): {e}")
            trace.append({"round": r + 1, "error": f"{type(e).__name__}: {e}"})
            break
        if not spec:
            trace.append({"round": r + 1, "error": "Proposer returned no valid spec."})
            break

        candidate = apply_transform(current, spec, schema)
        new_report = validate_items(candidate, schema)
        trace.append({
            "round": r + 1,
            "spec": spec,
            "errors_before": report["n_errors_shown"],
            "errors_after": new_report["n_errors_shown"],
            "error_items_after": new_report["n_error_items"],
        })
        # accept progress; stop if it didn't help
        progressed = new_report["n_error_items"] < report["n_error_items"]
        current, report = candidate, new_report
        if report["ok"] or not progressed:
            break

    return {"items": current, "trace": trace, "report": report}
