from __future__ import annotations

from pathlib import Path

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.api import results
from app.models.tables import (
    AnnotationJob,
    AnnotationResult,
    Base,
    DataItem,
    Dataset,
    JobStatus,
    Pipeline,
    Project,
)
from app.utils.file_parsers import parse_csv_dataset


@pytest.fixture
async def db_session(tmp_path: Path):
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'test.db'}")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    maker = async_sessionmaker(engine, expire_on_commit=False)
    async with maker() as session:
        yield session

    await engine.dispose()


async def test_long_format_csv_to_eval_metrics_end_to_end(db_session):
    """Paper/demo contract: labeled CSV parsing drives evidence + metrics.

    This avoids LLM calls by simulating annotation outputs, but covers the
    full persisted evaluation path used by the UI:
    long-format CSV -> DataItem.gold_labels -> AnnotationResult predictions
    -> Human feedback evidence -> metrics -> confusion matrix.
    """
    csv_content = """Row,Response ID,Coding theme,Level,Relevant quotes 
1,R_1,Listening strategy,Question-asking,"How did you come up with that?"
2,R_2,Listening strategy,Question-asking,"Tell me more about that."
2,R_2,Listening strategy,Paraphrase,"Tell me more about that."
3,R_3,Listening strategy,Sympathetic responsiveness,"I understand how hard that must feel."
4,R_4,Listening strategy,Back-channel response,"Uh-huh."
"""
    parsed_items = parse_csv_dataset(csv_content)

    assert len(parsed_items) == 4
    assert parsed_items[1]["gold_labels"] == {
        "Listening strategy": ["Question-asking", "Paraphrase"],
    }

    project = Project(name="Evaluation pipeline test")
    db_session.add(project)
    await db_session.commit()
    await db_session.refresh(project)

    dataset = Dataset(
        project_id=project.id,
        name="Mini Fiona-style labeled CSV",
        total_items=len(parsed_items),
        is_gold=True,
        file_type="csv",
    )
    pipeline = Pipeline(project_id=project.id, steps=[], auto_generated=True)
    db_session.add_all([dataset, pipeline])
    await db_session.commit()
    await db_session.refresh(dataset)
    await db_session.refresh(pipeline)

    data_items: list[DataItem] = []
    for item in parsed_items:
        row = DataItem(
            dataset_id=dataset.id,
            index=item["index"],
            content=item["content"],
            context=item.get("context", ""),
            metadata_=item.get("metadata", {}),
            gold_labels=item.get("gold_labels", {}),
        )
        db_session.add(row)
        data_items.append(row)
    await db_session.commit()
    for item in data_items:
        await db_session.refresh(item)

    job = AnnotationJob(
        project_id=project.id,
        dataset_id=dataset.id,
        pipeline_id=pipeline.id,
        status=JobStatus.COMPLETED,
        total_items=len(data_items),
        completed_items=len(data_items),
        source="human_feedback",
    )
    db_session.add(job)
    await db_session.commit()
    await db_session.refresh(job)

    dimension = "Listening Strategy (Bodie et al., 2012)"
    simulated_predictions = [
        "Question-Asking",              # exact/canonical match
        "Paraphrase",                   # acceptable list-valued gold label
        "Question-Asking",              # wrong; should be Sympathetic responsiveness
        "Back-Channel Response",        # punctuation/case-normalized match
    ]
    for item, prediction in zip(data_items, simulated_predictions):
        db_session.add(AnnotationResult(
            job_id=job.id,
            data_item_id=item.id,
            dimension_name=dimension,
            predicted_label=prediction,
            reasoning=f"Simulated prediction: {prediction}",
        ))
    await db_session.commit()

    evidence = await results.get_feedback_evidence(
        project_id=project.id,
        job_id=job.id,
        dimension=dimension,
        db=db_session,
    )

    by_content = {row["content"]: row for row in evidence}
    assert by_content["How did you come up with that?"]["match_status"] == "match"
    assert by_content["Tell me more about that."]["match_status"] == "partial"
    assert by_content["I understand how hard that must feel."]["match_status"] == "mismatch"
    assert by_content["Uh-huh."]["match_status"] == "match"

    review_rows = await results.get_feedback_evidence(
        project_id=project.id,
        job_id=job.id,
        dimension=dimension,
        mismatches_only=True,
        db=db_session,
    )
    assert [row["match_status"] for row in review_rows] == ["mismatch", "partial"]

    metrics = await results.get_metrics(project_id=project.id, job_id=job.id, db=db_session)
    metric = {row.dimension: row.metrics for row in metrics}[dimension]
    assert metric.n == 4
    assert metric.accuracy == 0.75
    assert metric.per_class["Question-Asking"]["tp"] == 1
    assert metric.per_class["Question-Asking"]["fp"] == 1
    assert metric.per_class["Sympathetic responsiveness"]["fn"] == 1
    # Supports are one per class. Question-Asking has precision=0.5,
    # recall=1.0, F1=2/3 because one Sympathetic item was predicted as
    # Question-Asking. Paraphrase and Back-Channel are perfect; Sympathetic is 0.
    assert round(metric.weighted_f1, 6) == round((2 / 3 + 1 + 0 + 1) / 4, 6)

    matrix = await results.get_confusion_matrix(
        project_id=project.id,
        job_id=job.id,
        dimension=dimension,
        db=db_session,
    )
    assert matrix["matrix"]["Question-Asking"]["Question-Asking"] == 1
    assert matrix["matrix"]["Paraphrase"]["Paraphrase"] == 1
    assert matrix["matrix"]["Sympathetic responsiveness"]["Question-Asking"] == 1
    assert matrix["matrix"]["Back-Channel Response"]["Back-Channel Response"] == 1
