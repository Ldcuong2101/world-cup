"""
seed_r32.py - Import confirmed 2026 World Cup Round of 32 bracket into DB.

Run once after group stage is complete:
    python seed_r32.py
"""
import sys, os
sys.path.insert(0, os.path.dirname(__file__))

from database import SessionLocal
from models import Match, Team

# Confirmed 2026 FIFA World Cup R32 fixtures (verified against official bracket)
# match_num → (home_team_name, away_team_name)  — names must match teams table
R32_FIXTURES = {
    73: ("South Africa", "Canada"),               # 2A vs 2B
    74: ("Germany",      "Paraguay"),              # 1E vs 3D
    75: ("Netherlands",  "Morocco"),               # 1F vs 2C
    76: ("Brazil",       "Japan"),                 # 1C vs 2F
    77: ("France",       "Sweden"),                # 1I vs 3F
    78: ("Ivory Coast",  "Norway"),                # 2E vs 2I
    79: ("Mexico",       "Ecuador"),               # 1A vs 3E
    80: ("England",      "DR Congo"),              # 1L vs 3K
    81: ("USA",          "Bosnia & Herzegovina"),  # 1D vs 3B
    82: ("Belgium",      "Senegal"),               # 1G vs 3I
    83: ("Portugal",     "Croatia"),               # 2K vs 2L
    84: ("Spain",        "Austria"),               # 1H vs 2J
    85: ("Switzerland",  "Algeria"),               # 1B vs 3J
    86: ("Argentina",    "Cape Verde"),            # 1J vs 2H
    87: ("Colombia",     "Ghana"),                 # 1K vs 3L
    88: ("Australia",    "Egypt"),                 # 2D vs 2G
}

db = SessionLocal()
teams_by_name = {t.name: t for t in db.query(Team).all()}

updated, errors = 0, []

for match_num, (home_name, away_name) in sorted(R32_FIXTURES.items()):
    match = db.query(Match).filter(Match.match_num == match_num).first()
    if not match:
        errors.append(f"Match {match_num} not found in DB")
        continue

    home = teams_by_name.get(home_name)
    away = teams_by_name.get(away_name)

    if not home:
        errors.append(f"Team '{home_name}' not found in teams table (match {match_num})")
    if not away:
        errors.append(f"Team '{away_name}' not found in teams table (match {match_num})")
    if not home or not away:
        continue

    match.team_home_id    = home.id
    match.team_home_label = home.name
    match.team_away_id    = away.id
    match.team_away_label = away.name
    print(f"  [{match_num}] {home.name} vs {away.name}")
    updated += 1

db.commit()
db.close()

print(f"\nDone — {updated}/{len(R32_FIXTURES)} R32 matches updated.")
if errors:
    print("Errors:")
    for e in errors:
        print(f"  ! {e}")
