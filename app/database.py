from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, sessionmaker
from sqlalchemy.pool import NullPool

from .config import get_settings

settings = get_settings()

database_url = settings.database_url
# Providers (Supabase included) hand out connection strings using the bare
# postgresql:// scheme, which makes SQLAlchemy default to psycopg2 — not
# installed here (requirements.txt only has psycopg3). Normalize to the
# psycopg3 dialect so pasting a provider's raw URL in still works.
if database_url.startswith("postgresql://"):
    database_url = "postgresql+psycopg://" + database_url[len("postgresql://"):]
elif database_url.startswith("postgres://"):
    database_url = "postgresql+psycopg://" + database_url[len("postgres://"):]

connect_args = {}
engine_kwargs = {}
if database_url.startswith("sqlite"):
    connect_args = {"check_same_thread": False}
else:
    # Supabase's connection pooler (Supavisor, transaction mode) rotates the
    # underlying connection per transaction, so server-side prepared
    # statements can't be reused across requests; and pooling on top of an
    # already-pooled endpoint is redundant, especially for Vercel's
    # short-lived serverless instances.
    connect_args = {"prepare_threshold": None}
    engine_kwargs = {"poolclass": NullPool}

engine = create_engine(database_url, connect_args=connect_args, future=True, **engine_kwargs)
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False, future=True)


class Base(DeclarativeBase):
    pass


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
