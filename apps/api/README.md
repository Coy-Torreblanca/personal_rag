# API Documentation

## Building and Running

See main DEPLOYMENT.md.

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
