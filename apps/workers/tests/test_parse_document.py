"""Tests for the parse_document module (DoclingParser).

``DoclingParser`` is wrapped by Modal's ``@app.cls()`` decorator,
which transforms it into a ``modal.cls.Cls`` instance at runtime.
To test the underlying logic without a Modal runtime, we:
1. Retrieve the original Python class via ``Cls._get_user_cls()``.
2. Retrieve the raw method functions via ``PartialFunction._get_raw_f()``.
3. Manually instantiate the user class and call the raw methods.

Because ``docling`` (a heavy dev-dependency) is not always installed,
we inject mock modules into ``sys.modules`` before patching.
"""

import sys
from unittest.mock import MagicMock, patch

import pytest

from src.parse_document import APP_NAME, DoclingParser


# ── Patch httpx via sys.modules ──────────────────────────────────
# ``httpx`` is imported *inside* ``process_document`` (``import httpx``).
# ``unittest.mock.patch`` requires a dotted ``module.attribute`` path,
# so we pre-populate ``sys.modules["httpx"]`` with a mock instead.


@pytest.fixture(autouse=True)
def _patch_httpx() -> MagicMock:
    """Pre-populate ``sys.modules["httpx"]`` with a mock so that local
    imports inside ``process_document`` resolve to our controlled mock."""
    mock_httpx = MagicMock()
    with patch.dict("sys.modules", {"httpx": mock_httpx}):
        yield mock_httpx


# ── Inject mock docling module ───────────────────────────────────
# ``DocumentConverter`` is imported inside ``DoclingParser.load_modals``.
# Rather than requiring the real (heavy) ``docling`` package, we
# pre-populate ``sys.modules`` with mock modules so that the import
# inside ``load_modals`` resolves to our mock.


@pytest.fixture(scope="session", autouse=True)
def _mock_docling_module() -> None:
    """Inject a mock ``docling`` module tree once per session."""
    if "docling" not in sys.modules:
        mock_docling = MagicMock()
        mock_docling.document_converter = MagicMock()
        mock_docling.document_converter.DocumentConverter = MagicMock()

        sys.modules["docling"] = mock_docling
        sys.modules["docling.document_converter"] = mock_docling.document_converter


@pytest.fixture(autouse=True)
def _setup_converter_mock() -> None:
    """Patch ``DocumentConverter`` before each test and extract raw
    functions from Modal wrappers."""
    with patch("docling.document_converter.DocumentConverter") as mock_cls:
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
        }


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


class TestModuleConstants:
    """Tests for module-level constants."""

    def test_app_name(self) -> None:
        """APP_NAME is correctly set."""
        assert APP_NAME == "s3-docling-ocr-pipeline"
