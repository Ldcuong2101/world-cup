from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, declarative_base

DATABASE_URL = "sqlite:///./worldcup.db"

engine = create_engine(DATABASE_URL, connect_args={"check_same_thread": False})
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def init_db():
    from models import User, Team, Match, Prediction, SpecialEvent, SpecialEventAnswer, Result, PendingRegistration  # noqa
    from sqlalchemy import text
    Base.metadata.create_all(bind=engine)
    # Add new columns to existing tables without a migration tool
    with engine.connect() as conn:
        for stmt in [
            "ALTER TABLE users ADD COLUMN email TEXT",
        ]:
            try:
                conn.execute(text(stmt))
                conn.commit()
            except Exception:
                pass  # Column already exists
