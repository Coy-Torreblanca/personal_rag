import os
from typing import Generator

from sqlmodel import SQLModel, create_engine, Session
from .models import Organization, User, Document, DocumentChunk, ProcessingJob


def get_db_url() -> str:
    """Get database URL from environment variables."""
    return os.getenv(
        "DATABASE_URL",
        "postgresql://30ai_user:30ai_password@localhost:5432/30ai_db",
    )


def create_engine_from_env():
    """Create SQLAlchemy engine from environment variables."""
    database_url = get_db_url()
    return create_engine(database_url, pool_pre_ping=True, pool_recycle=3600)


# Create engine and session factory
engine = create_engine_from_env()


def get_db() -> Generator[Session, None, None]:
    """Dependency to get database session."""
    db = Session(engine)
    try:
        yield db
    finally:
        db.close()


if __name__ == "__main__":
    db = Session(engine)

    user = User(
        email="",
        id="c06ed70c-b7bd-45a4-d0d7-0a978d44d956",
        organization_id="70885aed-0503-4656-bb72-368a26758575",
    )

    db.add(user)

    db.commit()
