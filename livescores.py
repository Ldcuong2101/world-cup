import asyncio
import httpx
from datetime import datetime

FD_BASE = "https://api.football-data.org/v4"
POLL_INTERVAL = 60  # seconds between polls


async def fetch_match_from_api(fd_match_id: int, api_key: str) -> dict:
    url = f"{FD_BASE}/matches/{fd_match_id}"
    async with httpx.AsyncClient() as client:
        resp = await client.get(url, headers={"X-Auth-Token": api_key}, timeout=10)
        resp.raise_for_status()
        return resp.json()


def _team_data(raw: dict) -> dict:
    """Extract lineup/bench/formation/coach from a homeTeam or awayTeam object."""
    return {
        "formation": raw.get("formation"),
        "coach": (raw.get("coach") or {}).get("name"),
        "lineup": [
            {
                "name": p.get("name"),
                "position": p.get("position"),
                "number": p.get("shirtNumber"),
            }
            for p in (raw.get("lineup") or [])
        ],
        "bench": [
            {
                "name": p.get("name"),
                "position": p.get("position"),
                "number": p.get("shirtNumber"),
            }
            for p in (raw.get("bench") or [])
        ],
    }


def parse_api_response(data: dict) -> dict:
    status = data.get("status", "")
    score = data.get("score", {}) or {}
    full_time = score.get("fullTime", {}) or {}
    minute = data.get("minute")

    home_raw = data.get("homeTeam") or {}
    away_raw = data.get("awayTeam") or {}
    home_id = home_raw.get("id")
    away_id = away_raw.get("id")

    # Goals
    goals = [
        {
            "minute": g.get("minute"),
            "injury_time": g.get("injuryTime"),
            "type": g.get("type"),          # REGULAR / PENALTY / OWN_GOAL
            "team_id": (g.get("team") or {}).get("id"),
            "scorer": (g.get("scorer") or {}).get("name"),
            "assist": (g.get("assist") or {}).get("name"),
            "score_home": (g.get("score") or {}).get("home"),
            "score_away": (g.get("score") or {}).get("away"),
        }
        for g in (data.get("goals") or [])
    ]

    # Lineups
    home_lineup = _team_data(home_raw)
    away_lineup = _team_data(away_raw)
    lineups = {"home": home_lineup, "away": away_lineup}
    has_lineups = bool(home_lineup["lineup"] or away_lineup["lineup"])

    # Team statistics
    home_stats = home_raw.get("statistics") or {}
    away_stats = away_raw.get("statistics") or {}
    stats = {"home": home_stats, "away": away_stats}
    has_stats = bool(home_stats or away_stats)

    # Bookings + substitutions
    bookings = [
        {
            "minute": b.get("minute"),
            "team_id": (b.get("team") or {}).get("id"),
            "player": (b.get("player") or {}).get("name"),
            "card": b.get("card"),          # YELLOW / RED
        }
        for b in (data.get("bookings") or [])
    ]
    substitutions = [
        {
            "minute": s.get("minute"),
            "team_id": (s.get("team") or {}).get("id"),
            "player_out": (s.get("playerOut") or {}).get("name"),
            "player_in": (s.get("playerIn") or {}).get("name"),
        }
        for s in (data.get("substitutions") or [])
    ]
    events = {"bookings": bookings, "substitutions": substitutions}
    has_events = bool(bookings or substitutions)

    return {
        "status": status,
        "score_home": full_time.get("home"),
        "score_away": full_time.get("away"),
        "minute": minute,
        "score_winner": score.get("winner"),    # "HOME_TEAM" / "AWAY_TEAM" / "DRAW" / None
        "score_duration": score.get("duration"), # "REGULAR" / "EXTRA_TIME" / "PENALTY_SHOOTOUT"
        "home_id": home_id,
        "away_id": away_id,
        "goals": goals or None,
        "lineups": lineups if has_lineups else None,
        "stats": stats if has_stats else None,
        "events": events if has_events else None,
    }


async def refresh_single_match(db, match_id: int, fd_match_id: int, api_key: str) -> dict:
    from models import Match
    data = await fetch_match_from_api(fd_match_id, api_key)
    parsed = parse_api_response(data)

    match = db.query(Match).filter(Match.id == match_id).first()
    if not match:
        return parsed

    if parsed["score_home"] is not None:
        match.score_home = parsed["score_home"]
        match.score_away = parsed["score_away"]
    match.live_status = parsed["status"]
    match.live_minute = parsed["minute"]

    # Auto-set winner when API confirms the match is over.
    # winner_id drives is_done in templates; scoring still requires admin confirmation.
    if parsed["status"] == "FINISHED" and match.winner_id is None:
        api_winner = parsed["score_winner"]
        if api_winner == "HOME_TEAM":
            match.winner_id = match.team_home_id
        elif api_winner == "AWAY_TEAM":
            match.winner_id = match.team_away_id
        # "DRAW" or None: leave winner_id as None (group-stage draw)

    if parsed["goals"] is not None:
        match.goals_data = parsed["goals"]
    if parsed["lineups"] is not None:
        match.lineups_data = parsed["lineups"]
    if parsed["stats"] is not None:
        match.stats_data = parsed["stats"]
    if parsed["events"] is not None:
        match.events_data = parsed["events"]

    db.commit()
    return parsed


async def _poll_once(SessionLocal, api_key: str):
    from models import Match
    db = SessionLocal()
    try:
        now = datetime.utcnow()
        live_matches = (
            db.query(Match)
            .filter(
                Match.match_date <= now,
                Match.winner_id.is_(None),
                Match.fd_match_id.isnot(None),
            )
            .all()
        )
        for match in live_matches:
            try:
                await refresh_single_match(db, match.id, match.fd_match_id, api_key)
                print(f"[livescores] match {match.id} updated")
            except Exception as exc:
                print(f"[livescores] match {match.id} error: {exc}")
    finally:
        db.close()


async def livescore_poll_loop(SessionLocal, api_key: str):
    print("[livescores] background poller started")
    while True:
        await asyncio.sleep(POLL_INTERVAL)
        try:
            await _poll_once(SessionLocal, api_key)
        except Exception as exc:
            print(f"[livescores] poll loop error: {exc}")
