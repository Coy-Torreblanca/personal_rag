"""
Parse Document - Modal-hosted document parsing service.

This module defines a Modal app that runs a Docling-based document parser.
Documents are downloaded from a presigned S3 URL, converted to markdown
using Docling, and the resulting markdown is uploaded back to S3.

The app is deployed separately via `modal deploy` and provides a remote
class (`DoclingParser`) that is called from the Celery workers in main.py.
"""

from logutil import get_logger

import modal

logger = get_logger(__name__)

APP_NAME = "s3-docling-ocr-pipeline"
CACHE_DIR = "/root/.cache/docling"
docling_volume = modal.Volume.from_name(
    f"{APP_NAME}_docling_cache_volume", create_if_missing=True
)

image = (
    modal.Image.debian_slim(python_version="3.11")
    .apt_install("libgomp1", "ffmpeg", "libgl1")
    .pip_install(
        "docling>=2.0.0",
        "torch",
        "torchvision",
        "httpx",
        "easyocr",
        "openai-whisper",
        extra_options="--extra-index-url www.download.pytorch.org/whl/cpu",
    )
    .env({"HF_HOME": CACHE_DIR})
)

app = modal.App(APP_NAME, image=image)


@app.cls(
    gpu=None, cpu=2.0, memory=4096, volumes={CACHE_DIR: docling_volume}, timeout=600
)
class DoclingParser:
    """
    Modal class for parsing documents using Docling.

    Downloads a document from a presigned S3 URL, converts it to markdown
    using the Docling library, and uploads the result back to S3.

    Attributes:
        converter: The DocumentConverter instance (initialized on container start).
    """

    @modal.enter()
    def load_modals(self):
        """
        Initialize the Docling DocumentConverter on container startup.

        This runs once when the Modal container starts, loading the
        converter into memory for reuse across method calls.
        """
        from docling.document_converter import DocumentConverter

        logger.info("Initializing docling document converter.")

        self.converter = DocumentConverter()

        logger.info("Converter successfully initialized")

    @modal.method()
    def process_document(self, download_url: str, upload_url: str):
        """
        Download, parse, and upload a document as markdown.

        Fetches the document from `download_url`, converts it to markdown
        via Docling, and uploads the markdown content to `upload_url`.

        Args:
            download_url: Presigned S3 URL for downloading the source document.
            upload_url: Presigned S3 URL for uploading the parsed markdown.

        Returns:
            A dict with:
                - status: "success" or "error"
                - message: Error description (if status is "error")
                - pages: Number of pages in the processed document (if success).
        """
        import httpx

        logger.info("Processing with Docling pipeline.")

        try:
            result = self.converter.convert(download_url)
            markdown_content = result.document.export_to_markdown().raw_text.replace(
                "\x00", ""
            )
        except Exception as e:
            logger.exception("Docling conversion failed for %s", download_url)
            return {
                "status": "error",
                "message": f"Docling conversion failed: {str(e)}",
            }

        logger.info("Document has been processed.")

        # 2. Upload the Markdown string to the presigned S3 upload URL via PUT
        try:
            # S3 presigned URLs require the payload as raw bytes or file-like objects
            upload_response = httpx.put(
                upload_url,
                content=markdown_content.encode("utf-8"),
                headers={"Content-Type": "text/markdown"},
                timeout=60.0,
            )
            upload_response.raise_for_status()
        except Exception as e:
            logger.exception("Failed to upload to S3")
            return {"status": "error", "message": f"failed to upload to S3: {str(e)}"}

        logger.info("Upload complete!")
        return {
            "status": "success",
            "pages": len(result.document.pages)
            if hasattr(result.document, "pages")
            else 1,
        }
