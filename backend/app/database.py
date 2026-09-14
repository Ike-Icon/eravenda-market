import os
from dotenv import load_dotenv  # type: ignore[import-not-found]
from sqlalchemy import create_engine  # type: ignore[import-not-found]
from sqlalchemy.orm import sessionmaker, declarative_base  # type: ignore[import-not-found]

load_dotenv()

DATABASE_URL = os.getenv("DATABASE_URL", "postgresql://postgres:postgres@localhost:5432/marketplace")

engine_options = {
    "pool_pre_ping": True,
    "pool_recycle": int(os.getenv("DB_POOL_RECYCLE_SECONDS", "1800")),
    "pool_timeout": int(os.getenv("DB_POOL_TIMEOUT_SECONDS", "30")),
}
if DATABASE_URL.startswith("postgresql"):
    engine_options.update({
        "pool_size": int(os.getenv("DB_POOL_SIZE", "5")),
        "max_overflow": int(os.getenv("DB_MAX_OVERFLOW", "10")),
        "connect_args": {"connect_timeout": int(os.getenv("DB_CONNECT_TIMEOUT_SECONDS", "10"))},
    })

engine = create_engine(DATABASE_URL, **engine_options)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
