import sys
import os
sys.path.insert(0, os.path.dirname(__file__))

from datetime import datetime, timedelta
from database import SessionLocal, init_db
from models import User, Team, Match, SpecialEvent
from auth import hash_password

init_db()
db = SessionLocal()

# Clear existing data
for model in [SpecialEvent, Match, User, Team]:
    db.query(model).delete()
db.commit()

# Admin users
admins = [
    User(username="admin", password_hash=hash_password("admin123"), is_admin=True, total_score=0),
    User(username="superadmin", password_hash=hash_password("superadmin123"), is_admin=True, total_score=0),
]
db.add_all(admins)

# Regular users
users = [
    User(username="alice", password_hash=hash_password("alice123"), is_admin=False, total_score=0),
    User(username="bob", password_hash=hash_password("bob123"), is_admin=False, total_score=0),
    User(username="charlie", password_hash=hash_password("charlie123"), is_admin=False, total_score=0),
    User(username="diana", password_hash=hash_password("diana123"), is_admin=False, total_score=0),
    User(username="eve", password_hash=hash_password("eve123"), is_admin=False, total_score=0),
]
db.add_all(users)

# Teams
teams_data = [
    ("Brazil", "🇧🇷", "A"),
    ("Germany", "🇩🇪", "A"),
    ("France", "🇫🇷", "B"),
    ("Argentina", "🇦🇷", "B"),
    ("England", "🏴󠁧󠁢󠁥󠁮󠁧󠁿", "C"),
    ("Spain", "🇪🇸", "C"),
    ("Portugal", "🇵🇹", "D"),
    ("Netherlands", "🇳🇱", "D"),
]
teams = [Team(name=n, flag_emoji=f, group=g) for n, f, g in teams_data]
db.add_all(teams)
db.flush()

now = datetime.utcnow()

# Matches
matches = [
    Match(
        stage="group", match_date=now - timedelta(days=5),
        team_home_id=teams[0].id, team_away_id=teams[1].id,
        score_home=2, score_away=1, winner_id=teams[0].id,
        home_strength_rating=0.65,
    ),
    Match(
        stage="group", match_date=now - timedelta(days=3),
        team_home_id=teams[2].id, team_away_id=teams[3].id,
        score_home=None, score_away=None, winner_id=None,
        home_strength_rating=0.50,
    ),
    Match(
        stage="group", match_date=now + timedelta(days=2),
        team_home_id=teams[4].id, team_away_id=teams[5].id,
        score_home=None, score_away=None, winner_id=None,
        home_strength_rating=0.45,
    ),
    Match(
        stage="r16", match_date=now + timedelta(days=5),
        team_home_id=teams[6].id, team_away_id=teams[7].id,
        score_home=None, score_away=None, winner_id=None,
        home_strength_rating=0.55,
    ),
    Match(
        stage="semi", match_date=now + timedelta(days=10),
        team_home_id=teams[0].id, team_away_id=teams[2].id,
        score_home=None, score_away=None, winner_id=None,
        home_strength_rating=0.60,
    ),
    Match(
        stage="final", match_date=now + timedelta(days=15),
        team_home_id=teams[3].id, team_away_id=teams[4].id,
        score_home=None, score_away=None, winner_id=None,
        home_strength_rating=0.40,
    ),
]
db.add_all(matches)

# Special Events
events = [
    SpecialEvent(
        title="Top Scorer",
        description="Who will finish as the tournament's top goal scorer?",
        deadline=now + timedelta(days=1),
        options=["Mbappé", "Ronaldo", "Messi", "Haaland", "Kane"],
        correct_answer=None,
    ),
    SpecialEvent(
        title="Golden Glove",
        description="Which goalkeeper will win the Golden Glove award?",
        deadline=now + timedelta(days=3),
        options=["Alisson", "Neuer", "Courtois", "Pickford"],
        correct_answer=None,
    ),
]
db.add_all(events)

db.commit()
print("Seed complete.")
print("Admin logins: admin/admin123, superadmin/superadmin123")
print("User logins: alice/alice123, bob/bob123, charlie/charlie123, diana/diana123, eve/eve123")
db.close()
