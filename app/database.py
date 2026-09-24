from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, sessionmaker
from sqlalchemy.pool import NullPool

from .config import get_settings

settings = get_settings()

connect_args = {}
engine_kwargs = {}
if settings.database_url.startswith("sqlite"):
    connect_args = {"check_same_thread": False}
else:
    # Supabase's connection pooler (Supavisor, transaction mode) rotates the
    # underlying connection per transaction, so server-side prepared
    # statements can't be reused across requests; and pooling on top of an
    # already-pooled endpoint is redundant, especially for Vercel's
    # short-lived serverless instances.
    connect_args = {"prepare_threshold": None}
    engine_kwargs = {"poolclass": NullPool}

engine = create_engine(settings.database_url, connect_args=connect_args, future=True, **engine_kwargs)
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False, future=True)


class Base(DeclarativeBase):
    pass


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
