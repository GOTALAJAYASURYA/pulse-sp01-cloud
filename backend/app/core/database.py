import os
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, declarative_base

raw_url = os.getenv(
    "DATABASE_URL", 
    "postgresql+psycopg://pulse_admin:pulse_secure_password_2026@localhost:5432/pulse_sp01_db"
)

# Normalize database URL for SQLAlchemy + psycopg3
if raw_url.startswith("postgres://"):
    raw_url = raw_url.replace("postgres://", "postgresql+psycopg://", 1)
elif raw_url.startswith("postgresql://") and not raw_url.startswith("postgresql+psycopg://"):
    raw_url = raw_url.replace("postgresql://", "postgresql+psycopg://", 1)

engine = create_engine(raw_url, pool_pre_ping=True)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
