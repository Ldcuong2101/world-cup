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


def parse_api_response(data: dict) -> dict:
    status = data.get("status", "")
    score = data.get("score", {}) or {}
    full_time = score.get("fullTime", {}) or {}
    minute = data.get("minute")
    return {
        "status": status,
        "score_home": full_time.get("home"),
        "score_away": full_time.get("away"),
        "minute": minute,
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
