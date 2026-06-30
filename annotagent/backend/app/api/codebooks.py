"""Codebook API routes — upload JSON, parse, validate; list presets."""
from __future__ import annotations

import json
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.database import get_db
from app.models.tables import Codebook, CodebookDraft, Dimension, Label, Project, DimensionType
from app.schemas.schemas import (
    AcceptDraftRequest, CodebookOut, CodebookUpload, PresetInfo,
)
from app.config import resolve_api_key
from app.engine.codebook_parser import parse_codebook, validate_codebook
from app.engine.auto_prompt_generator import agenerate_prompts_per_dimension
from app.engine.llm_client import call_llm
from app.utils.storage import next_version, project_paths, save_text, save_yaml, utc_now_iso

router = APIRouter(prefix="/api/projects/{project_id}/codebooks", tags=["codebooks"])

PRESETS_DIR = Path(__file__).parent.parent / "presets"

# Display order for the wizard's preset list. Anything not listed here
# falls to the back, alphabetized.
_PRESET_ORDER = ["self_disclosure", "ai_behavior"]


@router.get("/presets", response_model=list[PresetInfo])
async def list_presets(project_id: int):
    """List available codebook presets, ordered for the wizard."""
    presets = []
    for f in PRESETS_DIR.glob("*.json"):
        with open(f) as fp:
            data = json.load(fp)
        presets.append(PresetInfo(
            name=f.stem,
            description=data.get("description", ""),
            dimensions=len(data.get("dimensions", [])),
        ))
    rank = {n: i for i, n in enumerate(_PRESET_ORDER)}
    presets.sort(key=lambda p: (rank.get(p.name, len(_PRESET_ORDER)), p.name))
    return presets


@router.get("/presets/{name}")
async def get_preset(project_id: int, name: str):
    """Full preset codebook (name, description, dimensions with labels + paths) so
    the wizard can preview it before loading. Same shape a drafted codebook has."""
    # Guard against path traversal: only a bare preset stem is allowed.
    if "/" in name or "\\" in name or name.startswith("."):
        raise HTTPException(400, "Invalid preset name.")
    path = PRESETS_DIR / f"{name}.json"
    if not path.exists():
        raise HTTPException(404, f"Preset '{name}' not found")
    with open(path) as fp:
        return json.load(fp)


@router.post("", response_model=CodebookOut, status_code=201)
async def upload_codebook(
    project_id: int,
    body: CodebookUpload,
    db: AsyncSession = Depends(get_db),
):
    """Upload a codebook JSON or load from preset."""
    project = await db.get(Project, project_id)
    if not project:
        raise HTTPException(404, "Project not found")

    if body.preset_name:
        preset_path = PRESETS_DIR / f"{body.preset_name}.json"
        if not preset_path.exists():
            raise HTTPException(404, f"Preset '{body.preset_name}' not found")
        with open(preset_path) as fp:
            raw_json = json.load(fp)
    elif body.raw_json:
        raw_json = body.raw_json
    else:
        raise HTTPException(400, "Provide either preset_name or raw_json")

    errors = validate_codebook(raw_json)
    if errors:
        raise HTTPException(422, detail=errors)

    parsed = parse_codebook(raw_json)

    codebook = Codebook(
        project_id=project_id,
        name=parsed.name,
        description=parsed.description,
        raw_json=raw_json,
    )
    db.add(codebook)
    await db.flush()

    for i, dim_def in enumerate(parsed.dimensions):
        dim = Dimension(
            codebook_id=codebook.id,
            name=dim_def.name,
            dim_type=DimensionType(dim_def.dim_type),
            instructions=dim_def.instructions,
            gated_by=dim_def.gated_by,
            derived_from=dim_def.derived_from,
            context_dims=dim_def.context_dims,
            sort_order=i,
        )
        db.add(dim)
        await db.flush()

        for j, lbl_def in enumerate(dim_def.labels):
            label = Label(
                dimension_id=dim.id,
                name=lbl_def.name,
                definition=lbl_def.definition,
                examples=lbl_def.examples,
                path=lbl_def.path,
                sort_order=j,
            )
            db.add(label)

    await db.commit()

    # Reload with eagerly-loaded relationships to avoid async lazy-load.
    result = await db.execute(
        select(Codebook)
        .where(Codebook.id == codebook.id)
        .options(selectinload(Codebook.dimensions).selectinload(Dimension.labels))
    )
    return result.scalars().first()


class AutoPromptRequest(BaseModel):
    task_type: str = "text_annotation"


class DimensionPrompt(BaseModel):
    dimension_name: str
    prompt: str
    version: str
    path: str
    error: str | None = None


class AutoPromptResponse(BaseModel):
    prompts: list[DimensionPrompt]


@router.post("/{codebook_id}/auto-prompt", response_model=AutoPromptResponse)
async def auto_generate_prompt(
    project_id: int,
    codebook_id: int,
    body: AutoPromptRequest,
    db: AsyncSession = Depends(get_db),
):
    """LLM-generate one annotation prompt per dimension, in parallel.

    Each dimension's prompt is saved as
    ``workspace/project_<id>/prompts/<dim_name>/auto_vNNN.txt`` with a sibling
    ``.meta.yaml``. Per-dimension matches the multi-step pipeline + per-
    dimension optimizer architecture; the deterministic Jinja generator in
    ``engine/prompt_generator.py`` remains the path for preset/gallery prompts.
    """
    project = await db.get(Project, project_id)
    if not project:
        raise HTTPException(404, "Project not found")

    api_key = resolve_api_key(project.llm_provider, project.api_key_encrypted)
    if not api_key:
        raise HTTPException(
            400,
            f"No {project.llm_provider} API key available. Set one in Setup or add it to the backend .env.",
        )

    cb = await db.get(Codebook, codebook_id)
    if not cb or cb.project_id != project_id:
        raise HTTPException(404, "Codebook not found for this project")

    parsed = parse_codebook(cb.raw_json or {})
    if not parsed.dimensions:
        raise HTTPException(400, "Codebook has no dimensions")

    results = await agenerate_prompts_per_dimension(
        parsed.dimensions,
        task_type=body.task_type,
        provider=project.llm_provider,
        model=project.llm_model,
        api_key=api_key,
    )

    paths = project_paths(f"project_{project_id}")
    out: list[DimensionPrompt] = []
    for dim_name, res in results:
        # Sanitize dim name for filesystem (spaces / slashes happen in real codebooks).
        safe = "".join(c if c.isalnum() or c in "-_." else "_" for c in dim_name)
        dim_dir = paths["prompts"] / safe
        version = next_version(dim_dir, prefix="auto_v")

        if isinstance(res, Exception):
            out.append(DimensionPrompt(
                dimension_name=dim_name, prompt="", version=version,
                path=str(dim_dir / f"{version}.txt"), error=repr(res),
            ))
            continue

        prompt_path = dim_dir / f"{version}.txt"
        save_text(prompt_path, res)
        save_yaml(dim_dir / f"{version}.meta.yaml", {
            "version": version,
            "source": "auto_prompt_generator",
            "codebook_id": codebook_id,
            "codebook_name": cb.name,
            "dimension_name": dim_name,
            "task_type": body.task_type,
            "llm_provider": project.llm_provider,
            "llm_model": project.llm_model,
            "created_at": utc_now_iso(),
        })
        out.append(DimensionPrompt(
            dimension_name=dim_name, prompt=res, version=version,
            path=str(prompt_path), error=None,
        ))

    return AutoPromptResponse(prompts=out)


_STRUCTURE_SYSTEM = """You map an annotation codebook to a prediction-structure diagram.

Given the dimensions (name, type, labels, and dependencies: ``gated_by`` = a
dimension whose value restricts this one's labels; ``context_dims`` = dimensions fed
in as context), output STRICT JSON describing a left-to-right tree:

{
  "root": {"label": "<short scheme name>", "sublabel": "predict 1 of N"}  OR null,
  "themes": [
    {"name": "<dimension predicted first>",
     "citation": "<Author Year pulled from its definitions, or ''>",
     "levels": ["<label>", "<label>", ...]}
  ],
  "outputs": [{"name": "<dependent dimension>", "sublabel": "<short count e.g. '37 topics', or ''>"}],
  "independent_themes": ["<exact names of themes that do NOT feed the outputs>"]
}

How to fill it (works for ANY codebook, do not hard-code one):
  - THEMES = dimensions predicted on their own (no gated_by) whose labels are a
    SMALL mutually-exclusive scale (High/Low/No, Yes/No, Peripheral/Intermediate/
    Central, ...). Put each label in "levels". Pull a citation
    (e.g. "Zhang et al. 2025", "Altman & Taylor 1973") from the dimension's
    definitions if present, else "".
  - OUTPUTS = the dependent dimensions (those with gated_by or context_dims),
    ordered so a dimension others depend on comes BEFORE the ones depending on it
    (e.g. Topics before Topic thematic categories). Do NOT list their labels; put a
    short count in "sublabel" (e.g. "37 topics"). If there are none, outputs = [].
    Every theme's levels flow into the first output, so list outputs even if only
    one dimension formally gates them.
  - A predicted-first dimension with MANY labels (not a small scale) is still a
    theme; give it few or no "levels".
  - "independent_themes": MOST themes feed the outputs (the topic is described in
    their context). List here ONLY the EXACT names of themes that are clearly
    ORTHOGONAL to the topic — a different axis the topic does not depend on, e.g. a
    temporal "when" orientation (past/future/now). Everything not listed feeds.
  - "root": include only if the themes are facets of one coding scheme; sublabel
    like "predict 1 of <#themes>". Else null.

EXAMPLE — for a self-disclosure codebook with themes Level of disclosure (High/Low/
No), Depth of disclosure, Intimacy, Disclosure as confession, and Temporality
(Past/Future/Now), plus dependent dimensions Topics and Topic thematic categories:
{
  "root": {"label": "Self-disclosure", "sublabel": "predict 1 of 5"},
  "themes": [
    {"name": "Level of disclosure", "citation": "Zhang et al. 2025", "levels": ["High","Low","No"]},
    {"name": "Depth of disclosure", "citation": "Altman & Taylor 1973", "levels": ["Peripheral","Intermediate","Central"]},
    {"name": "Intimacy of self-disclosure", "citation": "Croes et al. 2024", "levels": ["Peripheral","Intermediate","Core"]},
    {"name": "Disclosure as confession", "citation": "Croes et al. 2024", "levels": ["Yes","No"]},
    {"name": "Temporality", "citation": "", "levels": ["Past","Future","Now"]}
  ],
  "outputs": [{"name": "Topics", "sublabel": "37 topics"},
              {"name": "Topic thematic categories", "sublabel": "17 categories"}],
  "independent_themes": ["Temporality"]
}
Temporality is independent (a "when" axis), so the four disclosure facets feed the
topic and Temporality does not.

Output STRICT JSON only — no prose, no fences."""


def _structure_user_message(parsed) -> str:
    dims = []
    for d in parsed.dimensions:
        # Include instructions + label-definition text so the model can pull a
        # citation (e.g. "Zhang et al. 2025") out of it.
        defs = " ".join((l.definition or "") for l in d.labels)
        dims.append({
            "name": d.name,
            "type": d.dim_type,
            "gated_by": d.gated_by or None,
            "context_dims": d.context_dims or [],
            "n_labels": len(d.labels),
            "labels": [l.name for l in d.labels][:40],
            "definition_text": ((d.instructions or "") + " " + defs)[:700],
        })
    return ("CODEBOOK DIMENSIONS:\n" + json.dumps(dims, ensure_ascii=False, indent=2)
            + "\n\nProduce the diagram JSON now. STRICT JSON only.")


def _extract_json(text: str):
    s = (text or "").strip()
    if s.startswith("```"):
        s = s.split("\n", 1)[-1].rsplit("```", 1)[0].strip()
    try:
        return json.loads(s)
    except json.JSONDecodeError:
        i, j = s.find("{"), s.rfind("}")
        if 0 <= i < j:
            try:
                return json.loads(s[i:j + 1])
            except json.JSONDecodeError:
                return None
        return None


def _theme_levels(d, cap: int) -> list[dict]:
    """The boxes shown branching off a theme, built deterministically from the
    codebook so it works for any shape:
      - hierarchical labels (path) -> one box per top-level group (function), with a
        leaf count, so a 37-leaf taxonomy shows ~6 function boxes, not 37 leaves;
      - a small flat scale (High/Low/No) -> one box per label;
      - many flat labels -> none (just the theme box, the count is on the theme).
    """
    has_path = any(getattr(l, "path", None) for l in d.labels)
    if has_path:
        order, counts = [], {}
        for l in d.labels:
            g = (l.path[0] if getattr(l, "path", None) else l.name)
            if g not in counts:
                counts[g] = 0; order.append(g)
            counts[g] += 1
        return [{"label": g, "sublabel": f"{counts[g]} codes"} for g in order[:cap]]
    if len(d.labels) <= cap:
        return [{"label": l.name} for l in d.labels]
    return []


class StructureSchemaOut(BaseModel):
    root: dict | None = None
    themes: list[dict] = []
    outputs: list[dict] = []


@router.post("/{codebook_id}/structure-schema", response_model=StructureSchemaOut)
async def generate_structure_schema(
    project_id: int, codebook_id: int, db: AsyncSession = Depends(get_db),
):
    """LLM-predict a structured diagram schema (root / themes[levels] / outputs) of
    the codebook's prediction structure. Universal: the model infers which dimensions
    are themes (with their levels + citations) and which are the dependent topic
    chain; the frontend renders the fixed left-to-right tree from it."""
    project = await db.get(Project, project_id)
    if not project:
        raise HTTPException(404, "Project not found")
    cb = await db.get(Codebook, codebook_id)
    if not cb or cb.project_id != project_id:
        raise HTTPException(404, "Codebook not found for this project")
    api_key = resolve_api_key(project.llm_provider, project.api_key_encrypted)
    if not api_key:
        raise HTTPException(400, f"No {project.llm_provider} API key available.")

    parsed = parse_codebook(cb.raw_json or {})
    if not parsed.dimensions:
        raise HTTPException(400, "Codebook has no dimensions")

    try:
        resp = await call_llm(
            messages=[
                {"role": "system", "content": _STRUCTURE_SYSTEM},
                {"role": "user", "content": _structure_user_message(parsed)},
            ],
            provider=project.llm_provider, model=project.llm_model, api_key=api_key,
            max_tokens=3000,
        )
    except Exception as e:
        raise HTTPException(502, f"LLM call failed: {type(e).__name__}: {e}")

    obj = _extract_json(resp.text)
    if not isinstance(obj, dict):
        raise HTTPException(502, "Model did not return a usable diagram schema.")

    # The LLM enriches (citation, which labels to show as levels, sublabel), but the
    # theme/output SPLIT is decided deterministically from the codebook so an
    # independent dimension (e.g. Temporality) is never mislabelled as a dependent
    # output: outputs = dimensions that actually depend on another (gated_by /
    # context_dims); everything else is a theme.
    llm_t = {str(t.get("name", "")): t for t in (obj.get("themes") or []) if isinstance(t, dict)}
    llm_o = {str(o.get("name", "")): o for o in (obj.get("outputs") or []) if isinstance(o, dict)}
    LEVEL_CAP = 12

    # Most themes feed the outputs; the LLM names the orthogonal ones to exclude.
    independent = {str(x) for x in (obj.get("independent_themes") or [])}

    themes, out_raw = [], []
    for d in parsed.dimensions:
        is_output = bool(d.gated_by or d.context_dims)
        if is_output:
            o = llm_o.get(d.name, {})
            out_raw.append({
                "name": d.name,
                "sublabel": str(o.get("sublabel", "") or "") or f"{len(d.labels)} labels",
                "_deps": [x for x in [d.gated_by, *(d.context_dims or [])] if x],
            })
        else:
            t = llm_t.get(d.name, {})
            themes.append({"name": d.name, "citation": str(t.get("citation", "") or ""),
                           "levels": _theme_levels(d, LEVEL_CAP), "feeds": d.name not in independent})

    # Order outputs so a dimension that depends on another output comes after it.
    out_names = {o["name"] for o in out_raw}
    out_raw.sort(key=lambda o: sum(1 for dep in o["_deps"] if dep in out_names))
    outputs = [{"name": o["name"], "sublabel": o["sublabel"]} for o in out_raw]

    if not themes:
        raise HTTPException(502, "Model did not return any themes.")
    root = obj.get("root") if isinstance(obj.get("root"), dict) else None
    if root:  # keep the count honest with the actual number of themes
        root["sublabel"] = f"predict 1 of {len(themes)}"
    return StructureSchemaOut(root=root, themes=themes, outputs=outputs)


@router.get("", response_model=list[CodebookOut])
async def list_codebooks(project_id: int, db: AsyncSession = Depends(get_db)):
    # Oldest → newest. Frontend treats codebooks[length-1] as the active one,
    # so this ordering must match every backend lookup that uses
    # ``order_by(Codebook.id.desc()).limit(1)`` to pick the latest.
    result = await db.execute(
        select(Codebook)
        .where(Codebook.project_id == project_id)
        .options(selectinload(Codebook.dimensions).selectinload(Dimension.labels))
        .order_by(Codebook.id.asc())
    )
    return result.scalars().all()


@router.post("/accept-draft", response_model=CodebookOut, status_code=201)
async def accept_draft(
    project_id: int,
    body: AcceptDraftRequest,
    db: AsyncSession = Depends(get_db),
):
    """Commit a CodebookDraft to this project. Strips _meta / _rationale,
    validates, and hydrates Dimension/Label rows."""
    project = await db.get(Project, project_id)
    if not project:
        raise HTTPException(404, "Project not found")

    draft = await db.get(CodebookDraft, body.draft_id)
    if not draft:
        raise HTTPException(404, "Draft not found")
    if draft.status != "ready":
        raise HTTPException(409, f"Draft status is {draft.status!r}; only 'ready' drafts can be accepted.")

    raw_json = dict(draft.draft_json or {})
    # Strip non-persistent metadata
    for k in list(raw_json.keys()):
        if k.startswith("_"):
            raw_json.pop(k)
    for dim in raw_json.get("dimensions", []):
        if isinstance(dim, dict):
            for k in list(dim.keys()):
                if k.startswith("_"):
                    dim.pop(k)

    errors = validate_codebook(raw_json)
    if errors:
        raise HTTPException(422, detail={"errors": errors,
                                          "message": "Draft failed validation on accept"})

    parsed = parse_codebook(raw_json)

    codebook = Codebook(
        project_id=project_id,
        name=parsed.name,
        description=parsed.description,
        raw_json=raw_json,
    )
    db.add(codebook)
    await db.flush()

    for i, dim_def in enumerate(parsed.dimensions):
        dim = Dimension(
            codebook_id=codebook.id,
            name=dim_def.name,
            dim_type=DimensionType(dim_def.dim_type),
            instructions=dim_def.instructions,
            gated_by=dim_def.gated_by,
            derived_from=dim_def.derived_from,
            context_dims=dim_def.context_dims,
            sort_order=i,
        )
        db.add(dim)
        await db.flush()
        for j, lbl_def in enumerate(dim_def.labels):
            label = Label(
                dimension_id=dim.id,
                name=lbl_def.name,
                definition=lbl_def.definition,
                examples=lbl_def.examples,
                path=lbl_def.path,
                sort_order=j,
            )
            db.add(label)

    # Mark the draft as accepted (but don't delete — user may want history)
    draft.accepted_for_project_id = project_id
    await db.commit()

    # Eager-loaded return
    result = await db.execute(
        select(Codebook)
        .where(Codebook.id == codebook.id)
        .options(selectinload(Codebook.dimensions).selectinload(Dimension.labels))
    )
    return result.scalars().first()


class AddLabelBody(BaseModel):
    dimension: str
    label: str
    definition: str = ""


def _norm_name(s: str) -> str:
    import re
    return " ".join(re.sub(r"[^0-9a-z]+", " ", str(s or "").casefold()).split())


@router.post("/add-label", response_model=CodebookOut)
async def add_label(project_id: int, body: AddLabelBody, db: AsyncSession = Depends(get_db)):
    """Add a new label to a dimension of the project's active codebook. Used from
    the gold-data mismatch fixer when a value is actually a valid label the user
    forgot to include. Updates raw_json and the normalized Label rows."""
    cb = (await db.execute(
        select(Codebook).where(Codebook.project_id == project_id)
        .order_by(Codebook.id.desc()).limit(1)
    )).scalars().first()
    if not cb:
        raise HTTPException(404, "No codebook for this project.")
    if not body.label.strip():
        raise HTTPException(400, "Label is empty.")

    raw = dict(cb.raw_json or {})
    dims = raw.get("dimensions", [])
    target = next((d for d in dims if _norm_name(d.get("name", "")) == _norm_name(body.dimension)), None)
    if target is None:
        raise HTTPException(404, f"Dimension {body.dimension!r} not in the codebook.")
    labels = target.setdefault("labels", [])
    if not any(_norm_name(l.get("name", "")) == _norm_name(body.label) for l in labels):
        labels.append({"name": body.label, "definition": body.definition or "User-added label.", "examples": []})
        cb.raw_json = raw
        from sqlalchemy.orm.attributes import flag_modified
        flag_modified(cb, "raw_json")

    # Mirror into the normalized Label table.
    dim_rows = (await db.execute(select(Dimension).where(Dimension.codebook_id == cb.id))).scalars().all()
    dim_row = next((d for d in dim_rows if _norm_name(d.name) == _norm_name(target["name"])), None)
    if dim_row is not None:
        existing = (await db.execute(select(Label).where(Label.dimension_id == dim_row.id))).scalars().all()
        if not any(_norm_name(l.name) == _norm_name(body.label) for l in existing):
            db.add(Label(dimension_id=dim_row.id, name=body.label,
                         definition=body.definition or "User-added label.",
                         examples=[], sort_order=len(existing)))
    await db.commit()

    result = await db.execute(
        select(Codebook).where(Codebook.id == cb.id)
        .options(selectinload(Codebook.dimensions).selectinload(Dimension.labels))
    )
    return result.scalars().first()
