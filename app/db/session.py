import os
from dotenv import load_dotenv
load_dotenv()

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from app.db.models import Base


def _database_url() -> str:
    url = os.getenv("DATABASE_URL", "sqlite:///arthiq.db").strip()
    # Neon commonly provides postgresql://; use psycopg 3 explicitly.
    if url.startswith("postgres://"):
        url = "postgresql+psycopg://" + url[len("postgres://"): ]
    elif url.startswith("postgresql://"):
        url = "postgresql+psycopg://" + url[len("postgresql://"): ]
    return url


DATABASE_URL = _database_url()
_engine_kwargs = {"pool_pre_ping": True}
if DATABASE_URL.startswith("sqlite"):
    _engine_kwargs["connect_args"] = {"check_same_thread": False, "timeout": 30}
engine = create_engine(DATABASE_URL, **_engine_kwargs)
SessionLocal = sessionmaker(bind=engine, expire_on_commit=False)


def init_db(target_engine=None):
    eng = target_engine or engine
    Base.metadata.create_all(eng)
    from app.db.migrate import run_migrations
    run_migrations(eng)


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
