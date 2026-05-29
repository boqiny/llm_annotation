from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.agents.reflect_memory import apply_human_feedback, apply_rules_to_prompt
from app.api import optimizers
from app.api import results
from app.models.tables import AnnotationJob, AnnotationResult, Base, DataItem, Dataset, JobStatus, Pipeline, Project, ReflectMemoryVersion


@pytest.fixture
async def db_session(tmp_path: Path):
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'test.db'}")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    maker = async_sessionmaker(engine, expire_on_commit=False)
    async with maker() as session:
        yield session

    await engine.dispose()


async def test_apply_human_feedback_merges_structured_rules(monkeypatch):
    async def fake_call_llm(**_kwargs):
        return SimpleNamespace(text="""```json
[
  {
    "id": "tense_boundary",
    "target_labels": ["Low", "High"],
    "boundary": "Past-tense memories should not be treated as current disclosure.",
    "positive_cues": ["current feelings"],
    "negative_cues": ["past-tense recollection"],
    "rule": "Use High only for current, explicit self-disclosure."
  },
  {
    "id": "invalid_rule",
    "rule": "This should be filtered because it has no boundary."
  }
]
```""")

    monkeypatch.setattr("app.agents.reflect_memory.call_llm", fake_call_llm)

    existing = [
        {
            "id": "tense_boundary",
            "boundary": "old boundary",
            "rule": "old rule",
        },
        {
            "id": "keep_me",
            "boundary": "Existing unrelated rule.",
            "rule": "Keep this rule.",
        },
    ]

    merged = await apply_human_feedback(
        feedback_text="The model over-labels past-tense experiences as High.",
        dimension_name="self_disclosure",
        label_defs="- Low: no disclosure\n- High: explicit disclosure",
        existing_rules=existing,
        provider="openai",
        model="test-model",
        api_key="test-key",
    )

    assert len(merged) == 2
    by_id = {r["id"]: r for r in merged}
    assert by_id["tense_boundary"]["boundary"] == "Past-tense memories should not be treated as current disclosure."
    assert by_id["keep_me"]["rule"] == "Keep this rule."
    assert "invalid_rule" not in by_id


async def test_apply_human_feedback_returns_existing_rules_on_llm_failure(monkeypatch):
    async def fake_call_llm(**_kwargs):
        raise RuntimeError("provider unavailable")

    monkeypatch.setattr("app.agents.reflect_memory.call_llm", fake_call_llm)

    existing = [{"id": "stable", "boundary": "Keep this.", "rule": "Do not change."}]

    merged = await apply_human_feedback(
        feedback_text="Please fix this.",
        dimension_name="tone",
        label_defs="",
        existing_rules=existing,
        provider="openai",
        model="test-model",
        api_key="test-key",
    )

    assert merged == existing


async def test_apply_rules_to_prompt_returns_clean_updated_prompt(monkeypatch):
    async def fake_call_llm(**_kwargs):
        return SimpleNamespace(text="```text\nUpdated prompt with calibration guidance.\n```")

    monkeypatch.setattr("app.agents.reflect_memory.call_llm", fake_call_llm)

    updated = await apply_rules_to_prompt(
        base_prompt="Original prompt.",
        rules=[{"id": "r1", "boundary": "Clarify Low vs High."}],
        dimension_name="self_disclosure",
        provider="openai",
        model="test-model",
        api_key="test-key",
    )

    assert updated == "Updated prompt with calibration guidance."


async def test_feedback_endpoint_persists_raw_feedback_text_and_utc_created_at(monkeypatch, db_session):
    async def fake_apply_human_feedback(**kwargs):
        assert kwargs["feedback_text"] == "Use Low for hypothetical statements.\nKeep this exact text."
        return [{"id": "hypothetical", "boundary": "Hypothetical statements are not actual disclosures."}]

    monkeypatch.setattr(optimizers, "apply_human_feedback", fake_apply_human_feedback)

    project = Project(name="Human feedback test", llm_provider="openai", llm_model="test-model")
    db_session.add(project)
    await db_session.commit()
    await db_session.refresh(project)

    response = await optimizers.apply_feedback(
        project_id=project.id,
        body=optimizers._FeedbackRequest(
            dimension_name="self_disclosure",
            feedback="Use Low for hypothetical statements.\nKeep this exact text.",
        ),
        db=db_session,
    )

    assert response["version"] == 1
    assert response["feedback_text"] == "Use Low for hypothetical statements.\nKeep this exact text."
    assert response["created_at"].endswith("Z")

    row = (
        await db_session.execute(select(ReflectMemoryVersion).where(ReflectMemoryVersion.id == response["id"]))
    ).scalars().one()
    assert row.feedback_text == "Use Low for hypothetical statements.\nKeep this exact text."
    assert row.rules_json == [{"id": "hypothetical", "boundary": "Hypothetical statements are not actual disclosures."}]


async def test_preview_does_not_write_and_commit_updates_pipeline(monkeypatch, tmp_path, db_session):
    async def fake_apply_rules_to_prompt(**kwargs):
        assert kwargs["base_prompt"] == "Original prompt."
        return "Updated prompt."

    monkeypatch.setattr(optimizers, "apply_rules_to_prompt", fake_apply_rules_to_prompt)
    monkeypatch.setattr(optimizers, "project_paths", lambda _project_id: {"prompts": tmp_path / "prompts"})

    project = Project(name="Prompt update test", llm_provider="openai", llm_model="test-model")
    db_session.add(project)
    await db_session.commit()
    await db_session.refresh(project)

    memory = ReflectMemoryVersion(
        project_id=project.id,
        dimension_name="self_disclosure",
        version=1,
        rules_json=[{"id": "r1", "boundary": "Clarify Low vs High."}],
        new_rules_count=1,
        feedback_text="Correction text.",
    )
    pipeline = Pipeline(
        project_id=project.id,
        steps=[{"name": "self_disclosure", "dimensions": ["self_disclosure"], "prompt": "Original prompt."}],
        auto_generated=True,
    )
    db_session.add_all([memory, pipeline])
    await db_session.commit()
    await db_session.refresh(pipeline)

    preview = await optimizers.preview_prompt(
        project_id=project.id,
        body=optimizers._PreviewRequest(dimension_name="self_disclosure"),
        db=db_session,
    )

    assert preview["old_prompt"] == "Original prompt."
    assert preview["new_prompt"] == "Updated prompt."

    unchanged = await db_session.get(Pipeline, pipeline.id)
    assert unchanged.steps[0]["prompt"] == "Original prompt."

    commit = await optimizers.commit_prompt(
        project_id=project.id,
        body=optimizers._CommitRequest(dimension_name="self_disclosure", new_prompt="Updated prompt."),
        db=db_session,
    )

    assert commit == {"ok": True, "pipeline_id": pipeline.id, "dimension_name": "self_disclosure"}

    updated = await db_session.get(Pipeline, pipeline.id)
    assert updated.steps[0]["prompt"] == "Updated prompt."
    assert (tmp_path / "prompts" / "self_disclosure" / "human_memory" / "v001.txt").read_text() == "Updated prompt."


async def test_feedback_batch_preview_is_dry_run_and_commit_saves_memory_and_prompt(monkeypatch, tmp_path, db_session):
    async def fake_apply_human_feedback(**kwargs):
        assert kwargs["feedback_text"] == "1. First correction.\n\n2. Second correction."
        return [
            {"id": "first", "boundary": "First generated boundary."},
            {"id": "second", "boundary": "Second generated boundary."},
        ]

    async def fake_apply_rules_to_prompt(**kwargs):
        assert [r["id"] for r in kwargs["rules"]] == ["first", "second"]
        return "Batch-updated prompt."

    monkeypatch.setattr(optimizers, "apply_human_feedback", fake_apply_human_feedback)
    monkeypatch.setattr(optimizers, "apply_rules_to_prompt", fake_apply_rules_to_prompt)
    monkeypatch.setattr(optimizers, "project_paths", lambda _project_id: {"prompts": tmp_path / "prompts"})

    project = Project(name="Batch feedback test", llm_provider="openai", llm_model="test-model")
    db_session.add(project)
    await db_session.commit()
    await db_session.refresh(project)

    pipeline = Pipeline(
        project_id=project.id,
        steps=[{"name": "self_disclosure", "dimensions": ["self_disclosure"], "prompt": "Original prompt."}],
        auto_generated=True,
    )
    db_session.add(pipeline)
    await db_session.commit()
    await db_session.refresh(pipeline)

    preview = await optimizers.preview_feedback_batch(
        project_id=project.id,
        body=optimizers._FeedbackBatchPreviewRequest(
            dimension_name="self_disclosure",
            feedbacks=["First correction.", "Second correction."],
        ),
        db=db_session,
    )

    assert preview["old_prompt"] == "Original prompt."
    assert preview["new_prompt"] == "Batch-updated prompt."
    assert preview["memory_version"] == 1
    assert [r["id"] for r in preview["rules"]] == ["first", "second"]
    assert (await db_session.execute(select(ReflectMemoryVersion))).scalars().all() == []

    commit = await optimizers.commit_feedback_batch(
        project_id=project.id,
        body=optimizers._FeedbackBatchCommitRequest(
            dimension_name="self_disclosure",
            feedbacks=["First correction.", "Second correction."],
            rules=preview["rules"],
            new_prompt=preview["new_prompt"],
        ),
        db=db_session,
    )

    assert commit["ok"] is True
    assert commit["memory"]["version"] == 1
    assert commit["memory"]["feedback_text"] == "1. First correction.\n\n2. Second correction."

    rows = (await db_session.execute(select(ReflectMemoryVersion))).scalars().all()
    assert len(rows) == 1
    assert rows[0].rules_json == preview["rules"]

    updated = await db_session.get(Pipeline, pipeline.id)
    assert updated.steps[0]["prompt"] == "Batch-updated prompt."
    assert (tmp_path / "prompts" / "self_disclosure" / "human_memory" / "v001.txt").read_text() == "Batch-updated prompt."


async def test_feedback_evidence_returns_content_gold_prediction_and_mismatches(db_session):
    project = Project(name="Evidence test")
    db_session.add(project)
    await db_session.commit()
    await db_session.refresh(project)

    dataset = Dataset(project_id=project.id, name="Gold", total_items=2, is_gold=True)
    pipeline = Pipeline(project_id=project.id, steps=[], auto_generated=True)
    db_session.add_all([dataset, pipeline])
    await db_session.commit()
    await db_session.refresh(dataset)
    await db_session.refresh(pipeline)

    item_match = DataItem(
        dataset_id=dataset.id,
        index=0,
        content="I feel calm today.",
        gold_labels={"self_disclosure": "High"},
    )
    item_mismatch = DataItem(
        dataset_id=dataset.id,
        index=1,
        content="If I felt calm, I would say so.",
        gold_labels={"self_disclosure": "Low"},
    )
    db_session.add_all([item_match, item_mismatch])
    await db_session.commit()
    await db_session.refresh(item_match)
    await db_session.refresh(item_mismatch)

    job = AnnotationJob(
        project_id=project.id,
        dataset_id=dataset.id,
        pipeline_id=pipeline.id,
        status=JobStatus.COMPLETED,
        total_items=2,
        completed_items=2,
    )
    db_session.add(job)
    await db_session.commit()
    await db_session.refresh(job)

    db_session.add_all([
        AnnotationResult(
            job_id=job.id,
            data_item_id=item_match.id,
            dimension_name="self_disclosure",
            predicted_label="High",
            reasoning="Current personal state.",
        ),
        AnnotationResult(
            job_id=job.id,
            data_item_id=item_mismatch.id,
            dimension_name="self_disclosure",
            predicted_label="High",
            reasoning="Mistakenly treated hypothetical as disclosure.",
        ),
    ])
    await db_session.commit()

    evidence = await results.get_feedback_evidence(
        project_id=project.id,
        job_id=job.id,
        dimension="self_disclosure",
        db=db_session,
    )

    assert [row["is_mismatch"] for row in evidence] == [True, False]
    assert evidence[0]["content"] == "If I felt calm, I would say so."
    assert evidence[0]["gold_label"] == "Low"
    assert evidence[0]["predicted_label"] == "High"
    assert evidence[0]["reasoning"] == "Mistakenly treated hypothetical as disclosure."

    mismatches = await results.get_feedback_evidence(
        project_id=project.id,
        job_id=job.id,
        dimension="self_disclosure",
        mismatches_only=True,
        db=db_session,
    )

    assert len(mismatches) == 1
    assert mismatches[0]["item_id"] == item_mismatch.id


async def test_delete_memory_version_removes_only_matching_project_row(db_session):
    project = Project(name="Delete memory test")
    other_project = Project(name="Other project")
    db_session.add_all([project, other_project])
    await db_session.commit()
    await db_session.refresh(project)
    await db_session.refresh(other_project)

    row = ReflectMemoryVersion(
        project_id=project.id,
        dimension_name="tone",
        version=1,
        rules_json=[],
    )
    other_row = ReflectMemoryVersion(
        project_id=other_project.id,
        dimension_name="tone",
        version=1,
        rules_json=[],
    )
    db_session.add_all([row, other_row])
    await db_session.commit()
    await db_session.refresh(row)
    await db_session.refresh(other_row)

    await optimizers.delete_memory_version(project_id=project.id, version_id=row.id, db=db_session)

    assert await db_session.get(ReflectMemoryVersion, row.id) is None
    assert await db_session.get(ReflectMemoryVersion, other_row.id) is not None
