"""SQLAlchemy ORM models for AnnotAgent."""
from __future__ import annotations

import datetime
import enum
from typing import Optional

from sqlalchemy import (
    Column,
    DateTime,
    Enum,
    Float,
    ForeignKey,
    Integer,
    JSON,
    String,
    Text,
    Boolean,
    func,
)
from sqlalchemy.orm import DeclarativeBase, relationship


class Base(DeclarativeBase):
    pass


# ---------- Enums ----------

class ProjectStatus(str, enum.Enum):
    DRAFT = "draft"
    READY = "ready"
    RUNNING = "running"
    COMPLETED = "completed"


class JobStatus(str, enum.Enum):
    PENDING = "pending"
    RUNNING = "running"
    PAUSED = "paused"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class DimensionType(str, enum.Enum):
    SINGLE_LABEL = "single_label"
    MULTI_LABEL = "multi_label"
    BINARY = "binary"
    ORDINAL = "ordinal"


# ---------- Tables ----------

class Project(Base):
    __tablename__ = "projects"

    id = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(String(255), nullable=False)
    description = Column(Text, default="")
    llm_provider = Column(String(50), default="openai")
    llm_model = Column(String(100), default="gpt-5.4-mini")
    api_key_encrypted = Column(Text, default="")
    status = Column(Enum(ProjectStatus), default=ProjectStatus.DRAFT)
    created_at = Column(DateTime, server_default=func.now())
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())

    codebooks = relationship("Codebook", back_populates="project", cascade="all, delete-orphan")
    datasets = relationship("Dataset", back_populates="project", cascade="all, delete-orphan")
    pipelines = relationship("Pipeline", back_populates="project", cascade="all, delete-orphan")
    jobs = relationship("AnnotationJob", back_populates="project", cascade="all, delete-orphan")


class Codebook(Base):
    __tablename__ = "codebooks"

    id = Column(Integer, primary_key=True, autoincrement=True)
    project_id = Column(Integer, ForeignKey("projects.id", ondelete="CASCADE"), nullable=False)
    name = Column(String(255), nullable=False)
    description = Column(Text, default="")
    raw_json = Column(JSON, nullable=False)

    project = relationship("Project", back_populates="codebooks")
    dimensions = relationship("Dimension", back_populates="codebook", cascade="all, delete-orphan")


class Dimension(Base):
    __tablename__ = "dimensions"

    id = Column(Integer, primary_key=True, autoincrement=True)
    codebook_id = Column(Integer, ForeignKey("codebooks.id", ondelete="CASCADE"), nullable=False)
    name = Column(String(255), nullable=False)
    dim_type = Column(Enum(DimensionType), default=DimensionType.SINGLE_LABEL)
    instructions = Column(Text, default="")
    sort_order = Column(Integer, default=0)

    codebook = relationship("Codebook", back_populates="dimensions")
    labels = relationship("Label", back_populates="dimension", cascade="all, delete-orphan")


class Label(Base):
    __tablename__ = "labels"

    id = Column(Integer, primary_key=True, autoincrement=True)
    dimension_id = Column(Integer, ForeignKey("dimensions.id", ondelete="CASCADE"), nullable=False)
    name = Column(String(255), nullable=False)
    definition = Column(Text, default="")
    examples = Column(JSON, default=list)
    sort_order = Column(Integer, default=0)

    dimension = relationship("Dimension", back_populates="labels")


class Dataset(Base):
    __tablename__ = "datasets"

    id = Column(Integer, primary_key=True, autoincrement=True)
    project_id = Column(Integer, ForeignKey("projects.id", ondelete="CASCADE"), nullable=False)
    name = Column(String(255), nullable=False)
    file_type = Column(String(20), default="json")
    total_items = Column(Integer, default=0)
    is_gold = Column(Boolean, default=False)

    project = relationship("Project", back_populates="datasets")
    items = relationship("DataItem", back_populates="dataset", cascade="all, delete-orphan")


class DataItem(Base):
    __tablename__ = "data_items"

    id = Column(Integer, primary_key=True, autoincrement=True)
    dataset_id = Column(Integer, ForeignKey("datasets.id", ondelete="CASCADE"), nullable=False)
    index = Column(Integer, nullable=False)
    content = Column(Text, nullable=False)
    context = Column(Text, default="")
    metadata_ = Column("metadata", JSON, default=dict)
    gold_labels = Column(JSON, default=dict)

    dataset = relationship("Dataset", back_populates="items")


class Pipeline(Base):
    __tablename__ = "pipelines"

    id = Column(Integer, primary_key=True, autoincrement=True)
    project_id = Column(Integer, ForeignKey("projects.id", ondelete="CASCADE"), nullable=False)
    steps = Column(JSON, nullable=False)  # list of step dicts
    auto_generated = Column(Boolean, default=True)

    project = relationship("Project", back_populates="pipelines")


class AnnotationJob(Base):
    __tablename__ = "annotation_jobs"

    id = Column(Integer, primary_key=True, autoincrement=True)
    project_id = Column(Integer, ForeignKey("projects.id", ondelete="CASCADE"), nullable=False)
    dataset_id = Column(Integer, ForeignKey("datasets.id"), nullable=False)
    pipeline_id = Column(Integer, ForeignKey("pipelines.id"), nullable=False)
    status = Column(Enum(JobStatus), default=JobStatus.PENDING)
    total_items = Column(Integer, default=0)
    completed_items = Column(Integer, default=0)
    failed_items = Column(Integer, default=0)
    total_tokens = Column(Integer, default=0)
    total_cost = Column(Float, default=0.0)
    created_at = Column(DateTime, server_default=func.now())
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())

    project = relationship("Project", back_populates="jobs")
    results = relationship("AnnotationResult", back_populates="job", cascade="all, delete-orphan")
    calibration_runs = relationship("CalibrationRun", back_populates="job", cascade="all, delete-orphan")


class AnnotationResult(Base):
    __tablename__ = "annotation_results"

    id = Column(Integer, primary_key=True, autoincrement=True)
    job_id = Column(Integer, ForeignKey("annotation_jobs.id", ondelete="CASCADE"), nullable=False)
    data_item_id = Column(Integer, ForeignKey("data_items.id"), nullable=False)
    step_order = Column(Integer, default=0)
    dimension_name = Column(String(255), nullable=False)
    predicted_label = Column(String(255), default="")
    reasoning = Column(Text, default="")
    tokens_used = Column(Integer, default=0)

    job = relationship("AnnotationJob", back_populates="results")


class CodebookDraft(Base):
    """A draft codebook produced by CodebookAgent from user-provided materials.
    Project-agnostic until Accept; binds to a project on acceptance."""
    __tablename__ = "codebook_drafts"

    id = Column(Integer, primary_key=True, autoincrement=True)
    source = Column(String(32), nullable=False)      # upload|paste|preset|scratch
    source_filename = Column(String(512), default="")
    source_bytes = Column(Integer, default=0)
    status = Column(String(32), default="pending")   # pending|ingesting|drafting|ready|failed
    error_message = Column(Text, default="")
    draft_json = Column(JSON, default=dict)          # CodebookDef + _meta
    cleaned_data = Column(JSON, default=list)        # analysis-friendly rows (empty if N/A)
    warnings = Column(JSON, default=list)
    critic_flags = Column(JSON, default=list)
    drafter_model = Column(String(100), default="")
    accepted_for_project_id = Column(Integer, ForeignKey("projects.id"), nullable=True)
    created_at = Column(DateTime, server_default=func.now())
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())


class OptimizerRun(Base):
    """A single prompt-optimization run on one codebook dimension."""
    __tablename__ = "optimizer_runs"

    id = Column(Integer, primary_key=True, autoincrement=True)
    project_id = Column(Integer, ForeignKey("projects.id", ondelete="CASCADE"), nullable=False)
    gold_dataset_id = Column(Integer, ForeignKey("datasets.id"), nullable=True)
    optimizer_name = Column(String(64), nullable=False)   # reflect_agent|gepa|mipro|opro
    dimension_name = Column(String(255), nullable=False)
    status = Column(String(32), default="pending")        # pending|running|completed|failed
    budget = Column(Integer, default=5)
    train_frac = Column(Float, default=0.7)
    initial_score = Column(Float, default=0.0)
    final_score = Column(Float, default=0.0)
    trajectory = Column(JSON, default=list)
    artifact = Column(JSON, default=dict)                 # rule_library for ReflectAgent
    optimized_prompt = Column(Text, default="")
    total_tokens = Column(Integer, default=0)
    total_cost = Column(Float, default=0.0)
    error = Column(Text, default="")
    created_at = Column(DateTime, server_default=func.now())
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())


class ReflectMemoryVersion(Base):
    """Cumulative reflection-rule library, versioned per (project, dimension).

    Each new reflect_agent run writes a new row whose ``rules_json`` contains
    *all* rules (prior versions + newly distilled), and whose ``version`` is one
    higher than the previous row for the same (project_id, dimension_name).
    Older rows are kept as an audit trail. Mirrors the
    ``memory.vNNN.json`` convention from the demo prototype.
    """
    __tablename__ = "reflect_memory_versions"

    id = Column(Integer, primary_key=True, autoincrement=True)
    project_id = Column(Integer, ForeignKey("projects.id", ondelete="CASCADE"), nullable=False)
    dimension_name = Column(String(255), nullable=False)
    version = Column(Integer, nullable=False)
    rules_json = Column(JSON, default=list)
    new_rules_count = Column(Integer, default=0)
    source_optimizer_run_id = Column(Integer, ForeignKey("optimizer_runs.id"), nullable=True)
    created_at = Column(DateTime, server_default=func.now())


class CalibrationRun(Base):
    __tablename__ = "calibration_runs"

    id = Column(Integer, primary_key=True, autoincrement=True)
    project_id = Column(Integer, ForeignKey("projects.id", ondelete="CASCADE"), nullable=False)
    job_id = Column(Integer, ForeignKey("annotation_jobs.id", ondelete="CASCADE"), nullable=False)
    gold_dataset_id = Column(Integer, ForeignKey("datasets.id"), nullable=False)
    metrics_json = Column(JSON, default=dict)
    error_patterns = Column(JSON, default=list)
    rules_generated = Column(JSON, default=list)
    created_at = Column(DateTime, server_default=func.now())

    job = relationship("AnnotationJob", back_populates="calibration_runs")
