# Workers

Workers is an app which deploys jobs after recieving a singal from Celery.

# Process Document

Process document runs in a Modal container and it uses Docling to make a R2 hosted document into a markdown file then uploads the document back to R2 with an addtional extension - `.md`.

process_document.py is a modal app. After making changes, you must deploy it with the following:

```bash
uv run python3 -m modal deploy src/parse_document.py
```

To see logs, you can run:

Note - s3-docling-ocr-pipeline is the app name as defined in process_document.
```bash
uv run python3 -m modal app logs s3-docling-ocr-pipeline
```


