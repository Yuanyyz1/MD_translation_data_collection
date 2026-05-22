import os
from pathlib import Path

from sqlalchemy import create_engine
from sqlalchemy.orm import declarative_base, sessionmaker

BASE_DIR = Path(__file__).resolve().parent.parent

def resolve_database_url() -> str:
    configured_url = (os.getenv("DATABASE_URL") or "").strip()
    if configured_url:
        return configured_url

    # Vercel serverless runtime can only write to /tmp.
    if (os.getenv("VERCEL") or "").strip() == "1":
        tmp_db_path = Path("/tmp") / "app_live.db"
        return f"sqlite:///{tmp_db_path.as_posix()}"

    # Local development default (Windows-friendly path).
    local_db_dir = Path.home() / "AppData" / "Local" / "data_collection_error_insertion"
    local_db_dir.mkdir(parents=True, exist_ok=True)
    local_db_path = local_db_dir / "app_live.db"
    return f"sqlite:///{local_db_path.as_posix()}"


DATABASE_URL = resolve_database_url()
connect_args = {"check_same_thread": False} if DATABASE_URL.startswith("sqlite") else {}

engine = create_engine(DATABASE_URL, connect_args=connect_args)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
