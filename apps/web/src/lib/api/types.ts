// ---------------------------------------------------------------------------
// TypeScript types mirroring the 30ai Python backend models.
// Keep in sync with packages/database/src/database/models.py
// ---------------------------------------------------------------------------

/** Mirrors the Python `DocumentStatus` StrEnum. */
export enum DocumentStatus {
  UPLOADING = "uploading",
  UPLOADED = "uploaded",
  PROCESSING = "processing",
  PROCESSED = "processed",
  ERROR = "error",
}

/** Mirrors the Python `ProcessingJobStatus` StrEnum. */
export enum ProcessingJobStatus {
  PENDING = "pending",
  PROCESSING = "processing",
  COMPLETED = "completed",
  FAILED = "failed",
}

/** Mirrors the Python `Organization` model. */
export interface Organization {
  id: string;
  name: string;
  clerk_organization_id: string | null;
  meta_data: Record<string, unknown>;
  created_at: string | null;
  updated_at: string | null;
}

/** Mirrors the Python `User` model. */
export interface User {
  id: string;
  clerk_user_id: string | null;
  email: string;
  full_name: string | null;
  organization_id: string;
  meta_data: Record<string, unknown>;
  created_at: string | null;
  updated_at: string | null;
}

/** Mirrors the Python `Document` model. */
export interface Document {
  id: string;
  organization_id: string;
  user_id: string;
  filename: string;
  file_type: string;
  file_size: number | null;
  s3_key: string | null;
  status: DocumentStatus;
  /** LLM-generated dense summary (150-250 words); null until processed. */
  summary: string | null;
  meta_data: Record<string, unknown>;
  created_at: string | null;
  updated_at: string | null;
}

/** Mirrors the Python `DocumentSearchResult` Pydantic model. */
export interface DocumentSearchResult {
  id: string;
  organization_id: string;
  user_id: string;
  filename: string;
  s3_key: string | null;
  file_type: string;
  file_size: number | null;
  status: DocumentStatus;
  created_at: string | null;
  updated_at: string | null;
  relevance: number;
}

/** Response from `GET /api/documents/{document_id}`. */
export interface DocumentDetail extends Document {
  /** Processed markdown content read from object storage; null when unavailable. */
  markdown_content: string | null;
}

/** Mirrors the Python `ProcessingJob` model. */
export interface ProcessingJob {
  id: string;
  document_id: string;
  job_type: string;
  status: ProcessingJobStatus;
  celery_task_id: string | null;
  error_message: string | null;
  meta_data: Record<string, unknown>;
  started_at: string | null;
  completed_at: string | null;
  created_at: string | null;
  updated_at: string | null;
}

/** Response from `GET /api/documents/upload-url/{file_path}`. */
export interface UploadUrlResponse {
  success: boolean;
  url: string;
  bucket: string;
  key: string;
  method: string;
  expires_in: number;
  message: string;
  job_id: string;
}

/** Response from `GET /api/documents/{document_id}/download`. */
export interface DownloadDocumentResponse {
  success: boolean;
  url: string;
  filename: string;
  key: string;
  method: string;
  expires_in: number;
  message: string;
}

/** Response from `POST /api/documents/{job_id}/process`. */
export interface ProcessDocumentResponse {
  message: string;
  document_id: string;
  task_id: string;
  status: string;
}

/** Response from `DELETE /api/documents/{document_id}`. */
export interface DeleteDocumentResponse {
  success: boolean;
  message: string;
  document_id: string;
}

/** Health check response. */
export interface HealthCheckResponse {
  status: string;
}

/** Root endpoint response. */
export interface RootResponse {
  message: string;
}
