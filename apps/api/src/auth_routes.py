from fastapi import APIRouter, Depends, HTTPException
from sqlmodel import Session, select

from database.models import Organization, User
from database.session import get_db

from logutil import get_logger

logger = get_logger(__name__)

router = APIRouter(prefix="/api", tags=["auth"])


@router.get("/organizations", response_model=list[Organization])
def get_organizations(db: Session = Depends(get_db)):
    """Get all organizations."""
    organizations = db.exec(select(Organization)).all()
    logger.info("Retrieved %d organizations", len(organizations))
    return organizations


@router.get("/organizations/{organization_id}", response_model=Organization)
def get_organization(organization_id: str, db: Session = Depends(get_db)):
    """Get a specific organization."""
    organization = db.get(Organization, organization_id)
    if not organization:
        logger.warning("Organization not found: %s", organization_id)
        raise HTTPException(status_code=404, detail="Organization not found")
    logger.debug("Retrieved organization: %s", organization_id)
    return organization


@router.get("/users", response_model=list[User])
def get_users(db: Session = Depends(get_db)):
    """Get all users."""
    users = db.exec(select(User)).all()
    logger.info("Retrieved %d users", len(users))
    return users
