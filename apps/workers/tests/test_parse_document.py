"""Tests for the parse_document module (DoclingParser).

``DoclingParser`` is wrapped by Modal's ``@app.cls()`` decorator,
which transforms it into a ``modal.cls.Cls`` instance at runtime.
To test the underlying logic without a Modal runtime, we:
1. Retrieve the original Python class via ``Cls._get_user_cls()``.
2. Retrieve the raw method functions via ``PartialFunction._get_raw_f()``.
3. Manually instantiate the user class and call the raw methods.

``docling`` pulls in a heavy ML stack (torch, transformers, ...), so we
inject mock modules into ``sys.modules`` for the modules ``load_modals``
imports, keeping the suite fast and offline.  Note that ``docling_core``
is NOT mocked: the VLM-enrichment tests build real documents with it.
"""

import sys
from types import SimpleNamespace
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from src.parse_document import (
    APP_NAME,
    IMAGE_PLACEHOLDER,
    VLM_MODEL_DEFAULT,
    VLM_MODEL_ENV,
    DoclingParser,
)


# ── Patch httpx via sys.modules ──────────────────────────────────
# ``httpx`` is imported *inside* ``process_document`` (``import httpx``).
# ``unittest.mock.patch`` requires a dotted ``module.attribute`` path,
# so we pre-populate ``sys.modules["httpx"]`` with a mock instead.


@pytest.fixture(autouse=True)
def _patch_httpx() -> MagicMock:
    """Pre-populate ``sys.modules["httpx"]`` with a mock so that local
    imports inside ``process_document`` resolve to our controlled mock.

    IMPORTANT: this must only ever add/remove the ``httpx`` key itself.
    ``patch.dict("sys.modules", ...)`` is NOT safe here: its teardown
    clears the *entire* module registry and restores a snapshot taken at
    fixture setup, silently dropping every module imported during the
    test body.  The VLM tests import ``docling_core`` (and with it
    ``numpy``) inside test bodies; once numpy is dropped from
    ``sys.modules`` the next re-import fails hard with
    ``ImportError: cannot load module more than once per process``.
    """
    mock_httpx = MagicMock()
    original_httpx = sys.modules.get("httpx")
    sys.modules["httpx"] = mock_httpx
    try:
        yield mock_httpx
    finally:
        # Restore only the ``httpx`` entry; leave everything else alone.
        if original_httpx is None:
            sys.modules.pop("httpx", None)
        else:
            sys.modules["httpx"] = original_httpx


# ── Inject mock docling module ───────────────────────────────────
# ``DocumentConverter`` is imported inside ``DoclingParser.load_modals``.
# Rather than requiring the real (heavy) ``docling`` package, we
# pre-populate ``sys.modules`` with mock modules so that the import
# inside ``load_modals`` resolves to our mock.


@pytest.fixture(scope="session", autouse=True)
def _mock_docling_module() -> None:
    """Inject a mock ``docling`` module tree once per session.

    ``load_modals`` imports from three submodules
    (``docling.document_converter``, ``docling.datamodel.base_models``,
    ``docling.datamodel.pipeline_options``).  Since the parent ``docling``
    mock has no ``__path__``, every dotted path must be pre-registered in
    ``sys.modules`` for the imports to resolve.
    """
    if "docling" not in sys.modules:
        mock_docling = MagicMock()
        mock_docling.document_converter = MagicMock()
        mock_docling.document_converter.DocumentConverter = MagicMock()

        mock_datamodel = MagicMock()
        mock_base_models = MagicMock()
        mock_pipeline_options = MagicMock()

        sys.modules["docling"] = mock_docling
        sys.modules["docling.document_converter"] = mock_docling.document_converter
        sys.modules["docling.datamodel"] = mock_datamodel
        sys.modules["docling.datamodel.base_models"] = mock_base_models
        sys.modules["docling.datamodel.pipeline_options"] = mock_pipeline_options


@pytest.fixture(autouse=True)
def _setup_converter_mock() -> None:
    """Patch ``DocumentConverter`` before each test and extract raw
    functions from Modal wrappers.

    Also patches ``PdfPipelineOptions`` / ``EasyOcrOptions`` so tests can
    assert the pipeline is configured WITHOUT OCR: picture images on,
    ``do_ocr`` / ``ocr_options`` untouched, and no EasyOCR engine built.
    """
    with (
        patch("docling.document_converter.DocumentConverter") as mock_cls,
        patch("docling.document_converter.PdfFormatOption") as mock_pdf_format_option,
        patch(
            "docling.document_converter.ImageFormatOption"
        ) as mock_image_format_option,
        patch("docling.datamodel.pipeline_options.PdfPipelineOptions") as mock_pdf_opts,
        patch("docling.datamodel.pipeline_options.EasyOcrOptions") as mock_easy_opts,
    ):
        # Get the original Python class (before Modal decoration)
        user_cls = DoclingParser._get_user_cls()

        # Get the raw function objects from Modal's PartialFunction wrappers
        partial_fns = DoclingParser._get_partial_functions()
        raw_load = partial_fns["load_modals"]._get_raw_f()
        raw_process = partial_fns["process_document"]._get_raw_f()

        yield {
            "user_cls": user_cls,
            "raw_load": raw_load,
            "raw_process": raw_process,
            "mock_converter_cls": mock_cls,
            "mock_converter": mock_cls.return_value,
            "mock_pdf_format_option": mock_pdf_format_option,
            "mock_image_format_option": mock_image_format_option,
            "mock_pdf_opts": mock_pdf_opts,
            "mock_easy_opts": mock_easy_opts,
        }


class _FakeVLMCompletions:
    """Canned ``chat.completions.create`` responses; records call kwargs."""

    def __init__(self, responses: list[str]) -> None:
        self.responses = list(responses)
        self.calls: list[dict[str, Any]] = []

    def create(self, **kwargs):
        self.calls.append(kwargs)
        content = self.responses.pop(0)
        return SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(content=content))]
        )


class _FakeVLMClient:
    """Minimal stand-in for ``openai.OpenAI``."""

    def __init__(self, responses: list[str]) -> None:
        self.chat = SimpleNamespace(completions=_FakeVLMCompletions(responses))


class _BoomVLMClient:
    """VLM client whose every ``chat.completions.create`` call raises."""

    class _BoomCompletions:
        def create(self, **kwargs):
            raise RuntimeError("api down")

    chat = SimpleNamespace(completions=_BoomCompletions())


def _build_vlm_doc():
    """Build a small real docling document with two pictures and a
    handwritten-text item (requires ``docling_core``).

    Layout (order matters for placeholder mapping):
        paragraph -> paragraph (duplicate text) -> picture -> handwritten
        text (same text as the paragraph, on purpose) -> paragraph -> picture
        -> paragraph

    The handwritten item is kept on purpose: the enrichment step is
    placeholder-only, so its text must be left untouched by the VLM pass.
    """
    from docling_core.types.doc import DocItemLabel, DoclingDocument
    from docling_core.types.doc.base import BoundingBox, Size
    from docling_core.types.doc.common.reference import ImageRef, ProvenanceItem
    from PIL import Image as PILImage

    img_ref = ImageRef.from_pil(PILImage.new("RGB", (50, 50), "red"), dpi=72)
    doc = DoclingDocument(name="test")
    doc.add_page(page_no=1, size=Size(width=50, height=50), image=img_ref)
    prov = ProvenanceItem(
        page_no=1, bbox=BoundingBox(l=0, t=0, r=50, b=50), charspan=(0, 0)
    )

    doc.add_text(label=DocItemLabel.PARAGRAPH, text="Intro paragraph.")
    doc.add_text(
        label=DocItemLabel.PARAGRAPH, text="handwritten note (plain para, must stay)"
    )
    doc.add_picture(image=img_ref, prov=prov)
    doc.add_text(label=DocItemLabel.HANDWRITTEN_TEXT, text="handwritten note", prov=prov)
    doc.add_text(label=DocItemLabel.PARAGRAPH, text="Middle text.")
    doc.add_picture(image=img_ref, prov=prov)
    doc.add_text(label=DocItemLabel.PARAGRAPH, text="Outro paragraph.")
    return doc


class TestDoclingParser:
    """Tests for :class:`DoclingParser` using raw (un-decorated) methods."""

    def _make_parser(self, ctx: dict) -> tuple:
        """Helper: instantiate the user class and initialise the converter."""
        user_cls = ctx["user_cls"]
        instance = user_cls()
        ctx["raw_load"](instance)
        return instance, ctx["raw_process"], ctx

    # ── load_modals ───────────────────────────────────────────────

    def test_load_modals_initializes_converter(self, _setup_converter_mock) -> None:
        """``load_modals`` creates a DocumentConverter."""
        ctx = _setup_converter_mock
        user_cls = ctx["user_cls"]
        instance = user_cls()
        ctx["raw_load"](instance)
        assert instance.converter is ctx["mock_converter"]

    # ── Pipeline configuration (VLM-only, no OCR) ───────────────────

    def test_load_modals_picture_images_without_ocr(
        self, _setup_converter_mock
    ) -> None:
        """OCR is explicitly disabled (``do_ocr=False`` — docling 2.118
        defaults it to True, so it must be set) while picture images stay
        enabled, so the VLM enrichment step can extract every picture via
        ``PictureItem.get_image``."""
        ctx = _setup_converter_mock
        instance = ctx["user_cls"]()
        ctx["raw_load"](instance)

        # Picture rasterization must remain on for the VLM step.
        assert ctx["mock_pdf_opts"].return_value.generate_picture_images is True
        # OCR is turned OFF explicitly: docling 2.118 defaults ``do_ocr`` to
        # True (bundling rapidocr), which would OCR handwriting and emit
        # garbled text items next to the VLM's clean transcription.
        assert ctx["mock_pdf_opts"].return_value.do_ocr is False
        # Nothing else was assigned on the pipeline options.
        assert not any(
            call[0].startswith("ocr_options")
            for call in ctx["mock_pdf_opts"].return_value.mock_calls
        )
        # No OCR engine was constructed at all.
        ctx["mock_easy_opts"].assert_not_called()

        # Both formats are wired through docling 2.x ``format_options`` and
        # share one pipeline-options instance (the parse stage routes
        # standalone image uploads here as well as PDFs).
        format_options = ctx["mock_converter_cls"].call_args.kwargs["format_options"]
        assert len(format_options) == 2
        assert ctx["mock_pdf_format_option"].return_value in format_options.values()
        assert ctx["mock_image_format_option"].return_value in format_options.values()
        assert ctx["mock_pdf_format_option"].call_args.kwargs == {
            "pipeline_options": ctx["mock_pdf_opts"].return_value
        }
        assert ctx["mock_image_format_option"].call_args.kwargs == {
            "pipeline_options": ctx["mock_pdf_opts"].return_value
        }

    # ── process_document ──────────────────────────────────────────

    def test_process_document_success(
        self, _setup_converter_mock, _patch_httpx
    ) -> None:
        """A successful conversion returns a success dict with pages."""
        ctx = _setup_converter_mock
        mock_converter = ctx["mock_converter"]
        mock_result = MagicMock()
        mock_result.document.export_to_markdown.return_value = "# Hello\n\nWorld."
        mock_result.document.pages = [1, 2, 3]
        mock_converter.convert.return_value = mock_result

        instance, raw_process, _ = self._make_parser(ctx)

        _patch_httpx.put.return_value = MagicMock()

        result = raw_process(
            instance, "https://example.com/doc.pdf", "https://example.com/upload"
        )

        assert result["status"] == "success"
        assert result["pages"] == 3
        mock_converter.convert.assert_called_once_with("https://example.com/doc.pdf")

    def test_process_document_exports_markdown_traversing_pictures(
        self, _setup_converter_mock, _patch_httpx
    ) -> None:
        """The markdown export traverses picture items so every picture
        surfaces as a ``<!-- image -->`` placeholder for the VLM pass."""
        ctx = _setup_converter_mock
        mock_converter = ctx["mock_converter"]
        mock_result = MagicMock()
        mock_result.document.export_to_markdown.return_value = "# OCR'd text"
        mock_result.document.pages = [1]
        mock_converter.convert.return_value = mock_result

        instance, raw_process, _ = self._make_parser(ctx)
        _patch_httpx.put.return_value = MagicMock()

        result = raw_process(
            instance, "https://example.com/scan.pdf", "https://example.com/upload"
        )

        assert result["status"] == "success"
        mock_result.document.export_to_markdown.assert_called_once_with(
            traverse_pictures=True
        )

    def test_process_document_no_pages_attribute(
        self, _setup_converter_mock, _patch_httpx
    ) -> None:
        """If the document has no ``pages`` attribute, fall back to 1."""
        ctx = _setup_converter_mock
        mock_converter = ctx["mock_converter"]
        mock_result = MagicMock()
        mock_result.document.export_to_markdown.return_value = "# Hi"
        del mock_result.document.pages
        mock_converter.convert.return_value = mock_result

        instance, raw_process, _ = self._make_parser(ctx)

        _patch_httpx.put.return_value = MagicMock()

        result = raw_process(
            instance, "https://example.com/doc.pdf", "https://example.com/upload"
        )

        assert result["status"] == "success"
        assert result["pages"] == 1

    def test_process_document_conversion_failure(
        self, _setup_converter_mock, _patch_httpx
    ) -> None:
        """When conversion fails, the method returns an error dict."""
        ctx = _setup_converter_mock
        mock_converter = ctx["mock_converter"]
        mock_converter.convert.side_effect = Exception("Conversion error")

        instance, raw_process, _ = self._make_parser(ctx)

        result = raw_process(
            instance, "https://example.com/bad.pdf", "https://example.com/upload"
        )

        assert result["status"] == "error"
        assert "Docling conversion failed: Conversion error" in result["message"]

    def test_process_document_upload_failure(
        self, _setup_converter_mock, _patch_httpx
    ) -> None:
        """When the upload to S3 fails, the method returns an error dict."""
        ctx = _setup_converter_mock
        mock_converter = ctx["mock_converter"]
        mock_result = MagicMock()
        mock_result.document.export_to_markdown.return_value = "# Hello"
        mock_result.document.pages = [1]
        mock_converter.convert.return_value = mock_result

        instance, raw_process, _ = self._make_parser(ctx)

        mock_response = MagicMock()
        mock_response.raise_for_status.side_effect = Exception("Upload rejected")
        _patch_httpx.put.return_value = mock_response

        result = raw_process(
            instance, "https://example.com/doc.pdf", "https://example.com/upload"
        )

        assert result["status"] == "error"
        assert "failed to upload to S3" in result["message"]

    def test_process_document_upload_content_type(
        self, _setup_converter_mock, _patch_httpx
    ) -> None:
        """The markdown is uploaded with the correct content type and encoding."""
        ctx = _setup_converter_mock
        mock_converter = ctx["mock_converter"]
        mock_result = MagicMock()
        mock_result.document.export_to_markdown.return_value = "# Test"
        mock_result.document.pages = [1]
        mock_converter.convert.return_value = mock_result

        instance, raw_process, _ = self._make_parser(ctx)

        _patch_httpx.put.return_value = MagicMock()

        raw_process(
            instance, "https://example.com/doc.pdf", "https://example.com/upload"
        )

        _patch_httpx.put.assert_called_once_with(
            "https://example.com/upload",
            content=b"# Test",
            headers={"Content-Type": "text/markdown"},
            timeout=60.0,
        )

    def test_process_document_vlm_failure_still_uploads_markdown(
        self, _setup_converter_mock, _patch_httpx, monkeypatch, caplog
    ) -> None:
        """A crash inside VLM enrichment must not fail the document: the
        un-enriched markdown (placeholders intact) is uploaded and the
        failure is logged, so one bad enrichment cannot lose the parse."""
        import logging

        ctx = _setup_converter_mock
        mock_converter = ctx["mock_converter"]
        mock_result = MagicMock()
        mock_result.document.export_to_markdown.return_value = "# Hello\n\n<!-- image -->"
        mock_result.document.pages = [1]
        # Make the enrichment phase blow up right after conversion.
        mock_result.document.iterate_items.side_effect = RuntimeError("enrichment boom")
        mock_converter.convert.return_value = mock_result

        monkeypatch.setenv("OPENAI_API_KEY", "test-key")
        instance, raw_process, _ = self._make_parser(ctx)
        _patch_httpx.put.return_value = MagicMock()

        with caplog.at_level(logging.ERROR):
            result = raw_process(
                instance, "https://example.com/doc.pdf", "https://example.com/upload"
            )

        assert result["status"] == "success"
        uploaded = _patch_httpx.put.call_args.kwargs["content"].decode("utf-8")
        assert "<!-- image -->" in uploaded
        assert any(
            "VLM image enrichment failed" in r.getMessage() for r in caplog.records
        )


class TestVlmEnrichment:
    """Tests for the OpenAI VLM image-description / transcription step.

    Uses a real ``docling_core`` document (skipped if the package is not
    installed) and canned VLM responses, so no network or API key is needed.
    """

    @staticmethod
    def _parser_and_doc():
        pytest.importorskip("docling_core")
        user_cls = DoclingParser._get_user_cls()
        instance = user_cls()
        doc = _build_vlm_doc()
        md = doc.export_to_markdown(traverse_pictures=True).replace("\x00", "")
        return user_cls, instance, doc, md

    def test_enrich_replaces_placeholders_in_order(self) -> None:
        """Each ``<!-- image -->`` placeholder is replaced in document order
        with the VLM summary + transcription; the surrounding content keeps
        its position, and non-picture items (including the handwritten
        item) are left untouched."""
        user_cls, instance, doc, md = self._parser_and_doc()
        assert md.count("<!-- image -->") == 2

        client = _FakeVLMClient(["FIRST PIC DESC", "SECOND PIC DESC"])
        out = user_cls._enrich_images_with_vlm(instance, doc, md, client)

        assert "<!-- image -->" not in out
        assert "**Image description:** FIRST PIC DESC" in out
        assert "**Image description:** SECOND PIC DESC" in out

        # Order preserved: intro -> desc1 -> middle -> desc2 -> outro.
        order = [
            out.index("Intro paragraph."),
            out.index("**Image description:** FIRST PIC DESC"),
            out.index("Middle text."),
            out.index("**Image description:** SECOND PIC DESC"),
            out.index("Outro paragraph."),
        ]
        assert order == sorted(order)

        # The handwritten item is placeholder-only by design: its text is
        # NOT replaced with a VLM transcription.
        assert "**Transcribed text:**" not in out
        assert "handwritten note" in out
        # The plain-paragraph duplicate of the handwritten text must survive.
        assert "handwritten note (plain para, must stay)" in out

        # Exactly 2 calls (pictures only), each with a base64 JPEG payload.
        calls = client.chat.completions.calls
        assert len(calls) == 2
        prompts = [c["messages"][1]["content"][0]["text"] for c in calls]
        # The unified prompt always asks for a summary AND a transcription.
        assert all("Summarize" in p and "Transcribe" in p for p in prompts)
        urls = [c["messages"][1]["content"][1]["image_url"]["url"] for c in calls]
        assert all(u.startswith("data:image/jpeg;base64,") for u in urls)

    def test_enrich_vlm_failure_keeps_markdown(self) -> None:
        """A failing VLM call must not sink the document: placeholders and
        OCR text are left untouched and the markdown is returned unchanged."""
        user_cls, instance, doc, md = self._parser_and_doc()

        out = user_cls._enrich_images_with_vlm(instance, doc, md, _BoomVLMClient())
        assert out == md
        assert out.count("<!-- image -->") == 2

    def test_enrich_partial_failure_keeps_remaining_placeholder(self) -> None:
        """A partial failure (first image described, second fails) keeps the
        failed picture's placeholder while the successful description is
        spliced in — and the cursor still maps subsequent pictures to the
        right placeholders."""
        user_cls, instance, doc, md = self._parser_and_doc()
        assert md.count("<!-- image -->") == 2

        # Second response is empty -> second picture keeps its placeholder.
        client = _FakeVLMClient(["FIRST PIC DESC", ""])
        out = user_cls._enrich_images_with_vlm(instance, doc, md, client)

        assert out.count("<!-- image -->") == 1
        assert "**Image description:** FIRST PIC DESC" in out
        # Order preserved: description still lands before the remaining
        # placeholder, which sits before the outro paragraph.
        assert out.index("**Image description:** FIRST PIC DESC") < out.index(
            "<!-- image -->"
        )
        assert out.index("<!-- image -->") < out.index("Outro paragraph.")
        assert len(client.chat.completions.calls) == 2

    def test_enrich_empty_vlm_response_keeps_placeholders(self) -> None:
        """Empty VLM responses leave every placeholder intact and return
        the markdown unchanged."""
        user_cls, instance, doc, md = self._parser_and_doc()

        out = user_cls._enrich_images_with_vlm(
            instance, doc, md, _FakeVLMClient(["", ""])
        )
        assert out == md
        assert out.count("<!-- image -->") == 2

    def test_enrich_ignores_handwritten_text_items(self) -> None:
        """HANDWRITTEN_TEXT items are intentionally not enriched: only
        ``<!-- image -->`` placeholders are replaced, so a document with
        handwriting but no pictures makes zero VLM calls."""
        pytest.importorskip("docling_core")
        from docling_core.types.doc import DocItemLabel, DoclingDocument
        from docling_core.types.doc.base import BoundingBox, Size
        from docling_core.types.doc.common.reference import ProvenanceItem

        doc = DoclingDocument(name="test")
        doc.add_page(page_no=1, size=Size(width=50, height=50))
        prov = ProvenanceItem(
            page_no=1, bbox=BoundingBox(l=0, t=0, r=50, b=50), charspan=(0, 0)
        )
        doc.add_text(
            label=DocItemLabel.HANDWRITTEN_TEXT, text="handwritten note", prov=prov
        )

        md = doc.export_to_markdown(traverse_pictures=True).replace("\x00", "")
        assert "<!-- image -->" not in md

        user_cls = DoclingParser._get_user_cls()
        client = _FakeVLMClient([])
        out = user_cls._enrich_images_with_vlm(user_cls(), doc, md, client)

        assert out == md
        assert "handwritten note" in out
        assert client.chat.completions.calls == []

    # ── _vlm_describe_image / helpers ──────────────────────────────

    def test_vlm_describe_image_uses_model_from_env(self, monkeypatch) -> None:
        """``OPENAI_VLM_MODEL`` overrides the default vision model, and the
        image is sent as a base64 JPEG data URL under the unified
        summarize + transcribe prompt."""
        from PIL import Image as PILImage

        user_cls = DoclingParser._get_user_cls()
        instance = user_cls()
        monkeypatch.setenv(VLM_MODEL_ENV, "gpt-4.1-mini")
        client = _FakeVLMClient(["a description"])

        out = user_cls._vlm_describe_image(
            instance,
            client,
            PILImage.new("RGB", (8, 8)),
            page_no=None,
        )

        assert out == "a description"
        call = client.chat.completions.calls[0]
        assert call["model"] == "gpt-4.1-mini"
        # System prompt asks for plain text; the user message carries the
        # prompt text plus the JPEG data URL.
        assert call["messages"][0]["role"] == "system"
        user_content = call["messages"][1]["content"]
        assert user_content[0]["type"] == "text"
        # The single prompt always asks for a summary AND a transcription.
        text_prompt = user_content[0]["text"]
        assert "Summarize" in text_prompt and "Transcribe" in text_prompt
        assert user_content[1]["image_url"]["url"].startswith(
            "data:image/jpeg;base64,"
        )

    def test_vlm_describe_image_empty_content_returns_none(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        """A model response with empty content yields None and a warning
        that includes the page number context."""
        import logging

        from PIL import Image as PILImage

        user_cls = DoclingParser._get_user_cls()
        instance = user_cls()
        client = _FakeVLMClient([""])

        with caplog.at_level(logging.WARNING):
            out = user_cls._vlm_describe_image(
                instance,
                client,
                PILImage.new("RGB", (8, 8)),
                page_no=2,
            )

        assert out is None
        assert any(
            "returned empty content (page 2)" in r.getMessage()
            for r in caplog.records
        )

    def test_vlm_describe_image_failure_returns_none(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        """A failed API call yields None (never raises) and logs the error,
        so one bad image cannot sink the whole document."""
        import logging

        from PIL import Image as PILImage

        user_cls = DoclingParser._get_user_cls()
        instance = user_cls()

        with caplog.at_level(logging.ERROR):
            out = user_cls._vlm_describe_image(
                instance,
                _BoomVLMClient(),
                PILImage.new("RGB", (8, 8)),
                page_no=None,
            )

        assert out is None
        assert any(
            "OpenAI VLM call failed" in r.getMessage() for r in caplog.records
        )

    def test_encode_image_to_data_url(self) -> None:
        """The data URL is base64 JPEG with the alpha channel dropped, so
        payloads stay small and the vision API accepts them."""
        import base64

        from PIL import Image as PILImage

        user_cls = DoclingParser._get_user_cls()
        url = user_cls._encode_image_to_data_url(
            PILImage.new("RGBA", (4, 4), (255, 0, 0, 128))
        )

        assert url.startswith("data:image/jpeg;base64,")
        payload = base64.b64decode(url.split(",", 1)[1])
        assert payload[:3] == b"\xff\xd8\xff"  # JPEG SOI magic bytes

    def test_page_no_of(self) -> None:
        """1-based page number comes from the item's first provenance;
        items without provenance yield None."""
        pytest.importorskip("docling_core")
        from docling_core.types.doc import DocItemLabel, DoclingDocument
        from docling_core.types.doc.base import BoundingBox, Size
        from docling_core.types.doc.common.reference import ProvenanceItem

        user_cls = DoclingParser._get_user_cls()
        doc = DoclingDocument(name="t")
        doc.add_page(page_no=3, size=Size(width=10, height=10))
        prov = ProvenanceItem(
            page_no=3, bbox=BoundingBox(l=0, t=0, r=10, b=10), charspan=(0, 0)
        )
        item = doc.add_text(label=DocItemLabel.PARAGRAPH, text="hi", prov=prov)
        assert user_cls._page_no_of(item) == 3

        class _NoProv:
            pass

        assert user_cls._page_no_of(_NoProv()) is None

    def test_enrich_missing_image_keeps_placeholder_and_advances(self) -> None:
        """A picture with no extractable image keeps its placeholder, but the
        cursor still advances so the next picture maps to the next
        placeholder rather than the skipped one."""
        pytest.importorskip("docling_core")
        from docling_core.types.doc import DocItemLabel, DoclingDocument
        from docling_core.types.doc.base import BoundingBox, Size
        from docling_core.types.doc.common.reference import ImageRef, ProvenanceItem
        from PIL import Image as PILImage

        img_ref = ImageRef.from_pil(PILImage.new("RGB", (50, 50), "red"), dpi=72)
        doc = DoclingDocument(name="test")
        doc.add_page(page_no=1, size=Size(width=50, height=50), image=img_ref)
        prov = ProvenanceItem(
            page_no=1, bbox=BoundingBox(l=0, t=0, r=50, b=50), charspan=(0, 0)
        )
        doc.add_picture()  # no image / no prov -> get_image() is None
        doc.add_picture(image=img_ref, prov=prov)
        doc.add_text(label=DocItemLabel.PARAGRAPH, text="Outro.")

        md = doc.export_to_markdown(traverse_pictures=True).replace("\x00", "")
        assert md.count("<!-- image -->") == 2

        user_cls = DoclingParser._get_user_cls()
        out = user_cls._enrich_images_with_vlm(
            user_cls(), doc, md, _FakeVLMClient(["SECOND PIC DESC"])
        )
        assert out.count("<!-- image -->") == 1
        assert "**Image description:** SECOND PIC DESC" in out

    def test_process_document_enriches_markdown_with_vlm(
        self, _setup_converter_mock, _patch_httpx, monkeypatch
    ) -> None:
        """With ``OPENAI_API_KEY`` set, ``process_document`` runs the VLM
        phase and uploads markdown with descriptions instead of placeholders."""
        pytest.importorskip("docling_core")
        ctx = _setup_converter_mock
        mock_result = MagicMock()
        mock_result.document = _build_vlm_doc()
        ctx["mock_converter"].convert.return_value = mock_result

        fake_client = _FakeVLMClient(["DESCRIBED IMAGE", "DESCRIBED IMAGE 2"])
        monkeypatch.setenv("OPENAI_API_KEY", "test-key")
        with patch("openai.OpenAI", return_value=fake_client) as mock_openai:
            instance = ctx["user_cls"]()
            ctx["raw_load"](instance)
            _patch_httpx.put.return_value = MagicMock()
            result = ctx["raw_process"](
                instance, "https://example.com/doc.pdf", "https://example.com/upload"
            )

        assert result["status"] == "success"
        mock_openai.assert_called_once_with(api_key="test-key")
        uploaded = _patch_httpx.put.call_args.kwargs["content"].decode("utf-8")
        assert "**Image description:** DESCRIBED IMAGE" in uploaded
        assert "**Image description:** DESCRIBED IMAGE 2" in uploaded
        assert "<!-- image -->" not in uploaded
        # Placeholder-only flow: handwritten items are not transcribed.
        assert "**Transcribed text:**" not in uploaded

    def test_process_document_skips_vlm_without_api_key(
        self, _setup_converter_mock, _patch_httpx, monkeypatch, caplog
    ) -> None:
        """Without ``OPENAI_API_KEY``, enrichment is skipped with a warning
        and the markdown (placeholders intact) is uploaded as-is."""
        import logging

        pytest.importorskip("docling_core")
        ctx = _setup_converter_mock
        mock_result = MagicMock()
        mock_result.document = _build_vlm_doc()
        ctx["mock_converter"].convert.return_value = mock_result

        monkeypatch.delenv("OPENAI_API_KEY", raising=False)
        instance = ctx["user_cls"]()
        ctx["raw_load"](instance)
        _patch_httpx.put.return_value = MagicMock()

        with caplog.at_level(logging.WARNING):
            result = ctx["raw_process"](
                instance, "https://example.com/doc.pdf", "https://example.com/upload"
            )

        assert result["status"] == "success"
        uploaded = _patch_httpx.put.call_args.kwargs["content"].decode("utf-8")
        assert "<!-- image -->" in uploaded
        assert any("OPENAI_API_KEY" in r.getMessage() for r in caplog.records)
        # The post-enrichment placeholder census fires too, so ops can spot
        # un-enriched images even when enrichment was skipped quietly.
        assert any(
            "2 image placeholder(s) remain" in r.getMessage() for r in caplog.records
        )

    def test_process_document_partial_enrichment_logs_remaining_placeholders(
        self, _setup_converter_mock, _patch_httpx, monkeypatch, caplog
    ) -> None:
        """When only some pictures are described (e.g. one VLM response is
        empty), the successful description is uploaded, the failed picture
        keeps its placeholder, and a warning reports how many placeholders
        remain."""
        import logging

        pytest.importorskip("docling_core")
        ctx = _setup_converter_mock
        mock_result = MagicMock()
        mock_result.document = _build_vlm_doc()
        ctx["mock_converter"].convert.return_value = mock_result

        fake_client = _FakeVLMClient(["DESCRIBED IMAGE", ""])
        monkeypatch.setenv("OPENAI_API_KEY", "test-key")
        with patch("openai.OpenAI", return_value=fake_client):
            instance = ctx["user_cls"]()
            ctx["raw_load"](instance)
            _patch_httpx.put.return_value = MagicMock()
            with caplog.at_level(logging.WARNING):
                result = ctx["raw_process"](
                    instance,
                    "https://example.com/doc.pdf",
                    "https://example.com/upload",
                )

        assert result["status"] == "success"
        uploaded = _patch_httpx.put.call_args.kwargs["content"].decode("utf-8")
        assert "**Image description:** DESCRIBED IMAGE" in uploaded
        assert uploaded.count("<!-- image -->") == 1
        assert any(
            "1 image placeholder(s) remain" in r.getMessage() for r in caplog.records
        )


class TestModuleConstants:
    """Tests for module-level constants."""

    def test_app_name(self) -> None:
        """APP_NAME is correctly set."""
        assert APP_NAME == "s3-docling-ocr-pipeline"

    def test_vlm_constants(self) -> None:
        """VLM knobs point at the documented env var / default."""
        assert VLM_MODEL_ENV == "OPENAI_VLM_MODEL"
        assert VLM_MODEL_DEFAULT == "gpt-4o-mini"
        assert IMAGE_PLACEHOLDER == "<!-- image -->"
