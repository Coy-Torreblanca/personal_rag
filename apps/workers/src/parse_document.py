"""
Parse Document - Modal-hosted document parsing service.

This module defines a Modal app that runs a Docling-based document parser.
Documents are downloaded from a presigned S3 URL, converted to markdown
using Docling, and the resulting markdown is uploaded back to S3.

The app is deployed separately via `modal deploy` and provides a remote
class (`DoclingParser`) that is called from the Celery workers in main.py.

Images that surface as ``<!-- image -->`` placeholders (photos, logos,
charts, scanned / image-only pages) are sent to an OpenAI vision model
(``gpt-4o-mini`` by default); the returned summary + verbatim text
transcription is spliced back into the markdown in place of the
placeholder.  The API key comes from the ``OPENAI_API_KEY`` environment
variable, exposed in the Modal container via the ``openai-api-key``
secret attached to the app.
"""

import os
from typing import TYPE_CHECKING

from logutil import get_logger

import modal

if TYPE_CHECKING:
    # Imported lazily at runtime (inside ``DoclingParser.load_modals``) to
    # keep container startup fast and to let the test-suite mock ``docling``
    # entirely; these imports exist only so type checkers can resolve the
    # annotations below.  All annotations are plain strings, so nothing is
    # ever evaluated (or imported) at runtime.
    from docling.document_converter import DocumentConverter
    from docling_core.types.doc import DocItem, DoclingDocument
    from openai import OpenAI
    from PIL import Image

logger = get_logger(__name__)

APP_NAME = "s3-docling-ocr-pipeline"
CACHE_DIR = "/root/.cache/docling"
docling_volume = modal.Volume.from_name(
    f"{APP_NAME}_docling_cache_volume", create_if_missing=True
)

# Environment variable naming the OpenAI vision model used to describe /
# transcribe images that docling could not turn into text (see
# ``DoclingParser._enrich_images_with_vlm``).  Read per document, so it can
# be changed without redeploying the Modal image.
VLM_MODEL_ENV = "OPENAI_VLM_MODEL"
VLM_MODEL_DEFAULT = "gpt-4o-mini"

# Placeholder docling's markdown serializer emits for every PictureItem
# (``image_mode=ImageRefMode.PLACEHOLDER`` is the default).  Each occurrence
# is replaced in place with the VLM description so the result keeps its
# position / context in the document.
IMAGE_PLACEHOLDER = "<!-- image -->"

image = (
    modal.Image.debian_slim(python_version="3.11")
    .apt_install("libgomp1", "ffmpeg", "libgl1")
    .pip_install(
        # Pinned: ``load_modals`` targets docling 2.x's ``format_options`` /
        # ``PdfFormatOption`` / ``ImageFormatOption`` API.  A floating ``>=``
        # range would let the next docling release silently change that API.
        "docling==2.118.0",
        "torch",
        "torchvision",
        "httpx",
        "openai-whisper",
        # Vision-model client for the image-summary step in
        # ``process_document``; pinned to match the workers pyproject.
        "openai>=2.48.0",
        "docling_core",
        extra_options="--extra-index-url www.download.pytorch.org/whl/cpu",
    )
    # Note: OCR is intentionally NOT enabled — ``load_modals`` explicitly
    # sets ``do_ocr=False`` because docling 2.118 defaults it to True (and
    # bundles rapidocr via ``docling-slim[standard]``, so an engine would
    # silently run).  Image content is handled by the VLM enrichment step
    # in ``process_document`` instead.
    .env({"HF_HOME": CACHE_DIR})
    .add_local_python_source("logutil")
)

app = modal.App(
    APP_NAME,
    image=image,
    # Exposes OPENAI_API_KEY to the container for the VLM image-description
    # step (see ``process_document``).  Create it once with:
    #   modal secret create openai-api-key OPENAI_API_KEY=<key>
    # If the secret is missing the pipeline still runs; images are simply
    # left as ``<!-- image -->`` placeholders and a warning is logged.
    secrets=[modal.Secret.from_name("openai-api-key")],
)


@app.cls(
    gpu=None, cpu=2.0, memory=4096, volumes={CACHE_DIR: docling_volume}, timeout=600
)
class DoclingParser:
    """
    Modal class for parsing documents using Docling.

    Downloads a document from a presigned S3 URL, converts it to markdown
    using the Docling library, and uploads the result back to S3.

    OCR is NOT enabled (it is expensive and rarely useful for the content
    this pipeline ingests).  Instead, images that surface as bare
    ``<!-- image -->`` placeholders in the exported markdown (photos, logos,
    charts, scanned / image-only pages) are sent to an OpenAI vision model;
    the returned summary + verbatim transcription is spliced back into the
    markdown in place of the placeholder (see ``process_document``).

    Attributes:
        converter: The DocumentConverter instance (initialized on container start).
    """

    # Set in ``load_modals`` (runs once per container, before any method
    # call).  Declared here so type checkers know the attribute exists when
    # ``process_document`` touches it.  ``DocumentConverter`` is imported
    # lazily inside ``load_modals`` — keeping container startup fast and
    # letting the test-suite mock ``docling`` entirely — hence the string
    # forward reference (never evaluated at runtime).
    converter: "DocumentConverter"

    @modal.enter()
    def load_modals(self):
        """
        Initialize the Docling DocumentConverter on container startup.

        This runs once when the Modal container starts, loading the
        converter into memory for reuse across method calls.

        The converter is configured for the VLM enrichment flow:

        * ``generate_picture_images=True`` — every picture must be
          rasterized so ``PictureItem.get_image()`` can hand the image to
          the OpenAI vision model later (without this, ``get_image``
          returns None and the placeholder stays).
        * OCR is deliberately disabled (``pipeline_options.do_ocr = False`` —
          docling 2.118 defaults it to True, which would OCR handwriting and
          emit garbled text items); image content is handled by the VLM step
          in ``process_document`` instead.
        * Both the PDF and the IMAGE pipelines share one
          ``pipeline_options`` instance: the parse stage routes standalone
          images (e.g. scanned JPG/PNG uploads) here as well as PDFs, and
          both formats must expose the same picture behaviour.
        """
        from docling.datamodel.base_models import InputFormat
        from docling.datamodel.pipeline_options import PdfPipelineOptions
        from docling.document_converter import (
            DocumentConverter,
            PdfFormatOption,
            ImageFormatOption,
        )

        logger.info("Initializing docling document converter.")

        pipeline_options = PdfPipelineOptions()
        pipeline_options.generate_picture_images = True
        # Docling 2.118 defaults ``do_ocr`` to True (and bundles rapidocr via
        # ``docling-slim[standard]``), so leaving it unset would OCR every
        # page — handwriting included — emitting garbled text items like
        # "dord heavenly Father" that pollute the markdown alongside the
        # VLM's clean transcription.  OCR must therefore be turned off
        # EXPLICITLY; the VLM enrichment step is the only image-content path.
        pipeline_options.do_ocr = False

        # docling 2.x wires per-format options through ``format_options``.
        self.converter = DocumentConverter(
            format_options={
                InputFormat.PDF: PdfFormatOption(pipeline_options=pipeline_options),
                InputFormat.IMAGE: ImageFormatOption(pipeline_options=pipeline_options),
            }
        )

        logger.info("Converter successfully initialized (ocr=off, picture_images=on)")

    @staticmethod
    def _encode_image_to_data_url(image: "Image.Image") -> str:
        """
        Encode a PIL image as a base64 JPEG data URL for the OpenAI API.

        JPEG keeps the payload small (cheaper / faster than PNG for photos
        and scans); RGB conversion drops any alpha channel, which the vision
        API does not accept.
        """
        import base64
        import io

        buffer = io.BytesIO()
        image.convert("RGB").save(buffer, format="JPEG", quality=85)
        return "data:image/jpeg;base64," + base64.b64encode(buffer.getvalue()).decode(
            "ascii"
        )

    @staticmethod
    def _page_no_of(item: "DocItem") -> int | None:
        """1-based page number of an item's first provenance, if any."""
        prov = getattr(item, "prov", None)
        if prov:
            return prov[0].page_no
        return None

    def _vlm_describe_image(
        self, client: "OpenAI", image: "Image.Image", page_no: int | None
    ) -> str | None:
        """
        Ask the OpenAI vision model to summarize an image and transcribe
        any text it contains.

        Args:
            client: An ``openai.OpenAI`` client (passed in so it is created
                once per document, not once per image).
            image: The PIL image extracted from the document.
            page_no: 1-based page number, used for logging context only.

        Returns:
            The model's response text (stripped), or None if the call fails
            or returns empty content.  Failures are logged, never raised, so
            one bad image cannot sink the whole document.
        """
        # Single unified prompt: the model ALWAYS provides a summary AND a
        # verbatim transcription of any visible text (there is no separate
        # describe vs. transcribe mode anymore).
        prompt = (
            "Summarize this image, which was extracted from a document, "
            "in detail. Transcribe any visible text verbatim, preserving "
            "spelling and line breaks. For charts, diagrams, or tables, "
            "explain what they show."
        )

        model = os.environ.get(VLM_MODEL_ENV, VLM_MODEL_DEFAULT)
        context = f" (page {page_no})" if page_no is not None else ""
        # Debug-level: one line per image so it is easy to see which model
        # served which page when investigating enrichment quality/costs.
        logger.debug("Calling OpenAI VLM model=%s%s", model, context)
        try:
            response = client.chat.completions.create(
                model=model,
                messages=[
                    {
                        "role": "system",
                        "content": (
                            "You are a document-parsing assistant. Your "
                            "response is inserted into the parsed markdown, "
                            "so answer with plain text only."
                        ),
                    },
                    {
                        "role": "user",
                        "content": [
                            {"type": "text", "text": prompt},
                            {
                                "type": "image_url",
                                "image_url": {
                                    "url": self._encode_image_to_data_url(image)
                                },
                            },
                        ],
                    },
                ],
                max_tokens=1024,
                timeout=60.0,
            )
            content = response.choices[0].message.content
        except Exception:
            logger.exception("OpenAI VLM call failed%s", context)
            return None
        if not content:
            logger.warning("OpenAI VLM returned empty content%s", context)
            return None
        return content.strip()

    def _enrich_images_with_vlm(
        self, doc: "DoclingDocument", markdown: str, client: "OpenAI"
    ) -> str:
        """
        Replace every ``<!-- image -->`` placeholder in ``markdown`` with an
        OpenAI VLM summary + verbatim transcription of the picture.

        The markdown serializer and this method traverse the document tree in
        the same depth-first order (``with_groups=True``,
        ``traverse_pictures=True``, body content layer), so a cursor into the
        markdown is enough to map each ``PictureItem`` to its
        ``<!-- image -->`` placeholder.  Results therefore land back in their
        original position, keeping their surrounding context.

        Only ``PictureItem`` placeholders are touched.  ``HANDWRITTEN_TEXT``
        items are intentionally left as-is (whatever text docling extracted,
        if any) — the VLM path is placeholder-only by design.

        Items that fail (no extractable image, VLM error, placeholder not
        found) are left untouched and logged; the document still parses.
        """
        from docling_core.types.doc import (
            ContentLayer,
            DocItem,
            DocItemLabel,
        )

        enriched = markdown
        # Cursor into ``enriched``; always sits at or before the current
        # item's emitted markdown, so ``find`` from it cannot jump ahead to
        # a later item's placeholder.
        search_pos = 0
        images_described = 0

        for item, _ in doc.iterate_items(
            with_groups=True,
            traverse_pictures=True,
            included_content_layers={ContentLayer.BODY},
        ):
            if not isinstance(item, DocItem):
                continue

            if item.label == DocItemLabel.PICTURE:
                # Locate this picture's placeholder.  The cursor is advanced
                # past it unconditionally — even when the image cannot be
                # extracted or the VLM call fails — so the next picture is
                # matched to the next placeholder.
                placeholder_idx = enriched.find(IMAGE_PLACEHOLDER, search_pos)
                if placeholder_idx == -1:
                    logger.warning(
                        "PictureItem %s has no %r in markdown; skipping",
                        item.self_ref,
                        IMAGE_PLACEHOLDER,
                    )
                    continue
                search_pos = placeholder_idx + len(IMAGE_PLACEHOLDER)

                image = item.get_image(doc)
                if image is None:
                    logger.debug(
                        "No extractable image for PictureItem %s; leaving placeholder",
                        item.self_ref,
                    )
                    continue

                description = self._vlm_describe_image(
                    client,
                    image,
                    page_no=self._page_no_of(item),
                )
                if not description:
                    continue
                replacement = f"**Image description:** {description}"
                enriched = (
                    enriched[:placeholder_idx]
                    + replacement
                    + enriched[placeholder_idx + len(IMAGE_PLACEHOLDER) :]
                )
                search_pos = placeholder_idx + len(replacement)
                images_described += 1

        if images_described:
            logger.info("Described %d image(s) with the OpenAI VLM", images_described)
        return enriched

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

        Notes:
            The markdown export always passes ``traverse_pictures=True`` so
            that picture items nested under groups are visited; this matters
            because every ``PictureItem`` surfaces as a ``<!-- image -->``
            placeholder in the markdown and must be found for replacement.

            After conversion, every ``<!-- image -->`` placeholder is sent to
            an OpenAI vision model (``OPENAI_VLM_MODEL``, default
            ``gpt-4o-mini``); the returned summary + verbatim transcription
            replaces the placeholder in place, preserving its position in
            the document.  This requires the ``OPENAI_API_KEY`` env var
            (provided by the app's ``openai-api-key`` secret).  If it is
            missing, enrichment is skipped and the placeholders remain.
        """
        import httpx
        from openai import OpenAI

        logger.info("Processing with Docling pipeline.")

        try:
            result = self.converter.convert(download_url)
            # ``traverse_pictures=True``: the markdown serializer skips
            # picture children by default, but every ``PictureItem`` must
            # surface as a ``<!-- image -->`` placeholder so the VLM
            # enrichment step below can find and replace it in place.
            markdown_content = result.document.export_to_markdown(
                traverse_pictures=True
            ).replace("\x00", "")
        except Exception as e:
            logger.exception("Docling conversion failed for %s", download_url)
            return {
                "status": "error",
                "message": f"Docling conversion failed: {str(e)}",
            }

        # VLM enrichment: every ``<!-- image -->`` placeholder is summarized
        # + transcribed by an OpenAI vision model and spliced back into the
        # markdown in place.  Requires OPENAI_API_KEY (provided by the app's
        # ``openai-api-key`` secret); without it the placeholders are left
        # as-is and a warning is logged.
        api_key = os.environ.get("OPENAI_API_KEY")
        if not api_key:
            logger.warning(
                "OPENAI_API_KEY is not set; skipping VLM image enrichment "
                + "(image placeholders will remain in the markdown)"
            )
        else:
            try:
                markdown_content = self._enrich_images_with_vlm(
                    doc=result.document,
                    markdown=markdown_content,
                    client=OpenAI(api_key=api_key),
                )
            except Exception:
                # Never fail the document because enrichment broke; upload
                # the markdown with the placeholders instead.
                logger.exception(
                    "VLM image enrichment failed; uploading un-enriched markdown"
                )

        # Observability: surface any picture that is still a bare
        # ``<!-- image -->`` placeholder after the enrichment phase.  A
        # non-zero count here means the API key was missing, a VLM call
        # failed, or a picture had no extractable image — all cases where
        # the document still parses but the image content is lost.
        remaining_placeholders = markdown_content.count(IMAGE_PLACEHOLDER)
        if remaining_placeholders:
            logger.warning(
                "%d image placeholder(s) remain in the markdown "
                + "(VLM enrichment incomplete or skipped)",
                remaining_placeholders,
            )

        # Log the output size up front: a suspiciously tiny markdown payload
        # (e.g. only ``<!-- image -->`` placeholders) is the first symptom of
        # a traversal / VLM regression, so it should be visible in logs even
        # before the upload succeeds.
        page_count = (
            len(result.document.pages) if hasattr(result.document, "pages") else 1
        )
        logger.debug(
            "Docling conversion produced markdown_len=%d, pages=%d",
            len(markdown_content),
            page_count,
        )
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
            "pages": page_count,
        }
