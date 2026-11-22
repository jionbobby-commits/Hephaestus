import os
from pathlib import Path

from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, sessionmaker

DATABASE_URL = os.getenv("HEPHAESTUS_DATABASE_URL", "sqlite:///./data/hephaestus.db")

if DATABASE_URL.startswith("sqlite:///") and DATABASE_URL != "sqlite:///:memory:":
    database_path = DATABASE_URL.removeprefix("sqlite:///")
    if not database_path.startswith("/"):
        Path(database_path).parent.mkdir(parents=True, exist_ok=True)

connect_args = {"check_same_thread": False} if DATABASE_URL.startswith("sqlite") else {}
engine = create_engine(DATABASE_URL, connect_args=connect_args, pool_pre_ping=True)
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)


class Base(DeclarativeBase):
    pass


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def create_db() -> None:
    # Import models so SQLAlchemy registers every table before create_all.
    from app import models  # noqa: F401

    Base.metadata.create_all(bind=engine)
