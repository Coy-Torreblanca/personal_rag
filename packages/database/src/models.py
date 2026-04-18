from datetime import datetime
from typing import Optional, List
from uuid import UUID, uuid4

from sqlmodel import (
    SQLModel,
    Field,
    Relationship,
    Column,
    JSON,
    Text,
    Index,
    text,
)
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy import DateTime, String, Integer, BigInteger, ForeignKey
from sqlalchemy.sql import func


class OrganizationBase(SQLModel):
    """Base organization model."""
    
    name: str = Field(max_length=255, nullable=False)
    clerk_organization_id: Optional[str] = Field(
        default=None, max_length=255, unique=True, index=True
    )
    metadata: dict = Field(default={}, sa_column=Column(JSON))


class Organization(OrganizationBase, table=True):
    """Organization model for multi-tenancy."""
    
    __tablename__ = "organizations"
    
    id: UUID = Field(
        default_factory=uuid4,
        primary_key=True,
        sa_column=Column(PG_UUID(as_uuid=True), primary_key=True, default=uuid4)
    )
    created_at: datetime = Field(
        default_factory=datetime.utcnow,
        sa_column=Column(DateTime(timezone=True), server_default=func.now())
    )
    updated_at: datetime = Field(
        default_factory=datetime.utcnow,
        sa_column=Column(
            DateTime(timezone=True), 
            server_default=func.now(), 
            onupdate=func.now()
        )
    )
    
    # Relationships
    users: List["User"] = Relationship(back_populates="organization")
    documents: List["Document"] = Relationship(back_populates="organization")


class UserBase(SQLModel):
    """Base user model."""
    
    clerk_user_id: Optional[str] = Field(
        default=None, max_length=255, unique=True, index=True
    )
    email: str = Field(max_length=255, nullable=False, index=True)
    full_name: Optional[str] = Field(default=None, max_length=255)
    organization_id: UUID = Field(foreign_key="organizations.id", nullable=False)
    metadata: dict = Field(default={}, sa_column=Column(JSON))


class User(UserBase, table=True):
    """User model synced from Clerk."""
    
    __tablename__ = "users"
    
    id: UUID = Field(
        default_factory=uuid4,
        primary_key=True,
        sa_column=Column(PG_UUID(as_uuid=True), primary_key=True, default=uuid4)
    )
    created_at: datetime = Field(
        default_factory=datetime.utcnow,
        sa_column=Column(DateTime(timezone=True), server_default=func.now())
    )
    updated_at: datetime = Field(
        default_factory=datetime.utcnow,
        sa_column=Column(
            DateTime(timezone=True), 
            server_default=func.now(), 
            onupdate=func.now()
        )
    )
    
    # Relationships
    organization: Organization = Relationship(back_populates="users")
    documents: List["Document"] = Relationship(back_populates="user")


class DocumentBase(SQLModel):
    """Base document model."""
    
    organization_id: UUID = Field(foreign_key="organizations.id", nullable=False)
    user_id: UUID = Field(foreign_key="users.id", nullable=False)
    filename: str = Field(max_length=255, nullable=False)
    file_type: str = Field(max_length=50, nullable=False)  # pdf, docx, txt, etc.
    file_size: Optional[int] = Field(default=None)  # Size in bytes
    s3_key: Optional[str] = Field(default=None, max_length=500)  # S3 object key
    status: str = Field(
        default="uploaded", max_length=50
    )  # uploaded, processing, processed, error
    metadata: dict = Field(default={}, sa_column=Column(JSON))


class Document(DocumentBase, table=True):
    """Document metadata model."""
    
    __tablename__ = "documents"
    
    id: UUID = Field(
        default_factory=uuid4,
        primary_key=True,
        sa_column=Column(PG_UUID(as_uuid=True), primary_key=True, default=uuid4)
    )
    created_at: datetime = Field(
        default_factory=datetime.utcnow,
        sa_column=Column(DateTime(timezone=True), server_default=func.now())
    )
    updated_at: datetime = Field(
        default_factory=datetime.utcnow,
        sa_column=Column(
            DateTime(timezone=True), 
            server_default=func.now(), 
            onupdate=func.now()
        )
    )
    
    # Relationships
    organization: Organization = Relationship(back_populates="documents")
    user: User = Relationship(back_populates="documents")
    chunks: List["DocumentChunk"] = Relationship(
        back_populates="document", 
        sa_relationship_kwargs={"cascade": "all, delete-orphan"}
    )
    
    # Indexes
    __table_args__ = (
        Index("idx_documents_organization_status", "organization_id", "status"),
        Index("idx_documents_user", "user_id"),
    )


class DocumentChunkBase(SQLModel):
    """Base document chunk model."""
    
    document_id: UUID = Field(foreign_key="documents.id", nullable=False)
    organization_id: UUID = Field(foreign_key="organizations.id", nullable=False)
    chunk_index: int = Field(nullable=False)  # Order of chunk in document
    content: str = Field(sa_column=Column(Text, nullable=False))
    embedding: Optional[str] = Field(default=None)  # Will be vector type
    metadata: dict = Field(default={}, sa_column=Column(JSON))


class DocumentChunk(DocumentChunkBase, table=True):
    """Document chunk with vector embedding."""
    
    __tablename__ = "document_chunks"
    
    id: UUID = Field(
        default_factory=uuid4,
        primary_key=True,
        sa_column=Column(PG_UUID(as_uuid=True), primary_key=True, default=uuid4)
    )
    created_at: datetime = Field(
        default_factory=datetime.utcnow,
        sa_column=Column(DateTime(timezone=True), server_default=func.now())
    )
    updated_at: datetime = Field(
        default_factory=datetime.utcnow,
        sa_column=Column(
            DateTime(timezone=True), 
            server_default=func.now(), 
            onupdate=func.now()
        )
    )
    
    # Relationships
    document: Document = Relationship(back_populates="chunks")
    organization: Organization = Relationship()
    
    # Indexes
    __table_args__ = (
        Index("idx_document_chunks_document", "document_id"),
        Index("idx_document_chunks_organization", "organization_id"),
    )


class ProcessingJobBase(SQLModel):
    """Base processing job model."""
    
    document_id: UUID = Field(foreign_key="documents.id", nullable=False)
    job_type: str = Field(max_length=50, nullable=False)  # parsing, embedding, etc.
    status: str = Field(
        default="pending", max_length=50
    )  # pending, processing, completed, failed
    celery_task_id: Optional[str] = Field(default=None, max_length=255)
    error_message: Optional[str] = Field(default=None, sa_column=Column(Text))
    metadata: dict = Field(default={}, sa_column=Column(JSON))
    started_at: Optional[datetime] = Field(default=None)
    completed_at: Optional[datetime] = Field(default=None)


class ProcessingJob(ProcessingJobBase, table=True):
    """Background processing job tracking."""
    
    __tablename__ = "processing_jobs"
    
    id: UUID = Field(
        default_factory=uuid4,
        primary_key=True,
        sa_column=Column(PG_UUID(as_uuid=True), primary_key=True, default=uuid4)
    )
    created_at: datetime = Field(
        default_factory=datetime.utcnow,
        sa_column=Column(DateTime(timezone=True), server_default=func.now())
    )
    updated_at: datetime = Field(
        default_factory=datetime.utcnow,
        sa_column=Column(
            DateTime(timezone=True), 
            server_default=func.now(), 
            onupdate=func.now()
        )
    )
    
    # Relationships
    document: Document = Relationship()
    
    # Indexes
    __table_args__ = (
        Index("idx_processing_jobs_document", "document_id"),
        Index("idx_processing_jobs_status", "status"),
    )