from sqlalchemy import Column, Integer, String, Float, Boolean, DateTime, ForeignKey, JSON, Text
from sqlalchemy.orm import relationship, backref as sa_backref
from database import Base


class User(Base):
    __tablename__ = "users"
    id = Column(Integer, primary_key=True, index=True)
    username = Column(String, unique=True, index=True, nullable=False)
    email = Column(String, unique=True, index=True, nullable=True)
    password_hash = Column(String, nullable=False)
    is_admin = Column(Boolean, default=False)
    total_score = Column(Integer, default=0)
    stars_remaining = Column(Integer, default=3)

    predictions = relationship("Prediction", back_populates="user")
    special_answers = relationship("SpecialEventAnswer", back_populates="user")
    champion_bets = relationship("ChampionBet", back_populates="user")


class PendingRegistration(Base):
    __tablename__ = "pending_registrations"
    id = Column(Integer, primary_key=True, index=True)
    email = Column(String, unique=True, index=True, nullable=False)
    username = Column(String, nullable=False)
    password_hash = Column(String, nullable=False)
    otp_code = Column(String(6), nullable=False)
    otp_expires_at = Column(DateTime, nullable=False)
    attempts = Column(Integer, default=0)
    last_sent_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, nullable=False)


class Team(Base):
    __tablename__ = "teams"
    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, nullable=False)
    name_normalised = Column(String, nullable=True)
    flag_emoji = Column(String, nullable=False)
    flag_code = Column(String, nullable=True)   # e.g. "mx", "gb-eng" – for flagcdn.com
    group = Column(String, nullable=True)
    continent = Column(String, nullable=True)
    fifa_code = Column(String, nullable=True)
    confed = Column(String, nullable=True)


class Match(Base):
    __tablename__ = "matches"
    id = Column(Integer, primary_key=True, index=True)
    match_num = Column(Integer, nullable=True)
    stage = Column(String, nullable=False)
    round_name = Column(String, nullable=True)
    group_name = Column(String, nullable=True)
    match_date = Column(DateTime, nullable=False)
    team_home_id = Column(Integer, ForeignKey("teams.id"), nullable=True)
    team_away_id = Column(Integer, ForeignKey("teams.id"), nullable=True)
    team_home_label = Column(String, nullable=True)
    team_away_label = Column(String, nullable=True)
    score_home = Column(Integer, nullable=True)
    score_away = Column(Integer, nullable=True)
    winner_id = Column(Integer, ForeignKey("teams.id"), nullable=True)
    home_strength_rating = Column(Float, default=0.5)
    ground = Column(String, nullable=True)
    rating_home = Column(Float, nullable=True)   # e.g. 1.5 (handicap line)
    rating_away = Column(Float, nullable=True)   # e.g. 0.0

    # Pre-match media
    youtube_url  = Column(String, nullable=True)
    players_note = Column(String, nullable=True)
    preview_text = Column(String, nullable=True)

    # Live score tracking (updated by background poller)
    fd_match_id = Column(Integer, nullable=True)   # football-data.org match ID
    live_status = Column(String, nullable=True)    # IN_PLAY / PAUSED / EXTRA_TIME / FINISHED
    live_minute = Column(Integer, nullable=True)   # current minute when IN_PLAY

    # Rich match data (fetched from API, stored as JSON)
    goals_data   = Column(JSON, nullable=True)  # [{minute, type, team_id, scorer, assist, score_home, score_away}]
    lineups_data = Column(JSON, nullable=True)  # {home: {formation, coach, lineup, bench}, away: {...}}
    stats_data   = Column(JSON, nullable=True)  # {home: {possession, shots, ...}, away: {...}}
    events_data  = Column(JSON, nullable=True)  # {bookings: [...], substitutions: [...]}

    # Post-match media
    highlight_url = Column(String, nullable=True)
    match_summary = Column(String, nullable=True)

    team_home = relationship("Team", foreign_keys=[team_home_id])
    team_away = relationship("Team", foreign_keys=[team_away_id])
    winner = relationship("Team", foreign_keys=[winner_id])
    predictions = relationship("Prediction", back_populates="match")
    result = relationship("Result", back_populates="match", uselist=False)


class Result(Base):
    __tablename__ = "results"
    id = Column(Integer, primary_key=True, index=True)
    match_id = Column(Integer, ForeignKey("matches.id"), unique=True, nullable=False)
    score_home = Column(Integer, nullable=True)       # 90-min score
    score_away = Column(Integer, nullable=True)
    score_home_et = Column(Integer, nullable=True)    # after extra time
    score_away_et = Column(Integer, nullable=True)
    score_home_pen = Column(Integer, nullable=True)   # penalty shootout
    score_away_pen = Column(Integer, nullable=True)
    is_extra_time = Column(Boolean, default=False)
    is_penalties = Column(Boolean, default=False)
    winner_id = Column(Integer, ForeignKey("teams.id"), nullable=True)

    match = relationship("Match", back_populates="result")
    winner = relationship("Team", foreign_keys=[winner_id])


class Prediction(Base):
    __tablename__ = "predictions"
    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    match_id = Column(Integer, ForeignKey("matches.id"), nullable=False)
    predicted_winner_id = Column(Integer, ForeignKey("teams.id"), nullable=False)
    points_earned = Column(Integer, nullable=True)
    use_star = Column(Boolean, default=False)

    user = relationship("User", back_populates="predictions")
    match = relationship("Match", back_populates="predictions")
    predicted_winner = relationship("Team", foreign_keys=[predicted_winner_id])


class SpecialEvent(Base):
    __tablename__ = "special_events"
    id = Column(Integer, primary_key=True, index=True)
    title = Column(String, nullable=False)
    description = Column(String, nullable=True)
    deadline = Column(DateTime, nullable=False)
    options = Column(JSON, nullable=False, default=list)
    correct_answer = Column(String, nullable=True)

    answers = relationship("SpecialEventAnswer", back_populates="special_event")


class PasswordResetToken(Base):
    __tablename__ = "password_reset_tokens"
    id = Column(Integer, primary_key=True, index=True)
    email = Column(String, unique=True, index=True, nullable=False)
    otp_code = Column(String(6), nullable=False)
    otp_expires_at = Column(DateTime, nullable=False)
    attempts = Column(Integer, default=0)
    last_sent_at = Column(DateTime, nullable=True)


class SpecialEventAnswer(Base):
    __tablename__ = "special_event_answers"
    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    special_event_id = Column(Integer, ForeignKey("special_events.id"), nullable=False)
    answer = Column(String, nullable=False)
    points_earned = Column(Integer, nullable=True)

    user = relationship("User", back_populates="special_answers")
    special_event = relationship("SpecialEvent", back_populates="answers")


class ChampionEvent(Base):
    __tablename__ = "champion_events"
    id = Column(Integer, primary_key=True, index=True)
    title = Column(String, nullable=False)
    description = Column(String, nullable=True)
    deadline = Column(DateTime, nullable=False)
    # [{name: str, rate: float}]
    teams = Column(JSON, nullable=False, default=list)
    winner = Column(String, nullable=True)

    bets = relationship("ChampionBet", back_populates="champion_event")


class ChampionBet(Base):
    __tablename__ = "champion_bets"
    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    champion_event_id = Column(Integer, ForeignKey("champion_events.id"), nullable=False)
    team_name = Column(String, nullable=False)
    bet_amount = Column(Integer, nullable=False)
    rate = Column(Float, nullable=False)
    points_earned = Column(Integer, nullable=True)

    user = relationship("User", back_populates="champion_bets")
    champion_event = relationship("ChampionEvent", back_populates="bets")


class Article(Base):
    __tablename__ = "articles"
    id            = Column(Integer, primary_key=True, index=True)
    title         = Column(String, nullable=False)
    source_url    = Column(String, unique=True, nullable=False, index=True)
    thumbnail_url = Column(String, nullable=True)
    excerpt       = Column(Text, nullable=True)
    published_at  = Column(DateTime, nullable=True)
    crawled_at    = Column(DateTime, nullable=False)


class MatchArticle(Base):
    __tablename__ = "match_articles"
    id           = Column(Integer, primary_key=True, index=True)
    match_id     = Column(Integer, ForeignKey("matches.id"), unique=True, nullable=False)
    source_url   = Column(String, nullable=False)
    title        = Column(String, nullable=True)
    content_html = Column(Text, nullable=True)
    crawled_at   = Column(DateTime, nullable=False)

    match = relationship("Match", backref=sa_backref("article", uselist=False))


class MatchPenalty(Base):
    """Tracks the no-prediction penalty applied to users who skipped a match."""
    __tablename__ = "match_penalties"
    id       = Column(Integer, primary_key=True, index=True)
    user_id  = Column(Integer, ForeignKey("users.id"), nullable=False)
    match_id = Column(Integer, ForeignKey("matches.id"), nullable=False)
    points_earned = Column(Integer, nullable=False)
