"""Provider factory for creating document parsing providers."""

import logging

from ..config import settings
from .base import BaseProvider
from .docling_provider import DoclingProvider

logger = logging.getLogger(__name__)


def get_provider() -> BaseProvider:
    """
    Get the configured document parsing provider.

    Returns:
        An instance of the configured provider

    Raises:
        ValueError: If the configured provider is not supported
    """
    provider_name = settings.docparse_provider.lower()

    logger.info(f"Initializing provider: {provider_name}")

    if provider_name == "docling":
        return DoclingProvider()
    else:
        raise ValueError(
            f"Unsupported provider: {provider_name}. "
            f"Available providers: docling"
        )
