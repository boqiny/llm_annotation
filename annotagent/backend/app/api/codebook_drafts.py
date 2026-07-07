"""CodebookAgent API — draft creation (upload / paste / preset), accept, artifact download.

Every endpoint catches exceptions and returns structured results so the UI can
render friendly banners instead of 500s.
"""
from __future__ import annotations

import csv as csv_module
import io
import json
import logging
from pathlib import Path

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from fastapi.responses import Response
from sqlalchemy.ext.asyncio import AsyncSession

from pydantic import BaseModel

from app.agents.codebook_agent import _run_critic, run_codebook_agent
from app.config import resolve_api_key
from app.database import get_db
from app.engine.codebook_parser import validate_codebook
from app.models.tables import (
    Codebook, CodebookDraft, Project,
)
from app.schemas.schemas import (
    CodebookDraftCreate, CodebookDraftOut,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/codebook-drafts", tags=["codebook-drafts"])

# Size limit (bytes). 16 MB — generous, but blocks obvious denial-of-service.
MAX_UPLOAD_BYTES = 16 * 1024 * 1024

# MIME whitelist + extension fallback
_ALLOWED_MIMES = {
    "application/pdf",
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    "application/msword",
    "application/vnd.ms-excel",
    "text/csv",
    "application/csv",
    "application/json",
    "text/plain",
    "text/markdown",
    "application/octet-stream",  # fall back on extension
    "",                          # sometimes empty from tests
}
_ALLOWED_EXTS = {"pdf", "docx", "xlsx", "xlsm", "csv", "json", "txt", "md"}

PRESETS_DIR = Path(__file__).parent.parent / "presets"


async def _project_llm_config(project_id: int | None, db: AsyncSession) -> tuple[str, str, str]:
    if project_id is None:
        raise HTTPException(400, "project_id is required so CodebookAgent can use this project's model settings.")
    project = await db.get(Project, project_id)
    if not project:
        raise HTTPException(404, "Project not found")
    provider = project.llm_provider or "openai"
    model = project.llm_model or ("claude-sonnet-4-5-20250929" if provider == "anthropic" else "gpt-5.4-mini")
    api_key = resolve_api_key(provider, project.api_key_encrypted)
    if not api_key:
        raise HTTPException(
            400,
            f"No {provider} API key available. Configure the model/API key before drafting a codebook.",
        )
    return provider, model, api_key


def _draft_to_out(draft: CodebookDraft) -> CodebookDraftOut:
    return CodebookDraftOut(
        id=draft.id,
        source=draft.source,
        source_filename=draft.source_filename or "",
        source_bytes=draft.source_bytes or 0,
        status=draft.status,
        error_message=draft.error_message or "",
        draft_json=draft.draft_json or {},
        warnings=list(draft.warnings or []),
        critic_flags=list(draft.critic_flags or []),
        has_cleaned_data=bool(draft.cleaned_data),
        cleaned_data_rows=len(draft.cleaned_data or []),
        drafter_model=draft.drafter_model or "",
        sheet_options=list((draft.draft_json or {}).get("_sheet_options") or []),
        accepted_for_project_id=draft.accepted_for_project_id,
        created_at=draft.created_at,
        updated_at=draft.updated_at,
    )


@router.post("/upload", response_model=CodebookDraftOut, status_code=201)
async def create_draft_from_upload(
    file: UploadFile = File(...),
    project_id: int = Form(...),
    merge_sheets: bool = Form(False),
    sheet: str = Form(""),
    db: AsyncSession = Depends(get_db),
):
    """Door A — upload a file. Ingestor + Drafter run inline (they're bounded
    by asyncio.wait_for timeouts), then response returns with status=ready|failed.

    Multi-sheet XLSX guardrail: if an .xlsx has more than one content sheet and the
    caller has not chosen, returns status="needs_sheet_choice" with sheet_options so
    the UI can ask to merge all (merge_sheets=True) or import one (sheet=<name>)."""
    # ─── Validate at the door ───
    mime = (file.content_type or "").lower()
    filename = file.filename or "upload"
    ext = filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
    if mime not in _ALLOWED_MIMES and ext not in _ALLOWED_EXTS:
        raise HTTPException(
            415,
            f"Unsupported file type (mime={mime!r}, ext={ext!r}). "
            f"Accepted: pdf, docx, xlsx, csv, json, txt."
        )

    data = await file.read()
    if len(data) > MAX_UPLOAD_BYTES:
        raise HTTPException(413, f"File too large ({len(data):,} bytes > {MAX_UPLOAD_BYTES:,} cap).")
    if not data:
        raise HTTPException(400, "Empty upload.")

    # ─── Multi-sheet guardrail (rule-based, before any drafting) ───
    only_sheet: str | None = None
    if ext in ("xlsx", "xlsm"):
        from app.engine.format_parsers import xlsx_content_sheets
        sheets = xlsx_content_sheets(data)
        if sheet:
            if sheet not in sheets:
                raise HTTPException(400, f"Sheet {sheet!r} not found. Available: {sheets}")
            only_sheet = sheet
        elif len(sheets) > 1 and not merge_sheets:
            # Pause and ask the user how to handle the multiple sheets.
            draft = CodebookDraft(
                source="upload",
                source_filename=filename,
                source_bytes=len(data),
                status="needs_sheet_choice",
                draft_json={"_sheet_options": sheets},
                warnings=[
                    f"'{filename}' has {len(sheets)} sheets ({', '.join(sheets)}). "
                    "Choose to merge them into one codebook or import a single sheet."
                ],
            )
            db.add(draft)
            await db.commit()
            await db.refresh(draft)
            return _draft_to_out(draft)
        # merge_sheets=True (or a single content sheet): only_sheet stays None → merge all.

    # Persist an initial draft row so the user can see status even if we crash later
    draft = CodebookDraft(
        source="upload",
        source_filename=filename,
        source_bytes=len(data),
        status="ingesting",
    )
    db.add(draft)
    await db.commit()
    await db.refresh(draft)

    provider, model, api_key = await _project_llm_config(project_id, db)

    try:
        result = await run_codebook_agent(
            file_bytes=data, filename=filename, mime=mime,
            provider=provider,
            model=model,
            api_key=api_key,
            only_sheet=only_sheet,
        )
    except Exception as e:
        logger.exception(f"CodebookAgent crashed on draft {draft.id}")
        draft.status = "failed"
        draft.error_message = f"{type(e).__name__}: {e}"
        await db.commit()
        await db.refresh(draft)
        return _draft_to_out(draft)

    draft.status = "ready" if result.ok else "failed"
    draft.error_message = result.error_message
    draft.draft_json = result.draft_json
    draft.cleaned_data = result.analysis_rows
    draft.warnings = result.warnings
    draft.critic_flags = result.critic_flags
    draft.drafter_model = result.drafter_model
    await db.commit()
    await db.refresh(draft)
    return _draft_to_out(draft)


@router.post("", response_model=CodebookDraftOut, status_code=201)
async def create_draft_from_json(
    body: CodebookDraftCreate,
    db: AsyncSession = Depends(get_db),
):
    """Doors B (text) and C (preset). JSON-only; no multipart."""
    if body.source not in ("paste", "preset"):
        raise HTTPException(400, f"Invalid source: {body.source!r}")

    draft = CodebookDraft(
        source=body.source,
        source_filename="",
        source_bytes=0,
        status="ingesting",
    )

    # ─── Door C: load preset directly, skip Drafter entirely ───
    if body.source == "preset":
        if not body.preset_name:
            raise HTTPException(400, "preset_name required for source=preset")
        preset_path = PRESETS_DIR / f"{body.preset_name}.json"
        if not preset_path.exists():
            raise HTTPException(404, f"Preset not found: {body.preset_name!r}")
        try:
            raw = json.loads(preset_path.read_text(encoding="utf-8"))
        except Exception as e:
            raise HTTPException(500, f"Failed to load preset: {e}")

        errors = validate_codebook(raw)
        if errors:
            raise HTTPException(422, detail={"errors": errors,
                                              "message": f"Preset {body.preset_name!r} failed validation"})

        # Add a minimal _meta
        raw.setdefault("_meta", {})
        raw["_meta"].update({"source_filename": f"preset:{body.preset_name}",
                             "drafter_model": "n/a (preset)"})
        draft.source_filename = f"preset:{body.preset_name}"
        draft.source_bytes = len(preset_path.read_bytes())
        draft.draft_json = raw
        draft.cleaned_data = []
        draft.warnings = [f"Loaded from preset '{body.preset_name}' — no LLM drafting."]
        draft.critic_flags = []
        draft.drafter_model = "preset"
        draft.status = "ready"
        db.add(draft)
        await db.commit()
        await db.refresh(draft)
        return _draft_to_out(draft)

    # ─── Door B: paste text ───
    if body.source == "paste":
        if not body.text or len(body.text.strip()) < 20:
            raise HTTPException(400, "Pasted text is too short (need ≥ 20 chars).")
        draft.source_filename = "pasted.txt"
        draft.source_bytes = len(body.text.encode("utf-8"))
        db.add(draft)
        await db.commit()
        await db.refresh(draft)

        provider, model, api_key = await _project_llm_config(body.project_id, db)
        try:
            result = await run_codebook_agent(
                pasted_text=body.text, filename="pasted.txt",
                provider=provider, model=model, api_key=api_key,
            )
        except Exception as e:
            logger.exception(f"CodebookAgent crashed on paste draft {draft.id}")
            draft.status = "failed"
            draft.error_message = f"{type(e).__name__}: {e}"
            await db.commit()
            await db.refresh(draft)
            return _draft_to_out(draft)

        draft.status = "ready" if result.ok else "failed"
        draft.error_message = result.error_message
        draft.draft_json = result.draft_json
        draft.cleaned_data = result.analysis_rows
        draft.warnings = result.warnings
        draft.critic_flags = result.critic_flags
        draft.drafter_model = result.drafter_model
        await db.commit()
        await db.refresh(draft)
        return _draft_to_out(draft)

    # Unreachable — source is validated to ("paste", "preset") at the top.
    raise HTTPException(400, f"Invalid source: {body.source!r}")


class FromCodebookRequest(BaseModel):
    codebook_id: int


@router.post("/from-codebook", response_model=CodebookDraftOut)
async def create_draft_from_codebook(
    body: FromCodebookRequest,
    db: AsyncSession = Depends(get_db),
):
    """Seed an editable draft from an EXISTING codebook so the user can revise it
    in the wizard (left: editable dimensions, right: structure/arrow) and re-accept.
    No LLM call — the stored ``raw_json`` already carries the full structure."""
    cb = await db.get(Codebook, body.codebook_id)
    if not cb:
        raise HTTPException(404, "Codebook not found")
    raw = dict(cb.raw_json or {})
    errors = validate_codebook(raw)
    if errors:
        raise HTTPException(422, detail={"errors": errors,
                                          "message": "Stored codebook failed validation"})
    raw.setdefault("_meta", {})
    raw["_meta"].update({"source_filename": f"codebook:{cb.name}", "drafter_model": "edit"})

    draft = CodebookDraft(
        source="codebook",
        source_filename=f"codebook:{cb.name}",
        source_bytes=0,
        status="ready",
        draft_json=raw,
        cleaned_data=[],
        warnings=[f"Editing existing codebook '{cb.name}'. Accepting saves a new version."],
        critic_flags=_run_critic(raw),
        drafter_model="edit",
    )
    db.add(draft)
    await db.commit()
    await db.refresh(draft)
    return _draft_to_out(draft)


@router.get("/{draft_id}", response_model=CodebookDraftOut)
async def get_draft(draft_id: int, db: AsyncSession = Depends(get_db)):
    draft = await db.get(CodebookDraft, draft_id)
    if not draft:
        raise HTTPException(404, "Draft not found")
    return _draft_to_out(draft)


from pydantic import BaseModel


class DraftPatch(BaseModel):
    draft_json: dict


@router.patch("/{draft_id}", response_model=CodebookDraftOut)
async def patch_draft(draft_id: int, body: DraftPatch, db: AsyncSession = Depends(get_db)):
    """Overwrite ``draft_json`` (user edits in the wizard).

    Critic-flag re-evaluation is intentionally NOT re-run here; the existing
    flags are preserved as a record of the original draft. Validation happens
    on accept.
    """
    draft = await db.get(CodebookDraft, draft_id)
    if not draft:
        raise HTTPException(404, "Draft not found")
    if draft.accepted_for_project_id is not None:
        raise HTTPException(409, "Draft already accepted; create a new one to edit.")

    draft.draft_json = body.draft_json
    await db.commit()
    await db.refresh(draft)
    return _draft_to_out(draft)


@router.get("/{draft_id}/artifact/{name}")
async def download_artifact(draft_id: int, name: str, db: AsyncSession = Depends(get_db)):
    """Download the cleaned_data artifact as JSON or CSV.

    name: 'cleaned_data.json' or 'cleaned_data.csv'
    """
    draft = await db.get(CodebookDraft, draft_id)
    if not draft:
        raise HTTPException(404, "Draft not found")

    rows = draft.cleaned_data or []
    if not rows:
        raise HTTPException(404, "This draft has no cleaned_data artifact "
                                 "(only annotator-style uploads produce one).")

    if name == "cleaned_data.json":
        body = json.dumps(rows, indent=2, ensure_ascii=False)
        return Response(
            content=body,
            media_type="application/json",
            headers={"Content-Disposition": f'attachment; filename="cleaned_data_{draft_id}.json"'},
        )

    if name == "cleaned_data.csv":
        # Flatten annotations dict into columns
        annotation_keys: list[str] = []
        seen = set()
        for r in rows:
            for k in (r.get("annotations") or {}).keys():
                if k not in seen:
                    seen.add(k)
                    annotation_keys.append(k)
        header = ["row_id", "user_id", "timestamp", "sentence", "behavior_side"] + annotation_keys + ["source_sheet", "source_row"]
        buf = io.StringIO()
        writer = csv_module.DictWriter(buf, fieldnames=header, extrasaction="ignore")
        writer.writeheader()
        for r in rows:
            flat = {
                "row_id": r.get("row_id", ""),
                "user_id": r.get("user_id", ""),
                "timestamp": r.get("timestamp", ""),
                "sentence": r.get("sentence", ""),
                "behavior_side": r.get("behavior_side", "") or "",
                "source_sheet": (r.get("source") or {}).get("sheet", ""),
                "source_row": (r.get("source") or {}).get("xlsx_row", ""),
            }
            for k in annotation_keys:
                v = (r.get("annotations") or {}).get(k, "")
                if isinstance(v, list):
                    v = " & ".join(v)
                flat[k] = v
            writer.writerow(flat)
        return Response(
            content=buf.getvalue(),
            media_type="text/csv",
            headers={"Content-Disposition": f'attachment; filename="cleaned_data_{draft_id}.csv"'},
        )

    raise HTTPException(404, f"Unknown artifact: {name!r}. "
                             f"Available: cleaned_data.json, cleaned_data.csv")


@router.delete("/{draft_id}", status_code=204)
async def delete_draft(draft_id: int, db: AsyncSession = Depends(get_db)):
    draft = await db.get(CodebookDraft, draft_id)
    if not draft:
        raise HTTPException(404, "Draft not found")
    await db.delete(draft)
    await db.commit()
