"""SQLAlchemy async engine and session factory."""
from __future__ import annotations

from sqlalchemy import event
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.config import settings

engine = create_async_engine(settings.DATABASE_URL, echo=False)


# SQLite does not enforce foreign keys by default, which means our
# ``ondelete=CASCADE`` declarations on Project → (Codebook, Dataset,
# Pipeline, AnnotationJob) are no-ops. Without this, deleting a project
# leaves orphan optimizer_runs / data_items / etc., which then leak into
# fresh projects whose ids happen to match. Enable per-connection.
@event.listens_for(engine.sync_engine, "connect")
def _enable_sqlite_fks(dbapi_connection, _connection_record):
    if "sqlite" in settings.DATABASE_URL:
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()


async_session = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)


async def get_db():
    """FastAPI dependency that yields an async DB session."""
    async with async_session() as session:
        yield session
