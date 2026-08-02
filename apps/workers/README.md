# Workers

Workers is an app which deploys background jobs after receiving a signal from
Celery. It handles document ingestion for the 30ai platform: parse uploaded
documents into markdown, generate embeddings, and persist the results.

## Architecture

```
src/
  main.py                 — Celery app & task definitions (process_document)
  generate_embeddings.py  — Text chunking + OpenAI embedding pipeline
  parse_document.py       — Modal-hosted Docling parser (deployed separately)
```

## Process Document

`process_document` (defined in `src/main.py`) is the Celery task that runs the
full document-processing pipeline. It runs in three stages:

1. **Parse** — `parse_document()`
   - Plain-text files (`.txt`, `.md`, `.html`, `.yaml`, ...) are already
     markdown-compatible and skip the Modal/Docling parser entirely.
   - All other file types are sent to the Modal-hosted `DoclingParser`, which
     converts the R2-hosted document into a markdown file and uploads it back
     to R2 with an additional `.md` extension.
2. **Embed** — `generate_embeddings()`
   - Generates a short-lived presigned GET URL for the markdown object
     (the original key for text files, `<s3_key>.md` for converted files).
   - Delegates to `src/generate_embeddings.py` to download the markdown,
     chunk it, generate OpenAI embeddings, and persist chunks to the database.
3. **Persist status** — `mark_job_and_document_as_processed()`
   - Marks the document as `PROCESSED` and the processing job as `COMPLETED`.

On any failure, `_fail_job()` marks the document as `ERROR` and the job as
`FAILED`, and the exception is re-raised for Celery's retry/error reporting.

### Deploying the Modal parser

`parse_document.py` is a Modal app. After making changes, deploy it with:

```bash
uv run python3 -m modal deploy src/parse_document.py
```

To see logs:

```bash
uv run python3 -m modal app logs s3-docling-ocr-pipeline
```

Note — `s3-docling-ocr-pipeline` is the app name as defined in
`parse_document.py`.

## Testing

```bash
uv run pytest
```
