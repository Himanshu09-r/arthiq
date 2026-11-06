import os
from dotenv import load_dotenv

load_dotenv()
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from app.db.models import Base

DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///arthiq.db")
engine = create_engine(DATABASE_URL, connect_args={"check_same_thread": False})
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
