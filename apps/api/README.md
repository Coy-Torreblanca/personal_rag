# API Documentation

## Building and Running

See main DEPLOYMENT.md.

## Environment Variables

The API requires the following environment variables in addition to the
standard database and S3 configuration:

| Variable | Description |
|----------|-------------|
| `OPENAI_API_KEY` | OpenAI API key (used for embedding queries with ``text-embedding-3-small``) |
| `COHERE_API_KEY` | Cohere API key (used for re-ranking search results) |
| `BUCKET_NAME` | S3/R2 bucket name for document storage |
| `DATABASE_URL` | PostgreSQL connection string |
| `REDIS_URL` | Redis connection string for Celery broker |
| `R2_ACCESS_ID` | R2 access key ID |
| `R2_SECRET_ACCESS_KEY` | R2 secret access key |

These are configured in ``docker-compose.yml`` at the repository root.

## Semantic Search

The API provides a semantic search endpoint that retrieves documents by
meaning (not just keyword matching).

### Search Documents

```bash
curl -G "http://localhost:8000/api/documents/search" \
  --data-urlencode "query=annual sales figures Q4"
```

**Response** (example):
```json
[
  {
    "id": "...",
    "organization_id": "...",
    "user_id": "...",
    "filename": "q4-report.pdf",
    "s3_key": "org-id/q4-report.pdf",
    "file_type": "application/pdf",
    "file_size": 204800,
    "status": "processed",
    "created_at": "2026-01-15T10:30:00Z",
    "updated_at": "2026-01-15T11:00:00Z",
    "relevance": 0.95
  }
]
```

The search pipeline:
1. Embeds the query using OpenAI ``text-embedding-3-small``.
2. Retrieves the top-``VECTOR_SEARCH_CANDIDATE_LIMIT`` (currently 30)
   most similar chunks from the vector store, merging each hit with its
   immediate neighbours. The candidate count is a tunable constant in
   ``src/document_search.py``.
3. Re-ranks results using Cohere's ``rerank-english-v3.0`` cross-encoder.
4. Deduplicates by document and returns results sorted by descending relevance.

## Document Detail

`GET /api/documents/{document_id}` returns a single document's metadata,
LLM-generated summary, and processed markdown content in one request —
the endpoint that powers the document detail dialog in the web UI.

### Fetch Document Details

```bash
curl "http://localhost:8000/api/documents/{document_id}"
```

**Response** (example):
```json
{
  "id": "...",
  "organization_id": "...",
  "user_id": "...",
  "filename": "q4-report.pdf",
  "file_type": "application/pdf",
  "file_size": 204800,
  "s3_key": "org-id/q4-report.pdf",
  "status": "processed",
  "summary": "...",
  "meta_data": {},
  "markdown_content": "# Q4 Report\n\n...",
  "created_at": "2026-01-15T10:30:00Z",
  "updated_at": "2026-01-15T11:00:00Z"
}
```

Notes:
- `summary` is written by the DeepSeek worker stage during document
  processing and is `null` while a document is still processing.
- `markdown_content` is read from object storage: plain-text sources
  (`.txt`, `.md`, `.html`, ...) are read from the original object key
  (they are already markdown); every other file type is read from
  `<s3_key>.md`. It degrades to `null` — rather than a 500 — when the
  markdown object does not exist yet, was cleaned up, or could not be
  fetched.
- A non-existent (or non-UUID) document id returns `404`/`422` respectively.

## Testing Presigned URLs

The API provides endpoints to generate presigned URLs for uploading documents to S3-compatible storage (Cloudflare R2).

### Test Data
- **Organization ID**: `70885aed-0503-4656-bb72-368a26758575`
- **User ID**: `c06ed70c-b7bd-45a4-d0d7-0a978d44d956`

If you lose your postgres data, you will need to re-insert above objects.

### Step 1: Get Presigned Upload URL

Request a presigned URL from the API:

```bash
curl -G "http://localhost:8000/api/documents/upload-url/docker-compose.yml" \
  --data-urlencode "organization_id=70885aed-0503-4656-bb72-368a26758575" \
  --data-urlencode "user_id=c06ed70c-b7bd-45a4-d0d7-0a978d44d956" \
  --data-urlencode "content_type=application/x-yaml"
```
**Response** (example):
```json
{
  "upload_url": "https://70885aed0503f656bb72368a26758575.r2.cloudflarestorage.com/30aidev/70885aed-0503-4656-bb72-368a26758575/test/my-document.pdf?X-Amz-Algorithm=AWS4-HMAC-SHA256&X-Amz-Credential=...",
  "document_id": "{uuid}"
}
```
You will see a new Document row and Job row. Follow their statuses as you prceed with below steps. Check database testing cheatsheet for details.

### Step 2: Upload File Using Presigned URL

Use the presigned URL to upload your file directly to S3:

```bash
curl -v -X PUT -H "Content-Type: application/x-yaml" --data-binary "@docker-compose.yml" \
  "{presigned_url}"
```
### Step 3: Process Document

Get job id - see database TESTING.md for how to open shell.
```sql
select * from processing_jobs;
```

```bash
curl -X POST http://localhost:8000/api/documents/{job_id}/process
```

Check logs -
```bash
podman logs 30ai-workers
```

Note - s3-docling-ocr-pipeline is the app name as defined in workers app.
```bash
uv run python3 -m modal app logs s3-docling-ocr-pipeline
```
