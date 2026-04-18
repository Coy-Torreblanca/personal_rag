import os
from celery import Celery
from sqlmodel import Session

from packages.database.src.session import create_engine_from_env
from packages.database.src.models import Document, ProcessingJob

# Create Celery application
celery = Celery(
    "30ai_workers",
    broker=os.getenv("REDIS_URL", "redis://localhost:6379/0"),
    backend=os.getenv("REDIS_URL", "redis://localhost:6379/0"),
)

# Configure Celery
celery.conf.update(
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",
    timezone="UTC",
    enable_utc=True,
    task_track_started=True,
    task_time_limit=30 * 60,  # 30 minutes
    task_soft_time_limit=25 * 60,  # 25 minutes
    worker_prefetch_multiplier=1,
    worker_max_tasks_per_child=1000,
)

# Create database engine
engine = create_engine_from_env()


@celery.task(bind=True, name="process_document")
def process_document(self, document_id: str):
    """Process a document: parse, chunk, and generate embeddings."""
    
    # Create processing job record
    with Session(engine) as session:
        # Get document
        document = session.get(Document, document_id)
        if not document:
            raise ValueError(f"Document {document_id} not found")
        
        # Create processing job
        job = ProcessingJob(
            document_id=document_id,
            job_type="document_processing",
            status="processing",
            celery_task_id=self.request.id,
            started_at=self.request.started_at,
        )
        session.add(job)
        session.commit()
        
        try:
            # Update document status
            document.status = "processing"
            session.add(document)
            session.commit()
            
            # TODO: Implement actual document processing
            # 1. Download document from S3
            # 2. Parse document using unstructured
            # 3. Chunk document into smaller pieces
            # 4. Generate embeddings using OpenAI/Anthropic
            # 5. Store chunks and embeddings in database
            
            # Simulate processing
            import time
            time.sleep(2)  # Simulate work
            
            # Update job status
            job.status = "completed"
            job.completed_at = self.request.started_at  # Use current time
            
            # Update document status
            document.status = "processed"
            
            session.add(job)
            session.add(document)
            session.commit()
            
            return {
                "document_id": document_id,
                "status": "completed",
                "message": "Document processed successfully",
            }
            
        except Exception as e:
            # Update job status on error
            job.status = "failed"
            job.error_message = str(e)
            job.completed_at = self.request.started_at
            
            # Update document status
            document.status = "error"
            
            session.add(job)
            session.add(document)
            session.commit()
            
            raise


@celery.task(name="generate_embeddings")
def generate_embeddings(chunk_id: str, text: str):
    """Generate embeddings for a text chunk."""
    
    # TODO: Implement embedding generation
    # 1. Use OpenAI/Anthropic API to generate embeddings
    # 2. Store embeddings in database
    
    # For now, return a dummy embedding
    import numpy as np
    
    # Generate random embedding (1536 dimensions like OpenAI)
    embedding = np.random.randn(1536).tolist()
    
    return {
        "chunk_id": chunk_id,
        "embedding": embedding,
        "dimensions": 1536,
    }


@celery.task(name="health_check")
def health_check():
    """Health check task."""
    return {"status": "healthy", "service": "30ai-workers"}


if __name__ == "__main__":
    celery.start()