from datetime import datetime
from enum import StrEnum
from typing import Any
from uuid import UUID, uuid4

from sqlmodel import (
    SQLModel,
    Field,
    Relationship,
    Column,
    JSON,
    Text,
    Index,
)
from sqlalchemy import DateTime
from sqlalchemy.sql import func

# For vector embeddings (if using pgvector)
from pgvector.sqlalchemy import Vector


class DocumentStatus(StrEnum):
    """Document status enum."""

    UPLOADING = "uploading"
    UPLOADED = "uploaded"
    PROCESSING = "processing"
    PROCESSED = "processed"
    ERROR = "error"


class ProcessingJobStatus(StrEnum):
    """Processing job status enum."""

    PENDING = "pending"
    PROCESSING = "processing"
    COMPLETED = "completed"
    FAILED = "failed"


class OrganizationBase(SQLModel):
    """Base organization model."""

    name: str = Field(max_length=255, nullable=False)
    clerk_organization_id: str | None = Field(
        default=None, max_length=255, unique=True, index=True
    )
    meta_data: dict[str, object] = Field(default={}, sa_column=Column(JSON))


class Organization(OrganizationBase, table=True):
    """Organization model for multi-tenancy."""

    __tablename__ = "organizations"  # pyright: ignore[reportUnannotatedClassAttribute, reportAssignmentType]

    id: UUID = Field(default_factory=uuid4, primary_key=True)
    created_at: datetime | None = Field(
        default=None,
        sa_column=Column(DateTime(timezone=True), server_default=func.now()),
    )
    updated_at: datetime | None = Field(
        default=None,
        sa_column=Column(
            DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
        ),
    )

    # Relationships
    users: list["User"] = Relationship(back_populates="organization")
    documents: list["Document"] = Relationship(back_populates="organization")


class UserBase(SQLModel):
    """Base user model."""

    clerk_user_id: str | None = Field(
        default=None, max_length=255, unique=True, index=True
    )
    email: str = Field(max_length=255, nullable=False, index=True)
    full_name: str | None = Field(default=None, max_length=255)
    organization_id: UUID = Field(foreign_key="organizations.id", nullable=False)
    meta_data: dict[str, object] = Field(default={}, sa_column=Column(JSON))


class User(UserBase, table=True):
    """User model synced from Clerk."""

    # type: ignore[assignment]
    __tablename__ = "users"  # pyright: ignore[reportUnannotatedClassAttribute, reportAssignmentType]

    id: UUID = Field(default_factory=uuid4, primary_key=True)
    created_at: datetime | None = Field(
        default=None,
        sa_column=Column(DateTime(timezone=True), server_default=func.now()),
    )
    updated_at: datetime | None = Field(
        default=None,
        sa_column=Column(
            DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
        ),
    )

    # Relationships
    organization: Organization = Relationship(back_populates="users")
    documents: list["Document"] = Relationship(back_populates="user")


class DocumentBase(SQLModel):
    """Base document model."""

    organization_id: UUID = Field(foreign_key="organizations.id", nullable=False)
    user_id: UUID = Field(foreign_key="users.id", nullable=False)
    filename: str = Field(max_length=255, nullable=False)
    file_type: str = Field(max_length=50, nullable=False)  # pdf, docx, txt, etc.
    file_size: int | None = Field(default=None)  # Size in bytes
    s3_key: str = Field(default=None, max_length=500)  # S3 object key
    status: DocumentStatus = Field(default=DocumentStatus.UPLOADED, max_length=50)
    meta_data: dict[str, object] = Field(default={}, sa_column=Column(JSON))


class Document(DocumentBase, table=True):
    """Document metadata model."""

    # type: ignore[assignment]
    __tablename__ = "documents"

    id: UUID = Field(default_factory=uuid4, primary_key=True)
    created_at: datetime | None = Field(
        default=None,
        sa_column=Column(DateTime(timezone=True), server_default=func.now()),
    )
    updated_at: datetime | None = Field(
        default=None,
        sa_column=Column(
            DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
        ),
    )

    # Relationships
    organization: Organization = Relationship(back_populates="documents")
    user: User = Relationship(back_populates="documents")
    chunks: list["DocumentChunk"] = Relationship(
        back_populates="document",
        sa_relationship_kwargs={"cascade": "all, delete-orphan"},
    )

    # Indexes
    __table_args__: tuple[Index, ...] = (  # type: ignore
        Index("idx_documents_organization_status", "organization_id", "status"),
        Index("idx_documents_user", "user_id"),
    )


class DocumentChunkBase(SQLModel):
    """Base document chunk model."""

    document_id: UUID = Field(foreign_key="documents.id", nullable=False)
    organization_id: UUID = Field(foreign_key="organizations.id", nullable=False)
    chunk_index: int = Field(nullable=False)  # Order of chunk in document
    content: str = Field(sa_column=Column(Text, nullable=False))
    embedding: list[float] | None = Field(
        default=None,
        sa_column=Column(Vector(1536)),  # 1536 dimensions for OpenAI embeddings
    )
    meta_data: dict[str, object] = Field(default={}, sa_column=Column(JSON))


class DocumentChunk(DocumentChunkBase, table=True):
    """Document chunk with vector embedding."""

    # type: ignore[assignment]
    __tablename__ = "document_chunks"

    id: UUID = Field(default_factory=uuid4, primary_key=True)
    created_at: datetime | None = Field(
        default=None,
        sa_column=Column(DateTime(timezone=True), server_default=func.now()),
    )
    updated_at: datetime | None = Field(
        default=None,
        sa_column=Column(
            DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
        ),
    )

    # Relationships
    document: Document = Relationship(back_populates="chunks")
    organization: Organization = Relationship()

    # Indexes
    __table_args__: tuple[Index, ...] = (  # type: ignore
        Index("idx_document_chunks_document", "document_id"),
        Index("idx_document_chunks_organization", "organization_id"),
        # For vector similarity search (uncomment when needed)
        # Index("idx_document_chunks_embedding", "embedding", postgresql_using="ivfflat", postgresql_with={"lists": 100}),
    )


class ProcessingJobBase(SQLModel):
    """Base processing job model."""

    document_id: UUID = Field(foreign_key="documents.id", nullable=False)
    job_type: str = Field(max_length=50, nullable=False)  # parsing, embedding, etc.
    status: ProcessingJobStatus = Field(
        default=ProcessingJobStatus.PENDING, max_length=50
    )
    celery_task_id: str | None = Field(default=None, max_length=255)
    error_message: str | None = Field(default=None, sa_column=Column(Text))
    meta_data: dict[str, object] = Field(default={}, sa_column=Column(JSON))
    started_at: datetime | None = Field(default=None)
    completed_at: datetime | None = Field(default=None)


class ProcessingJob(ProcessingJobBase, table=True):
    """Background processing job tracking."""

    # type: ignore[assignment]
    __tablename__ = "processing_jobs"

    id: UUID = Field(default_factory=uuid4, primary_key=True)
    created_at: datetime | None = Field(
        default=None,
        sa_column=Column(DateTime(timezone=True), server_default=func.now()),
    )
    updated_at: datetime | None = Field(
        default=None,
        sa_column=Column(
            DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
        ),
    )

    # Relationships
    document: Document = Relationship()

    # Indexes
    __table_args__: tuple[Index, ...] = (  # type: ignore
        Index("idx_processing_jobs_document", "document_id"),
        Index("idx_processing_jobs_status", "status"),
    )
