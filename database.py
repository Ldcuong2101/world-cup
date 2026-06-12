from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, declarative_base

import os
_DB_PATH = os.environ.get("DB_PATH", "./worldcup.db")
DATABASE_URL = f"sqlite:///{_DB_PATH}"

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
    from models import User, Team, Match, Prediction, SpecialEvent, SpecialEventAnswer, Result, PendingRegistration, PasswordResetToken, Article, MatchArticle  # noqa
    from sqlalchemy import text
    Base.metadata.create_all(bind=engine)
    # Add new columns to existing tables without a migration tool
    with engine.connect() as conn:
        for stmt in [
            "ALTER TABLE users ADD COLUMN email TEXT",
            "ALTER TABLE users ADD COLUMN stars_remaining INTEGER DEFAULT 3",
            "ALTER TABLE predictions ADD COLUMN use_star BOOLEAN DEFAULT 0",
            "ALTER TABLE matches ADD COLUMN fd_match_id INTEGER",
            "ALTER TABLE matches ADD COLUMN live_status TEXT",
            "ALTER TABLE matches ADD COLUMN live_minute INTEGER",
            "ALTER TABLE matches ADD COLUMN goals_data TEXT",
            "ALTER TABLE matches ADD COLUMN lineups_data TEXT",
            "ALTER TABLE matches ADD COLUMN stats_data TEXT",
            "ALTER TABLE matches ADD COLUMN events_data TEXT",
        ]:
            try:
                conn.execute(text(stmt))
                conn.commit()
            except Exception:
                pass  # Column already exists
