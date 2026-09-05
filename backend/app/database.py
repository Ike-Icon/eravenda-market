import os
from dotenv import load_dotenv  # type: ignore[import-not-found]
from sqlalchemy import create_engine  # type: ignore[import-not-found]
from sqlalchemy.orm import sessionmaker, declarative_base  # type: ignore[import-not-found]

load_dotenv()

DATABASE_URL = os.getenv("DATABASE_URL", "postgresql://postgres:postgres@localhost:5432/marketplace")

engine = create_engine(DATABASE_URL, pool_pre_ping=True)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
