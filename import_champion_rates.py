"""
Import champion betting event from metadata/champion_rates.json into the database.

Usage:
    python3 import_champion_rates.py

The script creates a single ChampionEvent with:
  - All 48 teams and their rates from champion_rates.json
  - Flag emojis looked up from the teams table
  - Deadline set to the start of the first World Cup match (edit below if needed)

Run once. Re-running will add a duplicate event, so delete the old one first if needed.
"""

import json
from datetime import datetime
from database import SessionLocal, init_db
from models import Team, ChampionEvent

RATES_FILE = "metadata/champion_rates.json"

EVENT_TITLE = "World Cup 2026 Champion"
EVENT_DESCRIPTION = "Who will lift the trophy? Bet your points — multiply up to ×3001 if you pick right."
# First WC 2026 match kick-off (UTC). Adjust if needed.
DEADLINE = datetime(2026, 6, 11, 20, 0, 0)


def main():
    init_db()
    db = SessionLocal()

    with open(RATES_FILE, encoding="utf-8") as f:
        rates = json.load(f)

    flag_map = {t.name: t.flag_emoji for t in db.query(Team).all()}

    missing = [r["team"] for r in rates if r["team"] not in flag_map]
    if missing:
        print(f"WARNING: {len(missing)} team(s) not found in DB and will be skipped:")
        for name in missing:
            print(f"  - {name}")

    teams = []
    for r in rates:
        name = r["team"]
        if name not in flag_map:
            continue
        teams.append({
            "name": name,
            "rate": float(r["rate"]),
            "flag": flag_map[name],
        })

    event = ChampionEvent(
        title=EVENT_TITLE,
        description=EVENT_DESCRIPTION,
        deadline=DEADLINE,
        teams=teams,
    )
    db.add(event)
    db.commit()
    db.refresh(event)

    print(f"Created ChampionEvent id={event.id} with {len(teams)} teams.")
    print(f"  Title    : {event.title}")
    print(f"  Deadline : {DEADLINE} UTC  ({DEADLINE.strftime('%d/%m/%Y %H:%M')} UTC)")
    print(f"  Teams    : {len(teams)}")
    db.close()


if __name__ == "__main__":
    main()
