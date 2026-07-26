"""Authentication and organisation/user management routes.

Endpoints prefixed with ``/api`` and tagged ``auth``:

- ``GET /api/organizations`` — List all organisations.
- ``GET /api/organizations/{organization_id}`` — Fetch a single organisation.
- ``GET /api/users`` — List all users.

All endpoints depend on a SQLModel database session injected via FastAPI's
``Depends`` mechanism (see ``database.session.get_db``).
"""

from fastapi import APIRouter, Depends, HTTPException
from sqlmodel import Session, select

from database.models import Organization, User
from database.session import get_db

from logutil import get_logger

logger = get_logger(__name__)

router = APIRouter(prefix="/api", tags=["auth"])


@router.get("/organizations", response_model=list[Organization])
def get_organizations(db: Session = Depends(get_db)) -> list[Organization]:
    """Retrieve all organisations.

    Args:
        db: Injected database session.

    Returns:
        List of all ``Organization`` records.
    """
    organizations = db.exec(select(Organization)).all()
    logger.info("Retrieved %d organizations", len(organizations))
    return organizations


@router.get("/organizations/{organization_id}", response_model=Organization)
def get_organization(
    organization_id: str, db: Session = Depends(get_db)
) -> Organization:
    """Retrieve a single organisation by its UUID.

    Args:
        organization_id: The organisation's UUID (string form).
        db: Injected database session.

    Returns:
        The matching ``Organization`` record.

    Raises:
        HTTPException 404: If no organisation with the given ID exists.
    """
    organization = db.get(Organization, organization_id)
    if not organization:
        logger.warning("Organization not found: %s", organization_id)
        raise HTTPException(status_code=404, detail="Organization not found")
    logger.debug("Retrieved organization: %s", organization_id)
    return organization


@router.get("/users", response_model=list[User])
def get_users(db: Session = Depends(get_db)) -> list[User]:
    """Retrieve all users.

    Args:
        db: Injected database session.

    Returns:
        List of all ``User`` records.
    """
    users = db.exec(select(User)).all()
    logger.info("Retrieved %d users", len(users))
    return users
