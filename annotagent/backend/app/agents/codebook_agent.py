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
      instructions, labels: [{name, definition, examples: []}]}
  - _rationale_per_dim: {dim_name: "why you chose this mode + any ambiguities"}

MODE INFERENCE:
  - single_label when labels are mutually exclusive (e.g. High/Low/No; Yes/No)
  - multi_label when labels can co-occur for the same input (e.g. you see
    "A & B" in the data, or same sentence appears multiple times with
    different labels, or codebook text explicitly says "labels may co-occur")

DIMENSIONS vs LABELS — get this right, it is the crux:
  A DIMENSION is one question answered for EVERY item (every sentence gets a
  Level, a Depth, an Intimacy, a Confession — four independent axes = four
  dimensions). LABELS are the mutually-exclusive answer options for ONE
  dimension (High / Low / No). A dimension is ALWAYS a single theme name plus a
  FLAT list of labels — never nest sub-structure inside it.

  In a spreadsheet, identify the dimensions FIRST. Read the column HEADERS — do
  not hard-code:
    - The dimensions are the distinct CODING AXES — typically the values of a
      "coding theme" / "aspect" column (e.g. "Level of disclosure", "Depth",
      "Intimacy"; or "Recommendation", "Analysis", "Planning"), PLUS any
      dedicated column that poses its own categorical question (a separate
      "Topic" column is its own dimension).
    - The labels are the option values sitting next to each axis (e.g. a
      "Levels" / "Code" column).
    - Definitions, examples, sub-codes, and notes DESCRIBE labels: fold them into
      the label's `definition` / `examples`. They are never dimensions, and must
      not be dropped.

  Do NOT mistake a broader grouping column for the dimension axis. If a column
  ABOVE the axis holds whole DOMAINS (e.g. a "Type" column with values like
  "Users' prompts" vs "Personalization" — the same role that separate sheets or
  separate codebooks play elsewhere), it is NOT a dimension. Keep one codebook,
  take the dimensions from the axis column below it, and mention the domain
  grouping in the affected dimensions' instructions.

  If the sheet is a single flat list of categories with no axis column, produce
  ONE dimension whose labels are those categories. Keep dimensions to the
  genuinely independent axes — never split one axis's labels into many thin
  dimensions.

RULES:
  1. If the input text already contains a codebook JSON block, extract it faithfully.
  2. If the input is annotator data (spreadsheet dumps with Coding theme / Level
     columns), synthesize the schema from the OBSERVED labels per theme.
  3. Use canonical casing (Title Case for labels; lowercase with underscores in IDs).
  4. 2-6 dimensions is typical; 3-8 labels per dimension is typical.
  5. If a dimension may not apply to every item, include an explicit "No label"
     label with a definition like "Use when none of the substantive labels apply."
     Do not represent non-applicability by omitting the dimension or leaving cells blank.
  6. Definitions: copy the source cell text verbatim. Never truncate a definition
     to a fragment, and never reuse an Example cell as a definition.
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

    # The whole codebook fits in one prompt; feed the full forward-filled content
    # to a strong model in a single call (with strict-JSON + schema-validation
    # retries) rather than a self-built tool-calling loop over windowed reads.
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
        names = [l.name.lower() for l in dim.labels]

        if len(dim.labels) < 2:
            flags.append({"severity": "error", "dim": dim.name,
                          "message": f"Only {len(dim.labels)} label(s) — need at least 2."})
        if len(dim.labels) > 10:
            flags.append({"severity": "warn", "dim": dim.name,
                          "message": f"{len(dim.labels)} labels — consider consolidating."})

        # Near-duplicate names (normalized lowercase substring match)
        for i, a in enumerate(names):
            for b in names[i + 1:]:
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
