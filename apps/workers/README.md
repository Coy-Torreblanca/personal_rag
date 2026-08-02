# Workers

Workers is an app which deploys background jobs after receiving a signal from
Celery. It handles document ingestion for the 30ai platform: parse uploaded
documents into markdown, generate embeddings, and persist the results.

## Architecture

```
src/
  main.py                    — Celery app & task definitions (process_document)
  generate_embeddings.py     — Text chunking + OpenAI embedding pipeline
  generate_llm_summary.py    — Dense LLM summary generation via DeepSeek
  parse_document.py          — Modal-hosted Docling parser (deployed separately)
```

## Process Document

`process_document` (defined in `src/main.py`) is the Celery task that runs the
full document-processing pipeline. It runs in four stages:

1. **Parse** — `parse_document()`
   - Plain-text files (`.txt`, `.md`, `.html`, `.yaml`, ...) are already
     markdown-compatible and skip the Modal/Docling parser entirely.
   - All other file types are sent to the Modal-hosted `DoclingParser`, which
     converts the R2-hosted document into a markdown file and uploads it back
     to R2 with an additional `.md` extension.
2. **Download** — `download_file_text()`
   - Generates a short-lived presigned GET URL for the markdown object
     (the original key for text files, `<s3_key>.md` for converted files)
     and downloads it once. The downloaded text feeds both the summary and
     embedding stages, so the content is never fetched twice.
3. **Summarize & Embed** — `generate_llm_summary()` + `generate_embeddings()`
   - `generate_llm_summary()` sends the markdown to DeepSeek
     (`DEEPSEEK_API_KEY`, `deepseek-v4-flash`) and returns a dense
     150–250 word summary.
   - `generate_embeddings()` chunks the markdown together with the LLM
     summary (joined on its own line, so the summary stays inside the same
     context windows as the content it describes), generates OpenAI
     embeddings for every chunk, and persists the chunks to the database.
4. **Persist status** — `mark_job_and_document_as_processed()`
   - Stores the LLM summary on the document row (`documents.summary`), marks
     the document as `PROCESSED` and the processing job as `COMPLETED`.

On any failure, `_fail_job()` marks the document as `ERROR` and the job as
`FAILED`, and the exception is re-raised for Celery's retry/error reporting.

### Configuration

| Variable | Used by | Purpose |
| --- | --- | --- |
| `DEEPSEEK_API_KEY` | `generate_llm_summary.py` | DeepSeek chat-completions auth (read lazily, at call time) |
| `BUCKET_NAME` | `main.py` | R2 bucket holding documents and converted markdown |

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
