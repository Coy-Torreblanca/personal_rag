"""Tests for the authentication / organisation / user routes."""

from uuid import UUID, uuid4
from unittest.mock import MagicMock

import pytest
from httpx import AsyncClient

from database.models import Organization, User


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def make_org(**overrides: dict) -> Organization:
    """Build a minimal ``Organization`` instance with sensible defaults."""
    defaults = {
        "id": uuid4(),
        "name": "Test Org",
        "clerk_organization_id": None,
        "meta_data": {},
    }
    defaults.update(overrides)
    return Organization(**defaults)


def make_user(**overrides: dict) -> User:
    """Build a minimal ``User`` instance with sensible defaults."""
    defaults = {
        "id": uuid4(),
        "email": "user@test.com",
        "full_name": "Test User",
        "organization_id": uuid4(),
        "meta_data": {},
    }
    defaults.update(overrides)
    return User(**defaults)


# ---------------------------------------------------------------------------
# GET /api/organizations
# ---------------------------------------------------------------------------


class TestGetOrganizations:
    """``GET /api/organizations`` — list all organisations."""

    async def test_returns_empty_list_when_no_organisations(
        self, async_client: AsyncClient, db_session: MagicMock
    ) -> None:
        """If the database has no rows, return an empty JSON array."""
        resp = await async_client.get("/api/organizations")
        assert resp.status_code == 200
        assert resp.json() == []

    async def test_returns_list_of_organisations(
        self, async_client: AsyncClient, db_session: MagicMock
    ) -> None:
        """It should serialise ``Organization`` records correctly."""
        org = make_org(name="Acme Corp")
        db_session.exec.return_value.all.return_value = [org]

        resp = await async_client.get("/api/organizations")
        assert resp.status_code == 200
        data = resp.json()
        assert len(data) == 1
        assert data[0]["name"] == "Acme Corp"
        assert data[0]["id"] == str(org.id)

    async def test_response_is_json_array(
        self, async_client: AsyncClient, db_session: MagicMock
    ) -> None:
        """The response body must be a JSON array of objects."""
        orgs = [make_org(name=f"Org {i}") for i in range(3)]
        db_session.exec.return_value.all.return_value = orgs

        resp = await async_client.get("/api/organizations")
        data = resp.json()
        assert isinstance(data, list)
        assert len(data) == 3


# ---------------------------------------------------------------------------
# GET /api/organizations/{organization_id}
# ---------------------------------------------------------------------------


class TestGetOrganization:
    """``GET /api/organizations/{org_id}`` — single organisation fetch."""

    async def test_returns_404_when_not_found(
        self, async_client: AsyncClient, db_session: MagicMock
    ) -> None:
        """If the org does not exist, return 404."""
        db_session.get.return_value = None
        resp = await async_client.get(f"/api/organizations/{uuid4()}")
        assert resp.status_code == 404
        assert resp.json()["detail"] == "Organization not found"

    async def test_returns_organisation_when_found(
        self, async_client: AsyncClient, db_session: MagicMock
    ) -> None:
        """It should return the matching ``Organization``."""
        org = make_org(name="Found Org")
        db_session.get.return_value = org

        resp = await async_client.get(f"/api/organizations/{org.id}")
        assert resp.status_code == 200
        data = resp.json()
        assert data["name"] == "Found Org"
        assert data["id"] == str(org.id)

    async def test_invalid_uuid_returns_404_not_422(
        self, async_client: AsyncClient, db_session: MagicMock
    ) -> None:
        """Passing a non-UUID string returns 404 (not 422).

        The endpoint parameter is typed as ``str``, not ``UUID``, so FastAPI
        does *not* perform UUID validation.  The string is passed to
        ``db.get(Organization, "not-a-uuid")`` which returns ``None``,
        triggering the 404 handler.
        """
        resp = await async_client.get("/api/organizations/not-a-uuid")
        assert resp.status_code == 404


# ---------------------------------------------------------------------------
# GET /api/users
# ---------------------------------------------------------------------------


class TestGetUsers:
    """``GET /api/users`` — list all users."""

    async def test_returns_empty_list_when_no_users(
        self, async_client: AsyncClient, db_session: MagicMock
    ) -> None:
        """If the database has no rows, return an empty JSON array."""
        resp = await async_client.get("/api/users")
        assert resp.status_code == 200
        assert resp.json() == []

    async def test_returns_list_of_users(
        self, async_client: AsyncClient, db_session: MagicMock
    ) -> None:
        """It should serialise ``User`` records correctly."""
        user = make_user(email="alice@test.com")
        db_session.exec.return_value.all.return_value = [user]

        resp = await async_client.get("/api/users")
        assert resp.status_code == 200
        data = resp.json()
        assert len(data) == 1
        assert data[0]["email"] == "alice@test.com"
