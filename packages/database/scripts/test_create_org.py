from sqlmodel import Session
from database.models import Organization
from database.session import create_engine_from_env

org = Organization(name="30-ai")

engine = create_engine_from_env()

with Session(engine) as session:
    session.add(org)
    session.commit()
