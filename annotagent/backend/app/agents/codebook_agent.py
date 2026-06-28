"""CodebookAgent — the system's front door.

Orchestrates three roles:

  Ingestor   — parses user-provided materials (any supported format) into
               cleaned text + detected tables + optional analysis-friendly rows.
  Drafter    — LLM-driven schema extraction with per-dimension mode inference.
               Output is a draft CodebookDef JSON, validated before return.
  Critic     — rule-based quality audit (no LLM): flags overlap, duplicates,
               too many labels, missing definitions.

Returns a structured `DraftResult`. Never raises — all failure modes surface
as warnings or critic flags with `severity: "error"`.
"""
from __future__ import annotations

import csv
import io
import json
import logging
import re
from dataclasses import dataclass, field
from typing import Any

from app.engine.codebook_parser import parse_codebook, validate_codebook
from app.engine.format_parsers import IngestResult, Table, parse_file
from app.engine.llm_client import call_llm

logger = logging.getLogger(__name__)

MIN_CLEAN_TEXT_CHARS = 50         # below this, skip Drafter
DRAFTER_MAX_RETRIES = 3           # strict-JSON + schema validation
DRAFTER_MAX_TOKENS = 8000         # many labels + verbatim definitions need headroom

# Codebook drafting is a one-shot reasoning task (read the whole codebook, infer
# the schema). Use a strong model here regardless of the per-project annotation
# model, which is often a cheaper one tuned for high-volume labeling.
# TODO: expose this as an explicit "codebook parser model" setting in setup so
# users can see and change the cost/latency tradeoff instead of relying on a
# hidden backend override.
CODEBOOK_DRAFTER_MODEL = "gpt-5.5"
# Drafting is extraction/structuring, not deep reasoning. Full-effort reasoning on
# gpt-5.5 runs ~2+ minutes (past the client timeout); "low" keeps quality but cuts
# latency to a usable range.
CODEBOOK_DRAFTER_EFFORT = "low"


@dataclass
class DraftResult:
    ok: bool = False
    draft_json: dict[str, Any] = field(default_factory=dict)
    analysis_rows: list[dict[str, Any]] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    critic_flags: list[dict[str, Any]] = field(default_factory=list)
    drafter_model: str = ""
    error_message: str = ""


_DRAFTER_SYSTEM = """You are a senior research methodologist designing an annotation codebook.

Given cleaned input materials (annotator notes, instructions, codebook text,
or spreadsheet dumps), extract a STRUCTURED CODEBOOK with:

  - name, description, top-level mode ("single_label" | "multi_label" | "mixed")
  - dimensions: list of {name, type ("single_label" or "multi_label"),
      instructions, labels: [{name, definition, examples: [], path: []}]}
  - _rationale_per_dim: {dim_name: "why you chose this mode + any ambiguities"}

MODE INFERENCE:
  - single_label when labels are mutually exclusive (e.g. High/Low/No; Yes/No)
  - multi_label when labels can co-occur for the same input (e.g. you see
    "A & B" in the data, or same sentence appears multiple times with
    different labels, or codebook text explicitly says "labels may co-occur")

DIMENSIONS vs LABELS — get this right, it is the crux:
  A DIMENSION is one theme/section. LABELS are the things an annotator actually
  assigns to an item — the LEAVES of the taxonomy. A hierarchical codebook keeps
  its tree in each label's `path`; the dimension itself stays a single theme name.

  Spreadsheets are usually a nested taxonomy with the BROADEST column on the LEFT
  (e.g. Type -> Function -> Code -> Subcode -> Example). Read the column HEADERS,
  do not hard-code. Map them by COLUMN POSITION:

    1. Find the OUTERMOST (leftmost) grouping column whose distinct values are the
       top-level categories. EACH distinct value of that column becomes one
       DIMENSION.
         - "Type" column with "Users' prompts" / "Personalization"  -> 2 dimensions.
         - "Coding theme" column with "Level of disclosure" / "Depth" / "Intimacy"
           / "Confession"  -> those 4 dimensions.
    2. The LABELS of a dimension are the LEAVES of the tree under it — the deepest
       filled cell in each row. For a Type -> Function -> Code -> Subcode sheet,
       a row's leaf is its Subcode if present, else its Code, else its Function.
       Each leaf becomes ONE label.
    3. Every label carries `path`: the ancestor cells BETWEEN the dimension and the
       leaf, leftmost-first (the dimension/Type value itself is NOT in path).
         - a Code leaf  -> path = ["<Function>"]
         - a Subcode leaf -> path = ["<Function>", "<Code>"]
         - a Function leaf (no Code/Subcode below it) -> path = []
       Labels that share a path prefix are siblings under the same branch.
    4. `definition` = the leaf cell's own meaning (copy verbatim if a definition
       cell exists; otherwise leave ""). `examples` = the Example cell(s) for that
       leaf. Do NOT fold Code/Subcode names into definitions — they are leaf NAMES
       or path ancestors now, never buried in prose.
    5. A SEPARATE column that codes a DIFFERENT facet than the main theme axis can
       be its own dimension — but FIRST check for a TAXONOMY PAIR: two columns that
       code the SAME facet at two granularities, a COARSE "category"/"thematic"
       column and a FINE "topic"/"code"/"subcode" column (e.g. "Topic thematic
       categories" = coarse parent, "Topics" = fine child). A taxonomy pair is ONE
       hierarchical dimension, NEVER two flat dimensions:
         - the FINE column supplies the LEAVES (the labels an annotator assigns);
         - the COARSE column supplies each leaf's `path` (its single parent category);
         - assign every fine leaf to the one coarse category it belongs to — use the
           source where the columns align, and your own world knowledge where the
           cells are unaligned parallel lists (a topic belongs under exactly one
           category).
       Do NOT emit the coarse column as its own separate flat dimension when it is
       the parent of a fine column; that throws away the tree the user needs.
       A coarse category value is a `path` parent ONLY — never also a leaf under
       itself. If "Knowledge seeking" is a category, do not also list a leaf named
       "Knowledge seeking"; the messy source sometimes repeats the category in the
       fine column, but a leaf must be a genuine sub-topic, not its own parent.
    6. LIST CELLS: when one cell holds several values separated by commas, slashes,
       newlines, or "&", each distinct value is a candidate label/category — but
       MERGE near-identical variants that differ only by spelling, plural, or an
       obvious typo into a SINGLE canonical label. ("Causal conversation" /
       "Causal conversations" / "Casual conversations" -> one; "Emotional distress"
       / "Emotional distresss" -> one; "Intimate exchange" / "Initimate exchange"
       -> one.) Never keep misspelled or plural variants as distinct labels.

  So for a Type -> Function -> Code -> Subcode sheet: dimensions = the Type values;
  labels = every leaf (Subcode where it exists, otherwise Code); each label's path
  names its Function (and Code, for a Subcode leaf). Capture EVERY leaf — do not
  collapse a branch down to its Function.

  If the sheet is a single flat list of categories with no grouping column,
  produce ONE dimension whose labels are those categories (path = []).

  COVERAGE CHECK (before finishing): walk EVERY column. Every categorical CODING
  column is accounted for (as the dimension axis, the leaf/label level, a parent
  level in some leaf's `path`, a separate dimension, or folded into definitions).
  A coarse "category"/"thematic" column is usually a `path` parent of its fine
  column, NOT a standalone dimension. Never drop a real coding column.
  EXCLUDE non-coding columns — these are NOT dimensions:
    - free text: definitions, notes;
    - identifiers: row number "#", user/participant id, timestamps, log source;
    - annotator QA / testing / review columns — headers containing "testing",
      "does it work", "check", "notes", or a column whose header is prefixed with
      an annotator's name or initials (e.g. "FL - ...", "CW - ...") and whose
      values are Y/N review flags.

  EXAMPLE / FEW-SHOT CAPTURE: a column whose cells hold illustrative EXAMPLE
  sentences or QUOTES demonstrating the row's label is NOT noise — capture it.
  Identify such a column by its CONTENT, not its header (it may be called
  "Example", "Relevant Quotes", "Sample", "Donated logs", or anything else: the
  tell is verbatim sentence/quote text, not a category or a Y/N flag). Put each
  such sentence into the matching label's `examples` array, cleaned of leading
  enumerators/speaker tags like "(1)", "(P)", "(Rep)". These become optional
  few-shot demonstrations. Do NOT turn an example column into a dimension, and do
  NOT confuse it with a Y/N testing-flag column (those stay excluded).

RULES:
  1. If the input text already contains a codebook JSON block, extract it faithfully.
  2. If the input is annotator data (spreadsheet dumps with Coding theme / Level
     columns), synthesize the schema from the OBSERVED labels per theme.
  3. Use canonical casing (Title Case for labels; lowercase with underscores in IDs).
  4. 2-6 dimensions is typical. A FLAT dimension has 3-8 labels; a HIERARCHICAL
     dimension (one with `path`s) can have many more leaves — capture them ALL,
     do not consolidate the tree to hit a target count.
  5. Add a "No label" option ONLY when the source genuinely shows the dimension is
     optional — e.g. a cell that reads "None of the above" / "N/A", or notes saying
     it may not apply. Do NOT add "No label" to every dimension by default; most
     dimensions do not need one, and a forced "No label" everywhere is wrong.
  6. Definitions: copy the source cell text verbatim. Never truncate a definition
     to a fragment, and never reuse an Example cell as a definition. A leaf with no
     definition cell gets an empty definition — do not invent one.
  7. Output STRICT JSON. No prose, no markdown fences, no comments."""


async def run_codebook_agent(
    *,
    file_bytes: bytes | None = None,
    filename: str = "",
    mime: str = "",
    pasted_text: str = "",
    provider: str = "openai",
    model: str = "gpt-5.4-mini",
    api_key: str = "",
) -> DraftResult:
    """Main entry point. Runs Ingestor → Drafter → Critic. Never raises."""
    warnings: list[str] = []
    analysis_rows: list[dict[str, Any]] = []

    # ─── Ingestor ───
    if file_bytes is not None:
        ingest = await parse_file(file_bytes, filename, mime=mime)
    elif pasted_text:
        from app.engine.format_parsers import _parse_text
        ingest = await _parse_text(pasted_text.encode("utf-8"), filename or "pasted.txt")
    else:
        return DraftResult(error_message="No input provided (need file or text).")

    warnings.extend(ingest.warnings)
    analysis_rows = ingest.analysis_rows

    if not ingest.ok and not ingest.clean_text.strip():
        return DraftResult(
            warnings=warnings,
            critic_flags=[{"severity": "error", "dim": "", "message":
                           "Ingestor failed to extract any usable content. "
                           "Try pasting the codebook text in Door B."}],
            error_message="Ingestor returned no usable content.",
        )

    if len(ingest.clean_text.strip()) < MIN_CLEAN_TEXT_CHARS:
        return DraftResult(
            warnings=warnings,
            critic_flags=[{"severity": "error", "dim": "", "message":
                           f"Only {len(ingest.clean_text.strip())} chars extracted. "
                           f"Need at least {MIN_CLEAN_TEXT_CHARS} to draft a codebook."}],
            error_message="Input too short for schema extraction.",
        )

    # ─── Drafter (strong one-shot) ───
    if not api_key:
        return DraftResult(
            warnings=warnings,
            critic_flags=[{"severity": "error", "dim": "", "message":
                           "No API key available for Drafter. Set OPENAI_API_KEY "
                           "in .env or provide a per-project key."}],
            error_message="No API key available.",
            analysis_rows=analysis_rows,
        )

    # The Ingestor already renders the spreadsheet as clean forward-filled CSV, so
    # one strong-model pass over that text gets the dimension/label cut right in
    # ~20s (strict-JSON + schema-validation retries).
    draft_model = _strong_drafter_model(provider, model)
    draft_json, drafter_error = await _draft_oneshot(
        ingest, provider=provider, model=draft_model, api_key=api_key,
    )

    if not draft_json:
        return DraftResult(
            warnings=warnings,
            critic_flags=[{"severity": "error", "dim": "", "message":
                           f"Drafter failed: {drafter_error}"}],
            error_message=drafter_error,
            analysis_rows=analysis_rows,
            drafter_model=draft_model,
        )

    # ─── Call B: conditional-dependency (gate) map, then deterministic merge ───
    # A focused second pass detects whether any dimension's labels are gated by
    # another (e.g. Topic restricted per Level of disclosure). Failure → no gating.
    dep_map = await _extract_dependency_map(
        ingest, draft_json, provider=provider, model=draft_model, api_key=api_key,
    )
    if dep_map.get("gated_dimensions"):
        warnings.extend(_apply_dependency_map(draft_json, dep_map))

    # ─── Clean hierarchy artifacts the LLM sometimes leaves behind ───
    _clean_hierarchy(draft_json)

    # ─── Critic (rule-based) ───
    critic_flags = _run_critic(draft_json)

    # Annotate _meta
    draft_json.setdefault("_meta", {})
    draft_json["_meta"].update({
        "source_filename": filename,
        "drafter_model": draft_model,
        "has_analysis_rows": bool(analysis_rows),
        "n_analysis_rows": len(analysis_rows),
    })

    return DraftResult(
        ok=True,
        draft_json=draft_json,
        analysis_rows=analysis_rows,
        warnings=warnings,
        critic_flags=critic_flags,
        drafter_model=draft_model,
    )


def _strong_drafter_model(provider: str, project_model: str) -> str:
    """Always draft with a strong model. For OpenAI that's CODEBOOK_DRAFTER_MODEL;
    other providers keep their project model (no cheap default to override)."""
    return CODEBOOK_DRAFTER_MODEL if (provider or "").lower() == "openai" else project_model


async def _draft_oneshot(
    ingest: IngestResult, *, provider: str, model: str, api_key: str,
) -> tuple[dict[str, Any], str]:
    """One LLM call (with strict-JSON + schema-validation retries) that reads the
    full codebook and returns a validated draft. Returns ({}, error) on failure."""
    user_msg = _build_drafter_user_message(ingest)
    drafter_error = ""
    last_err = ""
    for attempt in range(DRAFTER_MAX_RETRIES):
        try:
            resp = await call_llm(
                messages=[
                    {"role": "system", "content": _DRAFTER_SYSTEM},
                    {"role": "user", "content": user_msg + last_err},
                ],
                provider=provider, model=model, api_key=api_key,
                max_tokens=DRAFTER_MAX_TOKENS, reasoning_effort=CODEBOOK_DRAFTER_EFFORT,
            )
        except Exception as e:
            logger.warning(f"Drafter LLM call failed (attempt {attempt + 1}): {e}")
            drafter_error = f"LLM call failed: {type(e).__name__}: {e}"
            continue

        parsed = _extract_json(resp.text)
        if parsed is None:
            last_err = (
                "\n\nREMINDER: your previous response was not valid JSON. "
                "Return ONLY a JSON object — no markdown fences, no prose."
            )
            drafter_error = "LLM returned non-JSON."
            continue

        errors = validate_codebook(parsed)
        if errors:
            last_err = (
                "\n\nREMINDER: your previous JSON failed schema validation with these errors:\n- "
                + "\n- ".join(errors)
                + "\nFix these and return STRICT JSON only."
            )
            drafter_error = f"Schema validation: {errors[:2]}"
            continue

        return parsed, ""
    return {}, drafter_error


def _build_drafter_user_message(ingest: IngestResult) -> str:
    """Compose the Drafter prompt with the FULL file content.

    For spreadsheets/tables we render every forward-filled row as CSV (parent
    cells already propagated down the hierarchy) plus per-column multi-label
    hints. For text inputs we pass the cleaned text directly. This replaces the
    earlier truncated 25-row / 120-char summary that collapsed deep taxonomies.
    """
    parts: list[str] = []
    if ingest.tables:
        parts.append(
            "INPUT SPREADSHEET — every row below is self-contained "
            "(parent/hierarchy cells are already forward-filled down):"
        )
        for t in ingest.tables:
            parts.append(_render_table_csv(t))
            hint = _mode_hints(t)
            if hint:
                parts.append(hint)
    else:
        parts.append("INPUT MATERIAL:\n\n" + ingest.clean_text)

    parts.append(
        "\nProduce the codebook JSON now. STRICT JSON only — no fences, no prose. "
        "Copy definitions verbatim from the cells; capture every distinct category."
    )
    return "\n".join(parts)


def _render_table_csv(t: Table) -> str:
    """Render a table as CSV, dropping fully-empty columns and never truncating cells."""
    keep = [h for h in t.header if h and any(str(r.get(h) or "").strip() for r in t.rows)]
    if not keep:
        keep = [h for h in t.header if h] or [f"col{i}" for i in range(len(t.header))]
    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow(keep)
    for r in t.rows:
        writer.writerow([str(r.get(h, "") or "").replace("\n", " / ").strip() for h in keep])
    return f"\n[sheet: {t.name}]  ({len(t.rows)} rows)\n{buf.getvalue().rstrip()}"


def _mode_hints(t: Table) -> str:
    """Flag columns whose cells contain ' & ' — a multi-label co-occurrence signal."""
    flagged = [repr(h) for h in t.header
               if h and any(" & " in str(r.get(h) or "") for r in t.rows)]
    if not flagged:
        return ""
    return f"MODE HINT: columns {', '.join(flagged)} contain ' & ' (multi-label co-occurrence signal)."


def _extract_json(text: str) -> dict[str, Any] | None:
    """Best-effort JSON extraction. Strips code fences."""
    s = (text or "").strip()
    if not s:
        return None
    if s.startswith("```"):
        # ```json\n...\n```
        lines = s.split("\n", 1)
        if len(lines) > 1:
            s = lines[1]
        s = s.rsplit("```", 1)[0].strip()
    try:
        obj = json.loads(s)
        if isinstance(obj, dict):
            return obj
        return None
    except json.JSONDecodeError:
        # Try to find the outermost {...}
        start = s.find("{")
        end = s.rfind("}")
        if 0 <= start < end:
            try:
                return json.loads(s[start : end + 1])
            except json.JSONDecodeError:
                return None
        return None


def _norm_label(s: str) -> str:
    """Casefold + de-plural + collapse punctuation, for comparing label names."""
    t = re.sub(r"[^0-9a-z]+", " ", str(s or "").casefold()).strip()
    return " ".join(re.sub(r"s\b", "", w) or w for w in t.split())


# ─── Call B: conditional-dependency (gate) map ───

_DEPMAP_SYSTEM = """You map CONDITIONAL DEPENDENCIES between the dimensions of an annotation codebook.

You are given (a) the source table and (b) the already-drafted dimensions with
their labels. Your only job: decide whether any dimension's set of valid labels
DEPENDS ON another dimension's value, and if so, output that gate map.

A dependency exists when the source restricts one dimension's labels per value of
another. The classic signal: a coarse theme column (e.g. "Level of disclosure"
with values High/Low/No) where EACH value's row lists its OWN subset of a second
column (e.g. "Topics" / "Topic thematic categories"). That means the second
dimension is GATED BY the first: at value "High" only High's listed items are
valid, at "Low" only Low's, etc. The per-value subsets usually OVERLAP — that is
fine and still a gate.

Output STRICT JSON, no prose, no fences:
{
  "gated_dimensions": [
    {
      "dimension": "<exact name of the gated/dependent dimension>",
      "gated_by":  "<exact name of the gating dimension>",
      "category_dimension": "<display name of the coarse parent column, e.g. 'Topic thematic categories'; omit if none>",
      "allowed": {
        "<a label of the gating dimension>": ["<allowed leaf of the gated dim>", ...],
        ...
      }
    }
  ],
  "leaf_to_category": { "<gated-dim leaf>": "<its parent thematic category>", ... }
}

RULES:
  1. Use the EXACT dimension names and the EXACT leaf names from the drafted
     codebook you are given. Map messy source spellings to the drafted leaf names.
  2. "allowed" keys MUST be labels of the gating dimension. Every listed leaf MUST
     be a real label of the gated dimension — never invent a leaf.
  3. leaf_to_category maps each gated-dim leaf to its single parent thematic
     category (the coarse grouping). Use the source where it aligns, your own
     knowledge where the source lists are unaligned. ``category_dimension`` is the
     name the coarse column had in the source (so the category can be shown as its
     own output), e.g. "Topic thematic categories".
  4. If NO dimension is conditioned on another, return {"gated_dimensions": [],
     "leaf_to_category": {}}. Do NOT invent dependencies that are not in the source.
  5. A dimension is gated by AT MOST ONE other dimension. Pick the clearest gate."""


def _validate_depmap(obj: Any) -> list[str]:
    errors: list[str] = []
    if not isinstance(obj, dict):
        return ["top-level is not an object"]
    gd = obj.get("gated_dimensions")
    if not isinstance(gd, list):
        errors.append("'gated_dimensions' must be a list")
        return errors
    for i, entry in enumerate(gd):
        if not isinstance(entry, dict):
            errors.append(f"gated_dimensions[{i}] not an object")
            continue
        if not entry.get("dimension"):
            errors.append(f"gated_dimensions[{i}] missing 'dimension'")
        if not entry.get("gated_by"):
            errors.append(f"gated_dimensions[{i}] missing 'gated_by'")
        if not isinstance(entry.get("allowed"), dict):
            errors.append(f"gated_dimensions[{i}] 'allowed' must be an object")
    if not isinstance(obj.get("leaf_to_category", {}), dict):
        errors.append("'leaf_to_category' must be an object")
    return errors


async def _extract_dependency_map(
    ingest: IngestResult, draft_json: dict[str, Any], *,
    provider: str, model: str, api_key: str,
) -> dict[str, Any]:
    """One focused LLM call: detect cross-dimension conditional gating. Returns
    {} on any failure (gating is optional — a failure degrades to no gating)."""
    # Compact view of the drafted dimensions for the model to reference by name.
    dims_view = [
        {"name": d.get("name", ""),
         "labels": [l.get("name", "") for l in (d.get("labels") or [])]}
        for d in draft_json.get("dimensions", [])
    ]
    user_msg = (
        _build_drafter_user_message(ingest)
        + "\n\nDRAFTED DIMENSIONS (use these exact names):\n"
        + json.dumps(dims_view, ensure_ascii=False)
        + "\n\nProduce the gate map JSON now. STRICT JSON only."
    )
    last_err = ""
    for _ in range(DRAFTER_MAX_RETRIES):
        try:
            resp = await call_llm(
                messages=[
                    {"role": "system", "content": _DEPMAP_SYSTEM},
                    {"role": "user", "content": user_msg + last_err},
                ],
                provider=provider, model=model, api_key=api_key,
                max_tokens=DRAFTER_MAX_TOKENS, reasoning_effort=CODEBOOK_DRAFTER_EFFORT,
            )
        except Exception as e:
            logger.warning(f"Dependency-map call failed: {e}")
            return {}
        parsed = _extract_json(resp.text)
        if parsed is None:
            last_err = "\n\nREMINDER: return ONLY a JSON object, no prose."
            continue
        errors = _validate_depmap(parsed)
        if errors:
            last_err = "\n\nREMINDER: fix these and return STRICT JSON:\n- " + "\n- ".join(errors)
            continue
        return parsed
    return {}


def _apply_dependency_map(draft: dict[str, Any], dep: dict[str, Any]) -> list[str]:
    """Deterministically fold the gate map into the codebook. Rewrites each gated
    dimension's labels so every (gate_value, leaf) becomes a leaf with
    path=[gate_value, category], and sets the dimension's `gated_by`. Returns a list
    of human-readable warnings (hallucinated leaves/gate values dropped)."""
    warnings: list[str] = []
    dims = draft.get("dimensions", [])
    by_norm = {_norm_label(d.get("name", "")): d for d in dims}
    leaf_cat = {_norm_label(k): str(v) for k, v in (dep.get("leaf_to_category") or {}).items()}

    for entry in dep.get("gated_dimensions") or []:
        gd = by_norm.get(_norm_label(entry.get("dimension", "")))
        gg = by_norm.get(_norm_label(entry.get("gated_by", "")))
        if gd is None or gg is None:
            warnings.append(f"gate skipped: unknown dimension(s) {entry.get('dimension')!r}/{entry.get('gated_by')!r}")
            continue
        # Preserve original label definitions/examples by normalized name.
        orig = {_norm_label(l.get("name", "")): l for l in (gd.get("labels") or [])}
        gate_label_norms = {_norm_label(l.get("name", "")): l.get("name", "")
                            for l in (gg.get("labels") or [])}
        new_labels: list[dict[str, Any]] = []
        seen: set[tuple[str, str]] = set()
        for gate_value, leaves in (entry.get("allowed") or {}).items():
            gnorm = _norm_label(gate_value)
            if gnorm not in gate_label_norms:
                warnings.append(f"gate value {gate_value!r} is not a label of {gg.get('name')!r} — dropped")
                continue
            gate_canon = gate_label_norms[gnorm]
            for leaf in (leaves or []):
                lnorm = _norm_label(leaf)
                src = orig.get(lnorm)
                if src is None:
                    warnings.append(f"leaf {leaf!r} not a real label of {gd.get('name')!r} — dropped")
                    continue
                sig = (gnorm, lnorm)
                if sig in seen:
                    continue
                seen.add(sig)
                cat = leaf_cat.get(lnorm, "")
                path = [gate_canon] + ([cat] if cat else [])
                new_labels.append({
                    "name": src.get("name", leaf),
                    "definition": src.get("definition", ""),
                    "examples": src.get("examples", []),
                    "path": path,
                })
        if not new_labels:
            warnings.append(f"gate for {gd.get('name')!r} produced no valid leaves — left ungated")
            continue
        gd["labels"] = new_labels
        gd["gated_by"] = gg.get("name", "")
        # Name for the derived thematic-category output (the coarse parent column),
        # only kept if leaves actually carry a category in their path.
        cat_dim = str(entry.get("category_dimension", "") or "").strip()
        if cat_dim and any(len(l.get("path", [])) > 1 for l in new_labels):
            gd["category_dimension"] = cat_dim
    return warnings


def _clean_hierarchy(draft: dict[str, Any]) -> None:
    """In-place cleanup of hierarchy artifacts the LLM leaves in messy taxonomies.

    1. Drop any leaf whose name equals one of its own `path` ancestors (a category
       that was also listed as a topic under itself — always wrong).
    2. Drop exact-duplicate leaves (same normalized name + same path) in a dimension.
    Flat (path-less) dimensions are untouched except for exact-duplicate removal.
    """
    for dim in draft.get("dimensions", []):
        labels = dim.get("labels") or []
        seen: set[tuple[str, tuple[str, ...]]] = set()
        kept = []
        for lbl in labels:
            name = lbl.get("name", "")
            path = [str(p) for p in (lbl.get("path") or [])]
            nname = _norm_label(name)
            if any(_norm_label(p) == nname for p in path):
                continue  # leaf == its own ancestor category
            sig = (nname, tuple(_norm_label(p) for p in path))
            if sig in seen:
                continue  # exact duplicate leaf
            seen.add(sig)
            kept.append(lbl)
        dim["labels"] = kept


def _run_critic(draft: dict[str, Any]) -> list[dict[str, Any]]:
    """Deterministic rule-based critic. Emits flags for the UI."""
    flags: list[dict[str, Any]] = []

    try:
        cb = parse_codebook(draft)
    except Exception as e:
        flags.append({"severity": "error", "dim": "", "message":
                      f"Codebook parse failed: {e}"})
        return flags

    for dim in cb.dimensions:
        hierarchical = any(l.path for l in dim.labels)

        if len(dim.labels) < 2:
            flags.append({"severity": "error", "dim": dim.name,
                          "message": f"Only {len(dim.labels)} label(s) — need at least 2."})
        # A hierarchical dimension is expected to carry many leaves; only flag a
        # FLAT dimension with too many sibling labels.
        if not hierarchical and len(dim.labels) > 10:
            flags.append({"severity": "warn", "dim": dim.name,
                          "message": f"{len(dim.labels)} labels — consider consolidating."})

        # Near-duplicate names, compared WITHIN the same branch (same path). A leaf
        # legitimately repeated under different gate values / categories (a gated or
        # hierarchical dimension) is NOT a duplicate — only a same-name, same-branch
        # collision is. Flat dimensions share the empty branch, so this matches the
        # prior behaviour exactly.
        branches: dict[tuple[str, ...], list[str]] = {}
        for l in dim.labels:
            key = tuple(str(p).lower() for p in l.path)
            branches.setdefault(key, []).append(l.name.lower())
        for sibs in branches.values():
            for i, a in enumerate(sibs):
                for b in sibs[i + 1:]:
                    if not a or not b:
                        continue
                    if a == b:
                        flags.append({"severity": "warn", "dim": dim.name,
                                      "message": f"Duplicate label name: {a!r}"})
                    elif len(a) > 5 and len(b) > 5 and (a in b or b in a):
                        flags.append({"severity": "info", "dim": dim.name,
                                      "message": f"Similar label names: {a!r} vs {b!r}"})

        # Missing definitions
        missing_def = [l.name for l in dim.labels if not l.definition.strip()]
        if missing_def:
            flags.append({"severity": "info", "dim": dim.name,
                          "message": f"{len(missing_def)} label(s) missing definition: "
                                     f"{', '.join(missing_def[:3])}"
                                     f"{'…' if len(missing_def) > 3 else ''}"})

    return flags
