"""Shared fixtures and configuration for API tests.

Uses ``pytest`` with ``httpx`` for async test client support and FastAPI's
``app.dependency_overrides`` to inject mock database sessions.
"""

from collections.abc import Generator
from unittest.mock import MagicMock

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlmodel import Session as SQLModelSession

from database.session import get_db
from src.main import app


@pytest.fixture
def test_app() -> FastAPI:
    """Return the bare FastAPI application instance."""
    return app


@pytest.fixture
async def async_client(test_app: FastAPI) -> AsyncClient:
    """Provide an ``httpx.AsyncClient`` wired to the FastAPI app via ASGI.

    This lets tests call endpoints without needing a running server.
    """
    transport = ASGITransport(app=test_app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        yield client


# ---------------------------------------------------------------------------
# Database session mocking via dependency override
# ---------------------------------------------------------------------------
# FastAPI's ``Depends(get_db)`` captures a reference to the function at
# import time, so patching module-level names after import is ineffective.
# Instead we use ``app.dependency_overrides[get_db]`` which FastAPI consults
# at request time.


@pytest.fixture
def mock_db_session() -> MagicMock:
    """Create a fresh mock database session for a single test.

    The mock supports the standard ``Session`` interface used by the routes:
    ``exec()``, ``get()``, ``add()``, ``commit()``, ``flush()``,
    ``refresh()``, ``delete()``.

    Returns:
        A ``MagicMock`` configured with safe defaults.
    """
    session = MagicMock(spec=SQLModelSession)

    # ``exec()`` returns an object with ``.all()`` and ``.first()``
    exec_result = MagicMock()
    exec_result.all.return_value = []
    exec_result.first.return_value = None
    session.exec.return_value = exec_result

    # ``get()`` returns None by default (object-not-found behaviour)
    session.get.return_value = None

    # ``scalar()`` — used by the duplicate-upload guard clause; default to
    # 0 (no active jobs found) so the happy path is unaffected.
    session.scalar.return_value = 0

    # All other methods (add, commit, flush, refresh, delete, rollback)
    # are plain MagicMocks that accept any call and return themselves.
    return session


@pytest.fixture(autouse=True)
def _override_get_db(mock_db_session: MagicMock) -> Generator[None, None, None]:
    """Install ``mock_db_session`` as the dependency for every test.

    Applied automatically so that no test can accidentally hit a real
    database.  Tests that need a specific session state can manipulate
    ``mock_db_session`` directly or request the ``db_session`` fixture.
    """
    # Clear any previous overrides so we start fresh each test.
    app.dependency_overrides.clear()

    def override_get_db() -> Generator[MagicMock, None, None]:
        yield mock_db_session

    app.dependency_overrides[get_db] = override_get_db
    yield
    app.dependency_overrides.clear()


@pytest.fixture
def db_session(mock_db_session: MagicMock) -> MagicMock:
    """Convenience alias — gives access to the mock database session.

    Example::

        def test_get_organisations(db_session):
            db_session.exec.return_value.all.return_value = [org_1, org_2]
    """
    return mock_db_session


# ---------------------------------------------------------------------------
# S3 / R2 client mocking
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _mock_env_vars() -> Generator[None, None, None]:
    """Set required environment variables for every test.

    Without ``BUCKET_NAME`` the document routes raise 500 immediately.
    """
    import os
    from unittest.mock import patch

    with patch.dict("os.environ", {"BUCKET_NAME": "test-bucket"}):
        yield


@pytest.fixture(autouse=True)
def _mock_r2_client(mock_r2_instance: MagicMock) -> Generator[MagicMock, None, None]:
    """Replace ``R2Client`` with a mock in document routes.

    Delegates to ``mock_r2_instance`` for the mock configuration.
    """
    from unittest.mock import patch

    mock_client_cls = MagicMock()
    mock_client_cls.return_value = mock_r2_instance

    with patch("src.document_routes.R2Client", mock_client_cls):
        yield mock_r2_instance


@pytest.fixture
def r2_client(mock_r2_instance: MagicMock) -> MagicMock:
    """Public fixture giving tests access to the mocked ``R2Client`` instance.

    Use this to override default behaviour such as ``file_exists``::

        def test_foo(r2_client):
            r2_client.file_exists.return_value = False
    """
    return mock_r2_instance


@pytest.fixture
def mock_r2_instance() -> Generator[MagicMock, None, None]:
    """Internal fixture that creates the mock R2 instance.

    Separated so both ``_mock_r2_client`` and ``r2_client`` can reference it
    without duplicating configuration.
    """
    mock_instance = MagicMock()

    presigned_response = MagicMock()
    presigned_response.url = "https://test-bucket.r2.dev/test-key"
    presigned_response.bucket = "test-bucket"
    presigned_response.key = "test-key"
    presigned_response.method = "PUT"
    presigned_response.expires_in = 3600
    presigned_response.message = "Presigned URL generated for PUT operation"

    mock_instance.generate_presigned_url.return_value = presigned_response
    mock_instance.delete_file.return_value = MagicMock(success=True)
    mock_instance.file_exists.return_value = True

    return mock_instance


# ---------------------------------------------------------------------------
# Celery mocking
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _mock_celery() -> Generator[MagicMock, None, None]:
    """Replace ``celery.send_task`` with a mock to avoid needing a broker.

    The mock returns a result object with a ``.id`` attribute matching the
    ``task_id`` that was passed in.
    """
    from unittest.mock import patch

    mock_result = MagicMock()
    mock_result.id = "00000000-0000-0000-0000-000000000000"

    mock_celery = MagicMock()
    mock_celery.send_task.return_value = mock_result

    with patch("src.document_routes.celery", mock_celery):
        yield mock_celery
