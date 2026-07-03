"""Pydantic request/response schemas for CALICO API."""
from __future__ import annotations

import datetime
from typing import Any, Optional

from pydantic import AliasChoices, BaseModel, Field, field_validator


# ---------- Project ----------

class ProjectCreate(BaseModel):
    name: str
    description: str = ""
    llm_provider: str = "openai"
    llm_model: str = "gpt-5.4-mini"
    api_key: str = ""


class ProjectUpdate(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    llm_provider: Optional[str] = None
    llm_model: Optional[str] = None
    api_key: Optional[str] = None


class ProjectOut(BaseModel):
    id: int
    name: str
    description: str
    llm_provider: str
    llm_model: str
    status: str
    created_at: Optional[datetime.datetime] = None
    updated_at: Optional[datetime.datetime] = None

    model_config = {"from_attributes": True}


# ---------- Codebook ----------

class LabelOut(BaseModel):
    id: int
    name: str
    definition: str
    examples: list[Any] = []
    path: list[str] = []
    sort_order: int = 0

    model_config = {"from_attributes": True}

    @field_validator("path", "examples", mode="before")
    @classmethod
    def _none_to_list(cls, v: Any) -> Any:
        # Rows predating the column have NULL; coerce to empty list.
        return v if v is not None else []


class DimensionOut(BaseModel):
    id: int
    name: str
    dim_type: str
    instructions: str
    gated_by: str = ""
    derived_from: str = ""
    context_dims: list[str] = []
    sort_order: int = 0
    labels: list[LabelOut] = []

    model_config = {"from_attributes": True}


class CodebookOut(BaseModel):
    id: int
    project_id: int
    name: str
    description: str
    raw_json: dict[str, Any]
    dimensions: list[DimensionOut] = []

    model_config = {"from_attributes": True}


class CodebookUpload(BaseModel):
    """Upload raw codebook JSON or select a preset."""
    preset_name: Optional[str] = None
    raw_json: Optional[dict[str, Any]] = None


# ---------- Dataset ----------

class DataItemOut(BaseModel):
    id: int
    index: int
    content: str
    context: str = ""
    # ORM attribute is ``metadata_`` (renamed in tables.py to dodge the clash
    # with SQLAlchemy's class-level ``Base.metadata``). For from_attributes
    # mode we must read by the python attr name; ``serialization_alias`` +
    # ``serialize_by_name=True`` keeps the JSON key as ``metadata`` for the
    # frontend.
    metadata_: dict[str, Any] = Field(
        default_factory=dict,
        validation_alias=AliasChoices("metadata_", "metadata"),
        serialization_alias="metadata",
    )
    gold_labels: dict[str, Any] = {}

    model_config = {
        "from_attributes": True,
        "populate_by_name": True,
        "serialize_by_alias": True,
    }


class DatasetOut(BaseModel):
    id: int
    project_id: int
    name: str
    file_type: str
    total_items: int
    is_gold: bool

    model_config = {"from_attributes": True}


class DatasetPreview(BaseModel):
    dataset: DatasetOut
    items: list[DataItemOut] = []


# ---------- Pipeline ----------

class PipelineStepSchema(BaseModel):
    name: str
    dimensions: list[str]
    prompt: str = ""
    gate: Optional[str] = None  # dimension name to gate on


class PipelineOut(BaseModel):
    id: int
    project_id: int
    steps: list[dict[str, Any]]
    auto_generated: bool

    model_config = {"from_attributes": True}


class PipelineUpdate(BaseModel):
    steps: list[dict[str, Any]]


# ---------- Job ----------

class JobCreate(BaseModel):
    dataset_id: int
    pipeline_id: int
    source: str = "annotation"


class JobOut(BaseModel):
    id: int
    project_id: int
    dataset_id: int
    pipeline_id: int
    status: str
    total_items: int
    completed_items: int
    failed_items: int
    total_tokens: int
    source: str = "unknown"
    created_at: Optional[datetime.datetime] = None
    updated_at: Optional[datetime.datetime] = None

    model_config = {"from_attributes": True}


# ---------- Results ----------

class AnnotationResultOut(BaseModel):
    id: int
    job_id: int
    data_item_id: int
    step_order: int
    dimension_name: str
    predicted_label: str
    reasoning: str
    tokens_used: int

    model_config = {"from_attributes": True}


class MetricsOut(BaseModel):
    accuracy: float
    macro_precision: float
    macro_recall: float
    macro_f1: float
    weighted_f1: float
    per_class: dict[str, Any] = {}
    n: int
    classes: list[str] = []


class DimensionMetrics(BaseModel):
    dimension: str
    metrics: MetricsOut


# ---------- Misc ----------

class PresetInfo(BaseModel):
    name: str
    description: str
    dimensions: int


class TestConnectionRequest(BaseModel):
    provider: str
    model: str
    api_key: str


class TestConnectionResponse(BaseModel):
    success: bool
    message: str


class WSProgressMessage(BaseModel):
    job_id: int
    completed: int
    total: int
    current_item: Optional[str] = None
    current_step: Optional[str] = None
    tokens: int = 0
    cost: float = 0.0
    status: str = "running"


class CodebookDraftCreate(BaseModel):
    """JSON body when not uploading a file. For uploads, use multipart."""
    source: str  # "paste" | "preset" | "scratch"
    project_id: Optional[int] = None
    text: Optional[str] = None
    preset_name: Optional[str] = None


class CodebookCriticFlag(BaseModel):
    severity: str   # "warn" | "error" | "info"
    dim: str = ""
    message: str


class CodebookDraftOut(BaseModel):
    id: int
    source: str
    source_filename: str
    source_bytes: int
    status: str
    error_message: str
    draft_json: dict[str, Any]
    warnings: list[str] = []
    critic_flags: list[Any] = []
    has_cleaned_data: bool = False
    cleaned_data_rows: int = 0
    drafter_model: str = ""
    # When status == "needs_sheet_choice": the content sheets the user must choose
    # to merge or import individually. Empty otherwise.
    sheet_options: list[str] = []
    accepted_for_project_id: Optional[int] = None
    created_at: Optional[datetime.datetime] = None
    updated_at: Optional[datetime.datetime] = None

    model_config = {"from_attributes": True}


class AcceptDraftRequest(BaseModel):
    draft_id: int


class OptimizerInfo(BaseModel):
    name: str
    label: str
    description: str
    role: str   # "method" | "baseline"


class OptimizerRunCreate(BaseModel):
    optimizer_name: str
    dimension_name: str
    gold_dataset_id: int
    budget: int = 5
    # Default 3-way split — small train, large val (governor signal), large HELD-OUT test.
    # Rationale: prompt optimization is easy to overfit on a large train set; what we
    # actually need is many dev items for reliable governor decisions and enough
    # disjoint test items for an honest final number. Test is never shown to the optimizer.
    train_frac: float = 0.15
    val_frac: float = 0.42
    test_frac: float = 0.43


class OptimizerRunOut(BaseModel):
    id: int
    project_id: int
    gold_dataset_id: Optional[int] = None
    optimizer_name: str
    dimension_name: str
    status: str
    budget: int
    train_frac: float
    initial_score: float
    final_score: float
    trajectory: list[Any] = []
    artifact: dict[str, Any] = {}
    optimized_prompt: str = ""
    total_tokens: int = 0
    error: str = ""
    created_at: Optional[datetime.datetime] = None
    updated_at: Optional[datetime.datetime] = None

    model_config = {"from_attributes": True}
