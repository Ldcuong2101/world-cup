import sys
import os
import json
import re
from datetime import datetime, timedelta

sys.path.insert(0, os.path.dirname(__file__))

from database import SessionLocal, engine, Base
from models import User, Team, Match, Prediction, SpecialEvent, SpecialEventAnswer
from auth import hash_password

METADATA_DIR = os.path.join(os.path.dirname(__file__), "metadata")
TEAMS_JSON = os.path.join(METADATA_DIR, "worldcup.teams_meta.json")
MATCHES_JSON = os.path.join(METADATA_DIR, "worldcup.json")

def parse_flag_code(flag_unicode_str: str):
    """Derive flagcdn.com country/subdivision code from the flag_unicode field."""
    codes = re.findall(r'\\u\{([0-9A-Fa-f]+)\}', flag_unicode_str)
    if not codes:
        return None
    first = int(codes[0], 16)
    if first == 0x1F3F4:  # Subdivision flag (England, Scotland, Wales)
        letters = ""
        for c in codes[1:]:
            val = int(c, 16)
            if val == 0xE007F:
                break
            letters += chr(val - 0xE0000)
        if len(letters) >= 4:
            return letters[:2] + "-" + letters[2:]  # "gb-eng", "gb-sct"
        return None
    elif 0x1F1E6 <= first <= 0x1F1FF:  # Regional indicator pair
        l1 = chr(first - 0x1F1E6 + ord("a"))
        if len(codes) >= 2:
            l2 = chr(int(codes[1], 16) - 0x1F1E6 + ord("a"))
            return l1 + l2
    return None


ROUND_TO_STAGE = {
    "Round of 32": "r32",
    "Round of 16": "r16",
    "Quarter-final": "r8",
    "Semi-final": "semi",
    "Match for third place": "r4",
    "Final": "final",
}


def parse_match_datetime(date_str: str, time_str: str) -> datetime:
    parts = time_str.split()
    time_part = parts[0]
    tz_str = parts[1]
    m = re.match(r"UTC([+-]\d+)", tz_str)
    offset = int(m.group(1))
    dt = datetime.strptime(f"{date_str} {time_part}", "%Y-%m-%d %H:%M")
    return dt - timedelta(hours=offset)


def get_stage(round_name: str) -> str:
    if round_name.startswith("Matchday"):
        return "group"
    return ROUND_TO_STAGE.get(round_name, round_name)


# Drop and recreate all tables to pick up schema changes
print("Recreating schema…")
Base.metadata.drop_all(bind=engine)
Base.metadata.create_all(bind=engine)

db = SessionLocal()

# ── Users ─────────────────────────────────────────────────────────────────────
print("Seeding users…")
db.add_all([
    User(username="admin", password_hash=hash_password("admin123"), is_admin=True, total_score=0),
    # User(username="superadmin", password_hash=hash_password("superadmin123"), is_admin=True, total_score=0),
    # User(username="alice", password_hash=hash_password("alice123"), is_admin=False, total_score=0),
    # User(username="bob", password_hash=hash_password("bob123"), is_admin=False, total_score=0),
    # User(username="charlie", password_hash=hash_password("charlie123"), is_admin=False, total_score=0),
    # User(username="diana", password_hash=hash_password("diana123"), is_admin=False, total_score=0),
    # User(username="eve", password_hash=hash_password("eve123"), is_admin=False, total_score=0),
])
db.commit()

# ── Teams ─────────────────────────────────────────────────────────────────────
print("Seeding teams…")
with open(TEAMS_JSON, encoding="utf-8") as f:
    teams_data = json.load(f)

team_by_name = {}
for t in teams_data:
    team = Team(
        name=t["name"],
        name_normalised=t.get("name_normalised"),
        flag_emoji=t["flag_icon"],
        flag_code=parse_flag_code(t.get("flag_unicode", "")),
        group=t.get("group"),
        continent=t.get("continent"),
        fifa_code=t.get("fifa_code"),
        confed=t.get("confed"),
    )
    db.add(team)
    db.flush()
    team_by_name[t["name"]] = team

db.commit()
print(f"  {len(team_by_name)} teams inserted.")

# ── Matches ───────────────────────────────────────────────────────────────────
print("Seeding matches…")
with open(MATCHES_JSON, encoding="utf-8") as f:
    wc_data = json.load(f)

matches_inserted = 0
for m in wc_data["matches"]:
    round_name = m["round"]
    stage = get_stage(round_name)
    dt_utc = parse_match_datetime(m["date"], m["time"])

    t1_label = m["team1"]
    t2_label = m["team2"]

    # Resolve to team IDs only for group stage matches with known teams
    t1_id = team_by_name[t1_label].id if t1_label in team_by_name else None
    t2_id = team_by_name[t2_label].id if t2_label in team_by_name else None

    match = Match(
        match_num=m.get("num"),
        stage=stage,
        round_name=round_name,
        group_name=m.get("group"),
        match_date=dt_utc,
        team_home_id=t1_id,
        team_away_id=t2_id,
        team_home_label=t1_label,
        team_away_label=t2_label,
        ground=m.get("ground"),
        score_home=None,
        score_away=None,
        winner_id=None,
        home_strength_rating=0.5,
    )
    db.add(match)
    matches_inserted += 1

db.commit()
print(f"  {matches_inserted} matches inserted.")

db.close()
print("\nDone!")
print("Admin: admin/admin123  |  superadmin/superadmin123")
print("Users: alice/alice123, bob/bob123, charlie/charlie123, diana/diana123, eve/eve123")
