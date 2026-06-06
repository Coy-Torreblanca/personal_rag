# API Documentation

## Building and Running

### To build image

**From project root**

```bash
podman build -t apitest -f apps/api/Dockerfile .
```

### To run container

```bash
podman run --rm -p 8000:8000 --env-file .env localhost/apitest
```

### To run the app

Stop the running container as needed.
```bash
podman stop <label>
podman rm <label>
```

```bash
podman-compose --env-file .env up -d --build api
```

## Testing Presigned URLs

The API provides endpoints to generate presigned URLs for uploading documents to S3-compatible storage (Cloudflare R2).

### Test Data
- **Organization ID**: `70885aed-0503-4656-bb72-368a26758575`
- **User ID**: `c06ed70c-b7bd-45a4-d0d7-0a978d44d956`

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
  "document_id": "<uuid>"
}
```

### Step 2: Upload File Using Presigned URL

Use the presigned URL to upload your file directly to S3:

```bash
curl -v -X PUT -H "Content-Type: application/x-yaml" --data-binary "@docker-compose.yml" \
  "https://70885aed0503f656bb72368a26758575.r2.cloudflarestorage.com/30aidev/70885aed-0503-4656-bb72-368a26758575/docker-compose.yml?X-Amz-Algorithm=AWS4-HMAC-SHA256&X-Amz-Credential=68410334538db91d3ca5ff569ec938b7%2F20260606%2Fauto%2Fs3%2Faws4_request&X-Amz-Date=20260606T203452Z&X-Amz-Expires=3600&X-Amz-SignedHeaders=content-type%3Bhost&X-Amz-Signature=780e12255cf07d0ec0fdbace1eaad042a092024a80fa3a918bd894c5eded4700"
```

**Notes**:
- Replace `/path/to/your/file.pdf` with the actual path to your file
- The presigned URL is valid for 1 hour (3600 seconds)
- The `-v` flag shows verbose output including response headers
- The URL from Step 1 response should be used directly

### Example Workflow

```bash
# 1. Get presigned URL
RESPONSE=$(curl -s -G "http://localhost:8000/api/documents/upload-url/test/my-document.pdf" \
  --data-urlencode "organization_id=70885aed-0503-4656-bb72-368a26758575" \
  --data-urlencode "user_id=c06ed70c-b7bd-45a4-d0d7-0a978d44d956" \
  --data-urlencode "file_type=application/pdf")

UPLOAD_URL=$(echo $RESPONSE | jq -r '.upload_url')
DOC_ID=$(echo $RESPONSE | jq -r '.document_id')

echo "Upload URL: $UPLOAD_URL"
echo "Document ID: $DOC_ID"

# 2. Upload file
curl -X PUT --data-binary "@/path/to/your/file.pdf" "$UPLOAD_URL"

# 3. Verify upload (check document status)
curl "http://localhost:8000/api/documents/$DOC_ID"
```

