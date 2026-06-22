from fastapi import FastAPI, Request, Form, Depends, HTTPException
from fastapi.responses import HTMLResponse, RedirectResponse, JSONResponse
from fastapi.templating import Jinja2Templates
from starlette.middleware.sessions import SessionMiddleware
from sqlalchemy.orm import Session
from sqlalchemy import func
from datetime import datetime, timedelta
from collections import defaultdict

from database import get_db, init_db, SessionLocal
from models import User, Team, Match, Prediction, SpecialEvent, SpecialEventAnswer, Result, Article, MatchArticle, ChampionEvent, ChampionBet, MatchPenalty, UserPeek, Notification
from auth import (
    hash_password, verify_password, create_session_token,
    get_current_user, SESSION_COOKIE,
)
from scoring import compute_match_predictions, compute_special_event, compute_champion_event
from config import STAGE_LABELS, STAGE_ORDER, SECRET_KEY, LIVE_EARLY_MINUTES
from signup import router as signup_router
from crawler import crawl_news_list, crawl_match_article


app = FastAPI()
app.add_middleware(SessionMiddleware, secret_key=SECRET_KEY)
app.include_router(signup_router)
templates = Jinja2Templates(directory="templates")

_UTC7 = timedelta(hours=7)
templates.env.filters["local"] = lambda dt: dt + _UTC7 if dt else dt

def _compute_group_standings(db):
    all_teams = db.query(Team).all()
    standings = defaultdict(dict)
    for team in all_teams:
        if team.group:
            standings[team.group][team.id] = {
                "team": team, "mp": 0, "w": 0, "d": 0, "l": 0, "gf": 0, "ga": 0, "pts": 0,
            }
    for m in db.query(Match).order_by(Match.match_date).all():
        if m.stage != "group" or m.result is None:
            continue
        g = m.team_home.group
        for tid in [m.team_home_id, m.team_away_id]:
            if tid not in standings[g]:
                standings[g][tid] = {
                    "team": (m.team_home if tid == m.team_home_id else m.team_away),
                    "mp": 0, "w": 0, "d": 0, "l": 0, "gf": 0, "ga": 0, "pts": 0,
                }
        standings[g][m.team_home_id]["mp"] += 1
        standings[g][m.team_away_id]["mp"] += 1
        standings[g][m.team_home_id]["gf"] += m.score_home or 0
        standings[g][m.team_home_id]["ga"] += m.score_away or 0
        standings[g][m.team_away_id]["gf"] += m.score_away or 0
        standings[g][m.team_away_id]["ga"] += m.score_home or 0
        if m.winner_id == m.team_home_id:
            standings[g][m.team_home_id]["w"] += 1
            standings[g][m.team_home_id]["pts"] += 3
            standings[g][m.team_away_id]["l"] += 1
        elif m.winner_id == m.team_away_id:
            standings[g][m.team_away_id]["w"] += 1
            standings[g][m.team_away_id]["pts"] += 3
            standings[g][m.team_home_id]["l"] += 1
        else:
            # Draw — 1 point each
            standings[g][m.team_home_id]["d"] += 1
            standings[g][m.team_away_id]["d"] += 1
            standings[g][m.team_home_id]["pts"] += 1
            standings[g][m.team_away_id]["pts"] += 1
    groups_sorted = {}
    for grp, teams_dict in sorted(standings.items()):
        rows = sorted(teams_dict.values(), key=lambda r: (-r["pts"], -(r["gf"] - r["ga"]), -r["gf"]))
        groups_sorted[grp] = rows
    return groups_sorted


def _fmt_rating(val):
    if val is None:
        return ""
    return str(int(val)) if val == int(val) else str(val)
templates.env.filters["fmt_rating"] = _fmt_rating

import json as _json
def _jsattr(val):
    """JSON-encode a value for safe use inside x-data="...". Returns Markup so Jinja2 autoescape won't re-escape the &quot; entities."""
    from markupsafe import Markup
    return Markup(_json.dumps(val).replace('"', '&quot;'))
templates.env.filters["jsattr"] = _jsattr

import re as _re
def _youtube_embed(url):
    """Convert any YouTube URL to an embed URL, or return '' if not parseable."""
    if not url:
        return ''
    m = _re.search(r'youtu\.be/([a-zA-Z0-9_-]+)', url)
    if not m:
        m = _re.search(r'[?&]v=([a-zA-Z0-9_-]+)', url)
    if not m:
        m = _re.search(r'youtube\.com/embed/([a-zA-Z0-9_-]+)', url)
    return f'https://www.youtube.com/embed/{m.group(1)}' if m else ''
templates.env.filters["youtube_embed"] = _youtube_embed

init_db()


def flash(response, message: str, category: str = "info"):
    from urllib.parse import quote, unquote
    response.set_cookie("flash_msg", quote(message, safe=""), max_age=5)
    response.set_cookie("flash_cat", category, max_age=5)


def get_flash(request: Request):
    from urllib.parse import unquote
    raw = request.cookies.get("flash_msg")
    msg = unquote(raw) if raw else None
    cat = request.cookies.get("flash_cat", "info")
    return msg, cat


def redirect(url: str, msg: str = None, cat: str = "info"):
    r = RedirectResponse(url=url, status_code=302)
    if msg:
        flash(r, msg, cat)
    return r


# ─── Auth ────────────────────────────────────────────────────────────────────

@app.get("/login", response_class=HTMLResponse)
async def login_page(request: Request):
    msg, cat = get_flash(request)
    resp = templates.TemplateResponse("login.html", {"request": request, "flash_msg": msg, "flash_cat": cat})
    resp.delete_cookie("flash_msg")
    resp.delete_cookie("flash_cat")
    return resp


@app.post("/login")
async def login_submit(
    request: Request,
    username: str = Form(...),
    password: str = Form(...),
    db: Session = Depends(get_db),
):
    user = db.query(User).filter(User.username == username).first()
    if not user or not verify_password(password, user.password_hash):
        r = RedirectResponse("/login", status_code=302)
        flash(r, "Invalid username or password", "error")
        return r
    token = create_session_token(user.id)
    r = RedirectResponse("/matches", status_code=302)
    r.set_cookie(SESSION_COOKIE, token, httponly=True, max_age=86400 * 7)
    return r


@app.get("/logout")
async def logout():
    r = RedirectResponse("/login", status_code=302)
    r.delete_cookie(SESSION_COOKIE)
    return r


# ─── Matches ─────────────────────────────────────────────────────────────────

@app.get("/matches", response_class=HTMLResponse)
async def matches_page(request: Request, db: Session = Depends(get_db)):
    user = get_current_user(request, db)
    if not user:
        return RedirectResponse("/login", status_code=302)

    all_matches = db.query(Match).order_by(Match.match_date).all()
    now = datetime.utcnow()

    user_preds = {p.match_id: p for p in db.query(Prediction).filter(Prediction.user_id == user.id).all()}

    # Split: upcoming sorted soonest-first, past sorted most-recent-first
    upcoming = sorted([m for m in all_matches if m.match_date > now], key=lambda m: m.match_date)
    past = sorted([m for m in all_matches if m.match_date <= now], key=lambda m: m.match_date, reverse=True)

    # Group each list by calendar date
    def group_by_date(matches):
        grouped = defaultdict(list)
        for m in matches:
            grouped[(m.match_date + _UTC7).date()].append(m)
        return [(d, grouped[d]) for d in sorted(grouped.keys(), key=lambda x: (upcoming[0].match_date + _UTC7).date() if upcoming else x)]

    def group_by_date_sorted(matches, reverse=False):
        grouped = defaultdict(list)
        for m in matches:
            grouped[(m.match_date + _UTC7).date()].append(m)
        dates = sorted(grouped.keys(), reverse=reverse)
        return [(d, grouped[d]) for d in dates]

    upcoming_by_date = group_by_date_sorted(upcoming, reverse=False)
    past_by_date = group_by_date_sorted(past, reverse=True)

    groups_sorted = _compute_group_standings(db)

    peeked_ids = {
        row.match_id
        for row in db.query(UserPeek.match_id).filter(UserPeek.user_id == user.id).all()
    }
    peeks_remaining = max(0, 3 - len(peeked_ids))

    # Consecutive wrong prediction streak
    match_date_map = {m.id: m.match_date for m in all_matches}
    scored_preds = sorted(
        [p for p in user.predictions if p.points_earned is not None and p.match_id in match_date_map],
        key=lambda p: match_date_map[p.match_id]
    )
    wrong_streak = 0
    for pred in reversed(scored_preds):
        if pred.points_earned < 0:
            wrong_streak += 1
        else:
            break

    # Upcoming matches in the next 24 h without a prediction
    cutoff_24h = now + timedelta(hours=24)
    unpredicted_count = sum(1 for m in upcoming if m.id not in user_preds and m.match_date <= cutoff_24h)

    msg, cat = get_flash(request)
    resp = templates.TemplateResponse("matches.html", {
        "request": request,
        "user": user,
        "upcoming_by_date": upcoming_by_date,
        "past_by_date": past_by_date,
        "user_preds": user_preds,
        "now": now,
        "flash_msg": msg,
        "flash_cat": cat,
        "groups_sorted": groups_sorted,
        "STAGE_LABELS": STAGE_LABELS,
        "stars_remaining": user.stars_remaining if user.stars_remaining is not None else 3,
        "peeked_ids": peeked_ids,
        "peeks_remaining": peeks_remaining,
        "wrong_streak": wrong_streak,
        "unpredicted_count": unpredicted_count,
    })
    resp.delete_cookie("flash_msg")
    resp.delete_cookie("flash_cat")
    return resp


# ─── Peek ────────────────────────────────────────────────────────────────────

@app.post("/matches/{match_id}/peek", response_class=JSONResponse)
async def peek_match_picks(match_id: int, request: Request, db: Session = Depends(get_db)):
    user = get_current_user(request, db)
    if not user:
        return JSONResponse({"error": "auth"}, status_code=401)

    existing = db.query(UserPeek).filter(
        UserPeek.user_id == user.id, UserPeek.match_id == match_id
    ).first()

    if not existing:
        used = db.query(UserPeek).filter(UserPeek.user_id == user.id).count()
        if used >= 3:
            return JSONResponse({"error": "no_peeks"})
        db.add(UserPeek(user_id=user.id, match_id=match_id))
        db.commit()

    match = db.query(Match).filter(Match.id == match_id).first()
    if not match:
        return JSONResponse({"error": "not_found"}, status_code=404)

    rows = (
        db.query(Prediction, User)
        .join(User, Prediction.user_id == User.id)
        .filter(Prediction.match_id == match_id)
        .all()
    )
    home_names = [u.username for p, u in rows if p.predicted_winner_id == match.team_home_id]
    away_names = [u.username for p, u in rows if p.predicted_winner_id != match.team_home_id]
    return JSONResponse({"ok": True, "home_names": home_names, "away_names": away_names})


# ─── Predict ─────────────────────────────────────────────────────────────────

@app.get("/predict/{match_id}", response_class=HTMLResponse)
async def predict_page(match_id: int, request: Request, db: Session = Depends(get_db)):
    user = get_current_user(request, db)
    if not user:
        return RedirectResponse("/login", status_code=302)

    match = db.query(Match).filter(Match.id == match_id).first()
    if not match:
        raise HTTPException(status_code=404)

    now = datetime.utcnow()
    _live_statuses = {'IN_PLAY', 'PAUSED', 'EXTRA_TIME', 'PENALTY_SHOOTOUT', 'FINISHED'}
    # is_live: true from LIVE_EARLY_MINUTES before kickoff — controls UI (stream, stats tab default)
    is_live = match.live_status in _live_statuses or (match.match_date - timedelta(minutes=LIVE_EARLY_MINUTES)) <= now
    # can_predict: true until actual kickoff AND match not in progress per API
    can_predict = match.match_date > now and match.live_status not in _live_statuses

    existing = db.query(Prediction).filter(
        Prediction.user_id == user.id,
        Prediction.match_id == match_id
    ).first()

    article = db.query(MatchArticle).filter(MatchArticle.match_id == match_id).first()

    group_key = match.team_home.group if match.team_home else None
    group_rows = None
    if group_key and match.stage == "group":
        groups_sorted = _compute_group_standings(db)
        group_rows = groups_sorted.get(group_key)

    home_picks = db.query(func.count(Prediction.id)).filter(
        Prediction.match_id == match_id,
        Prediction.predicted_winner_id == match.team_home_id,
    ).scalar() or 0
    away_picks = db.query(func.count(Prediction.id)).filter(
        Prediction.match_id == match_id,
        Prediction.predicted_winner_id == match.team_away_id,
    ).scalar() or 0
    total_picks = home_picks + away_picks
    home_pick_pct = round(home_picks / total_picks * 100) if total_picks > 0 else 50
    away_pick_pct = 100 - home_pick_pct

    already_peeked = db.query(UserPeek).filter(
        UserPeek.user_id == user.id, UserPeek.match_id == match_id
    ).first() is not None
    peeks_used = db.query(UserPeek).filter(UserPeek.user_id == user.id).count()
    peeks_remaining = max(0, 3 - peeks_used)

    # When live, expose names for free (no peek quota)
    live_home_names = []
    live_away_names = []
    if is_live and not can_predict:
        rows = (
            db.query(Prediction, User)
            .join(User, Prediction.user_id == User.id)
            .filter(Prediction.match_id == match_id)
            .all()
        )
        live_home_names = [u.username for p, u in rows if p.predicted_winner_id == match.team_home_id]
        live_away_names = [u.username for p, u in rows if p.predicted_winner_id != match.team_home_id]

    return templates.TemplateResponse("predict.html", {
        "request": request,
        "user": user,
        "match": match,
        "existing": existing,
        "now": now,
        "can_predict": can_predict,
        "stars_remaining": user.stars_remaining if user.stars_remaining is not None else 3,
        "article": article,
        "home_picks": home_picks,
        "away_picks": away_picks,
        "total_picks": total_picks,
        "home_pick_pct": home_pick_pct,
        "away_pick_pct": away_pick_pct,
        "group_rows": group_rows,
        "group_key": group_key,
        "is_live": is_live,
        "already_peeked": already_peeked,
        "peeks_remaining": peeks_remaining,
        "live_home_names": live_home_names,
        "live_away_names": live_away_names,
    })


@app.post("/predict/{match_id}")
async def predict_submit(
    match_id: int,
    request: Request,
    predicted_winner_id: int = Form(...),
    use_star: str = Form(default=""),
    db: Session = Depends(get_db),
):
    user = get_current_user(request, db)
    if not user:
        return RedirectResponse("/login", status_code=302)

    match = db.query(Match).filter(Match.id == match_id).first()
    if not match:
        raise HTTPException(status_code=404)

    now = datetime.utcnow()
    _live_statuses = {'IN_PLAY', 'PAUSED', 'EXTRA_TIME', 'PENALTY_SHOOTOUT', 'FINISHED'}
    if match.match_date <= now or match.live_status in _live_statuses:
        return redirect(f"/predict/{match_id}", "Prediction deadline has passed", "error")

    if predicted_winner_id not in [match.team_home_id, match.team_away_id]:
        return redirect(f"/predict/{match_id}", "Invalid team selection", "error")

    want_star = use_star == "on"

    existing = db.query(Prediction).filter(
        Prediction.user_id == user.id,
        Prediction.match_id == match_id
    ).first()

    had_star = bool(existing and existing.use_star)

    # Star budget management
    stars = user.stars_remaining or 0
    if want_star and not had_star:
        if stars <= 0:
            return redirect(f"/predict/{match_id}", "No stars remaining!", "error")
        user.stars_remaining = stars - 1
    elif had_star and not want_star:
        user.stars_remaining = stars + 1  # return the star

    if existing:
        existing.predicted_winner_id = predicted_winner_id
        existing.use_star = want_star
    else:
        db.add(Prediction(
            user_id=user.id,
            match_id=match_id,
            predicted_winner_id=predicted_winner_id,
            use_star=want_star,
        ))

    db.commit()
    msg = "Star Pick saved!" if want_star else "Prediction saved!"
    return redirect("/matches", msg, "success")


# ─── Ranking ─────────────────────────────────────────────────────────────────

@app.get("/ranking", response_class=HTMLResponse)
async def ranking_page(request: Request, db: Session = Depends(get_db)):
    user = get_current_user(request, db)
    if not user:
        return RedirectResponse("/login", status_code=302)

    users = db.query(User).order_by(User.total_score.desc()).all()

    # Count correct predictions per user
    correct_counts = {}
    for u in users:
        correct = sum(
            1 for p in u.predictions
            if p.points_earned is not None and p.points_earned > 0
        )
        correct_counts[u.id] = correct

    # Picks grid: finished matches × users
    finished_matches = (
        db.query(Match)
        .filter(Match.result != None)  # noqa: E711 — SQLAlchemy requires != None
        .order_by(Match.match_date)
        .all()
    )
    finished_ids = [m.id for m in finished_matches]
    all_preds = (
        db.query(Prediction).filter(Prediction.match_id.in_(finished_ids)).all()
        if finished_ids else []
    )
    pick_grid = {}   # {user_id: {match_id: Prediction}}
    for p in all_preds:
        pick_grid.setdefault(p.user_id, {})[p.match_id] = p

    all_penalties = (
        db.query(MatchPenalty).filter(MatchPenalty.match_id.in_(finished_ids)).all()
        if finished_ids else []
    )
    penalty_grid = {}  # {user_id: {match_id: points_earned}}
    for pen in all_penalties:
        penalty_grid.setdefault(pen.user_id, {})[pen.match_id] = pen.points_earned

    # Compute achievement badges per user
    match_date_lookup = {m.id: m.match_date for m in finished_matches}
    badges = {}
    for u in users:
        correct = correct_counts[u.id]
        scored_preds = sorted(
            [p for p in u.predictions if p.points_earned is not None and p.match_id in match_date_lookup],
            key=lambda p: match_date_lookup[p.match_id]
        )
        user_badges = []
        last4 = scored_preds[-4:]
        last10 = scored_preds[-10:]
        if len(last10) == 10 and all(p.points_earned >= 0 for p in last10):
            user_badges.append(("🔮", "Thần Nhãn", "legendary"))
        elif len(last4) == 4 and all(p.points_earned >= 0 for p in last4):
            user_badges.append(("⚡", "Tiên Tri", "positive"))
        if len(last10) == 10 and all(p.points_earned <= 0 for p in last10):
            user_badges.append(("☄️", "Thiên Tai", "doomed"))
        elif len(last4) == 4 and all(p.points_earned <= 0 for p in last4):
            user_badges.append(("💀", "Vận Đen", "negative"))
        badges[u.id] = user_badges

    return templates.TemplateResponse("ranking.html", {
        "request": request,
        "user": user,
        "users": users,
        "correct_counts": correct_counts,
        "finished_matches": finished_matches,
        "pick_grid": pick_grid,
        "penalty_grid": penalty_grid,
        "badges": badges,
    })


# ─── Special Events ──────────────────────────────────────────────────────────

@app.get("/special", response_class=HTMLResponse)
async def special_page(request: Request, db: Session = Depends(get_db)):
    user = get_current_user(request, db)
    if not user:
        return RedirectResponse("/login", status_code=302)

    events = db.query(SpecialEvent).all()
    champion_events = db.query(ChampionEvent).all()
    now = datetime.utcnow()
    user_answers = {a.special_event_id: a for a in db.query(SpecialEventAnswer).filter(
        SpecialEventAnswer.user_id == user.id
    ).all()}
    user_champion_bets = {b.champion_event_id: b for b in db.query(ChampionBet).filter(
        ChampionBet.user_id == user.id
    ).all()}

    msg, cat = get_flash(request)
    resp = templates.TemplateResponse("special.html", {
        "request": request,
        "user": user,
        "events": events,
        "champion_events": champion_events,
        "now": now,
        "user_answers": user_answers,
        "user_champion_bets": user_champion_bets,
        "flash_msg": msg,
        "flash_cat": cat,
    })
    resp.delete_cookie("flash_msg")
    resp.delete_cookie("flash_cat")
    return resp


@app.post("/special/{event_id}/answer")
async def special_answer(
    event_id: int,
    request: Request,
    answer: str = Form(...),
    db: Session = Depends(get_db),
):
    user = get_current_user(request, db)
    if not user:
        return RedirectResponse("/login", status_code=302)

    event = db.query(SpecialEvent).filter(SpecialEvent.id == event_id).first()
    if not event:
        raise HTTPException(status_code=404)

    now = datetime.utcnow()
    if event.deadline <= now:
        return redirect("/special", "Deadline has passed for this event", "error")

    if answer not in event.options:
        return redirect("/special", "Invalid option selected", "error")

    existing = db.query(SpecialEventAnswer).filter(
        SpecialEventAnswer.user_id == user.id,
        SpecialEventAnswer.special_event_id == event_id,
    ).first()

    if existing:
        existing.answer = answer
    else:
        db.add(SpecialEventAnswer(user_id=user.id, special_event_id=event_id, answer=answer))

    db.commit()
    return redirect("/special", "Answer saved!", "success")


@app.post("/champion/{event_id}/bet")
async def champion_bet(
    event_id: int,
    request: Request,
    team_name: str = Form(...),
    bet_amount: int = Form(...),
    db: Session = Depends(get_db),
):
    user = get_current_user(request, db)
    if not user:
        return RedirectResponse("/login", status_code=302)

    event = db.query(ChampionEvent).filter(ChampionEvent.id == event_id).first()
    if not event:
        raise HTTPException(status_code=404)

    now = datetime.utcnow()
    if event.deadline <= now:
        return redirect("/special", "Betting deadline has passed.", "error")

    team_map = {t["name"]: t["rate"] for t in event.teams}
    if team_name not in team_map:
        return redirect("/special", "Invalid team selected.", "error")

    if bet_amount < 1 or bet_amount > 50:
        return redirect("/special", "Bet amount must be between 1 and 50 points.", "error")

    existing = db.query(ChampionBet).filter(
        ChampionBet.user_id == user.id,
        ChampionBet.champion_event_id == event_id,
    ).first()

    if existing:
        user.total_score = (user.total_score or 0) + existing.bet_amount - bet_amount
        existing.team_name = team_name
        existing.bet_amount = bet_amount
        existing.rate = team_map[team_name]
        existing.points_earned = None
    else:
        user.total_score = (user.total_score or 0) - bet_amount
        db.add(ChampionBet(
            user_id=user.id,
            champion_event_id=event_id,
            team_name=team_name,
            bet_amount=bet_amount,
            rate=team_map[team_name],
        ))

    db.commit()
    return redirect("/special", f"Bet placed on {team_name}! {bet_amount} pts wagered.", "success")


# ─── Admin ───────────────────────────────────────────────────────────────────

@app.get("/admin", response_class=HTMLResponse)
async def admin_page(request: Request, db: Session = Depends(get_db)):
    user = get_current_user(request, db)
    if not user:
        return RedirectResponse("/login", status_code=302)
    if not user.is_admin:
        raise HTTPException(status_code=403)

    matches = db.query(Match).order_by(Match.match_date).all()
    events = db.query(SpecialEvent).all()
    champion_events = db.query(ChampionEvent).all()
    teams = db.query(Team).all()
    articles_count = db.query(Article).count()

    now = datetime.utcnow()
    msg, cat = get_flash(request)
    resp = templates.TemplateResponse("admin.html", {
        "request": request,
        "user": user,
        "matches": matches,
        "events": events,
        "champion_events": champion_events,
        "teams": teams,
        "articles_count": articles_count,
        "flash_msg": msg,
        "flash_cat": cat,
        "STAGE_LABELS": STAGE_LABELS,
        "now": now,
    })
    resp.delete_cookie("flash_msg")
    resp.delete_cookie("flash_cat")
    return resp


@app.post("/admin/match/{match_id}/time")
async def admin_set_time(
    match_id: int,
    request: Request,
    match_date: str = Form(...),
    db: Session = Depends(get_db),
):
    user = get_current_user(request, db)
    if not user or not user.is_admin:
        raise HTTPException(status_code=403)

    match = db.query(Match).filter(Match.id == match_id).first()
    if not match:
        raise HTTPException(status_code=404)

    try:
        dt_local = datetime.fromisoformat(match_date)
        match.match_date = dt_local - timedelta(hours=7)
    except ValueError:
        return redirect("/admin", "Invalid date format", "error")

    db.commit()
    return redirect("/admin", "Match time updated!", "success")


@app.post("/admin/match/{match_id}/prematch")
async def admin_set_prematch(
    match_id: int,
    request: Request,
    rating_home: str = Form(default=""),
    rating_away: str = Form(default=""),
    home_strength_rating: str = Form(default=""),
    db: Session = Depends(get_db),
):
    user = get_current_user(request, db)
    if not user or not user.is_admin:
        raise HTTPException(status_code=403)

    match = db.query(Match).filter(Match.id == match_id).first()
    if not match:
        raise HTTPException(status_code=404)

    try:
        if rating_home.strip():
            match.rating_home = float(rating_home)
        if rating_away.strip():
            match.rating_away = float(rating_away)
    except ValueError:
        return redirect("/admin", "Rating must be a number (e.g. 1.5 and 0)", "error")

    try:
        if home_strength_rating.strip():
            match.home_strength_rating = float(home_strength_rating) / 100.0
    except ValueError:
        pass

    db.commit()
    return redirect("/admin", "Pre-match settings saved!", "success")


@app.post("/admin/match/{match_id}/media")
async def admin_set_media(
    match_id: int,
    request: Request,
    youtube_url: str = Form(default=""),
    players_note: str = Form(default=""),
    preview_text: str = Form(default=""),
    db: Session = Depends(get_db),
):
    user = get_current_user(request, db)
    if not user or not user.is_admin:
        raise HTTPException(status_code=403)

    match = db.query(Match).filter(Match.id == match_id).first()
    if not match:
        raise HTTPException(status_code=404)

    match.youtube_url  = youtube_url.strip() or None
    match.players_note = players_note.strip() or None
    match.preview_text = preview_text.strip() or None

    db.commit()
    return redirect("/admin", "Pre-match media saved!", "success")


@app.post("/admin/match/{match_id}/rating")
async def admin_set_rating(
    match_id: int,
    request: Request,
    rating_home: str = Form(default=""),
    rating_away: str = Form(default=""),
    db: Session = Depends(get_db),
):
    """Legacy endpoint kept for compatibility."""
    user = get_current_user(request, db)
    if not user or not user.is_admin:
        raise HTTPException(status_code=403)

    try:
        rh, ra = float(rating_home), float(rating_away)
    except (ValueError, TypeError):
        return redirect("/admin", "Rating must be a number (e.g. 1.5 and 0)", "error")

    match = db.query(Match).filter(Match.id == match_id).first()
    if not match:
        raise HTTPException(status_code=404)

    match.rating_home, match.rating_away = rh, ra
    db.commit()
    return redirect("/admin", "Rating saved!", "success")


@app.post("/admin/match/{match_id}/result")
async def admin_set_result(
    match_id: int,
    request: Request,
    score_home: str = Form(default=""),
    score_away: str = Form(default=""),
    is_extra_time: str = Form(default=None),
    is_penalties: str = Form(default=None),
    score_home_et: str = Form(default=""),
    score_away_et: str = Form(default=""),
    score_home_pen: str = Form(default=""),
    score_away_pen: str = Form(default=""),
    db: Session = Depends(get_db),
):
    user = get_current_user(request, db)
    if not user or not user.is_admin:
        raise HTTPException(status_code=403)

    match = db.query(Match).filter(Match.id == match_id).first()
    if not match:
        raise HTTPException(status_code=404)

    def safe_int(s):
        try: return int(s) if s and s.strip() else None
        except ValueError: return None

    if not (score_home.strip() and score_away.strip()):
        return redirect("/admin", "Both scores are required", "error")

    sh = safe_int(score_home)
    sa = safe_int(score_away)
    if sh is None or sa is None:
        return redirect("/admin", "Invalid score values", "error")

    et = is_extra_time == "on"
    pen = is_penalties == "on"

    # winner_id = actual match winner (for display/bracket)
    # score_home/score_away always stores 90-min score (used for handicap prediction scoring)
    if pen:
        sph = safe_int(score_home_pen) or 0
        spa = safe_int(score_away_pen) or 0
        winner_id = match.team_home_id if sph > spa else match.team_away_id
    elif et:
        she = safe_int(score_home_et) if score_home_et.strip() else sh
        sae = safe_int(score_away_et) if score_away_et.strip() else sa
        if she is not None and sae is not None and she > sae:
            winner_id = match.team_home_id
        elif she is not None and sae is not None and sae > she:
            winner_id = match.team_away_id
        else:
            winner_id = None
    elif sh > sa:
        winner_id = match.team_home_id
    elif sa > sh:
        winner_id = match.team_away_id
    else:
        winner_id = None  # group-stage draw

    match.score_home = sh
    match.score_away = sa
    match.winner_id = winner_id

    result_data = dict(
        score_home=sh, score_away=sa, winner_id=winner_id,
        is_extra_time=et, is_penalties=pen,
        score_home_et=safe_int(score_home_et) if et else None,
        score_away_et=safe_int(score_away_et) if et else None,
        score_home_pen=safe_int(score_home_pen) if pen else None,
        score_away_pen=safe_int(score_away_pen) if pen else None,
    )
    existing = db.query(Result).filter(Result.match_id == match_id).first()
    if existing:
        for k, v in result_data.items():
            setattr(existing, k, v)
    else:
        db.add(Result(match_id=match_id, **result_data))

    db.commit()
    compute_match_predictions(db, match)
    return redirect("/admin", "Result saved and scores updated!", "success")


@app.post("/admin/match/{match_id}/highlight")
async def admin_set_highlight(
    match_id: int,
    request: Request,
    highlight_url: str = Form(default=""),
    match_summary: str = Form(default=""),
    db: Session = Depends(get_db),
):
    user = get_current_user(request, db)
    if not user or not user.is_admin:
        raise HTTPException(status_code=403)

    match = db.query(Match).filter(Match.id == match_id).first()
    if not match:
        raise HTTPException(status_code=404)

    match.highlight_url = highlight_url.strip() or None
    match.match_summary = match_summary.strip() or None

    db.commit()
    return redirect("/admin", "Highlight info saved!", "success")


@app.post("/admin/special/{event_id}/answer")
async def admin_set_special_answer(
    event_id: int,
    request: Request,
    correct_answer: str = Form(...),
    db: Session = Depends(get_db),
):
    user = get_current_user(request, db)
    if not user or not user.is_admin:
        raise HTTPException(status_code=403)

    event = db.query(SpecialEvent).filter(SpecialEvent.id == event_id).first()
    if not event:
        raise HTTPException(status_code=404)

    event.correct_answer = correct_answer
    db.commit()
    compute_special_event(db, event)
    return redirect("/admin", "Special event answer set and points awarded!", "success")


@app.post("/admin/special/create")
async def admin_create_special(
    request: Request,
    title: str = Form(...),
    description: str = Form(""),
    deadline: str = Form(...),
    options: str = Form(...),
    db: Session = Depends(get_db),
):
    user = get_current_user(request, db)
    if not user or not user.is_admin:
        raise HTTPException(status_code=403)

    try:
        dl = datetime.fromisoformat(deadline)
    except ValueError:
        return redirect("/admin", "Invalid deadline format", "error")

    opts = [o.strip() for o in options.split(",") if o.strip()]
    if len(opts) < 2:
        return redirect("/admin", "Provide at least 2 options separated by commas", "error")

    db.add(SpecialEvent(title=title, description=description, deadline=dl, options=opts))
    db.commit()
    return redirect("/admin", "Special event created!", "success")


@app.post("/admin/champion/create")
async def admin_create_champion(
    request: Request,
    title: str = Form(...),
    description: str = Form(""),
    deadline: str = Form(...),
    teams_json: str = Form(...),
    db: Session = Depends(get_db),
):
    user = get_current_user(request, db)
    if not user or not user.is_admin:
        raise HTTPException(status_code=403)

    try:
        dl = datetime.fromisoformat(deadline)
    except ValueError:
        return redirect("/admin", "Invalid deadline format", "error")

    try:
        teams = _json.loads(teams_json)
    except Exception:
        return redirect("/admin", "Invalid teams data", "error")

    teams = [t for t in teams if t.get("name", "").strip() and t.get("rate")]
    if len(teams) < 2:
        return redirect("/admin", "Provide at least 2 teams with rates", "error")

    flag_map = {tm.name: tm.flag_emoji for tm in db.query(Team).all()}
    for t in teams:
        t["name"] = t["name"].strip()
        t["rate"] = float(t["rate"])
        t["flag"] = flag_map.get(t["name"], "")

    db.add(ChampionEvent(title=title, description=description, deadline=dl, teams=teams))
    db.commit()
    return redirect("/admin", "Champion event created!", "success")


@app.post("/admin/champion/{event_id}/winner")
async def admin_set_champion_winner(
    event_id: int,
    request: Request,
    winner: str = Form(...),
    db: Session = Depends(get_db),
):
    user = get_current_user(request, db)
    if not user or not user.is_admin:
        raise HTTPException(status_code=403)

    event = db.query(ChampionEvent).filter(ChampionEvent.id == event_id).first()
    if not event:
        raise HTTPException(status_code=404)

    event.winner = winner
    db.commit()
    compute_champion_event(db, event)
    return redirect("/admin", f"Champion set to {winner} — points awarded!", "success")


# ─── News ─────────────────────────────────────────────────────────────────────

@app.get("/news", response_class=HTMLResponse)
async def news_page(request: Request, db: Session = Depends(get_db)):
    user = get_current_user(request, db)
    if not user:
        return RedirectResponse("/login", status_code=302)

    page = max(1, int(request.query_params.get("page", 1)))
    per_page = 12
    total = db.query(Article).count()
    total_pages = max(1, (total + per_page - 1) // per_page)
    page = min(page, total_pages)

    articles = (
        db.query(Article)
        .order_by(Article.crawled_at.desc())
        .offset((page - 1) * per_page)
        .limit(per_page)
        .all()
    )
    msg, cat = get_flash(request)
    resp = templates.TemplateResponse("news.html", {
        "request": request,
        "user": user,
        "articles": articles,
        "page": page,
        "total_pages": total_pages,
        "total": total,
        "flash_msg": msg,
        "flash_cat": cat,
    })
    resp.delete_cookie("flash_msg")
    resp.delete_cookie("flash_cat")
    return resp


@app.post("/admin/news/crawl")
async def admin_crawl_news(request: Request, db: Session = Depends(get_db)):
    user = get_current_user(request, db)
    if not user or not user.is_admin:
        raise HTTPException(status_code=403)

    items = await crawl_news_list()
    new_count = 0
    for item in items:
        existing = db.query(Article).filter(Article.source_url == item["source_url"]).first()
        if existing:
            for k, v in item.items():
                setattr(existing, k, v)
        else:
            db.add(Article(**item))
            new_count += 1
    db.commit()
    return redirect("/admin", f"Đã cập nhật {len(items)} bài viết ({new_count} mới)", "success")


@app.post("/admin/match/{match_id}/nhandinh")
async def admin_set_nhandinh(
    match_id: int,
    request: Request,
    nhandinh_url: str = Form(...),
    db: Session = Depends(get_db),
):
    user = get_current_user(request, db)
    if not user or not user.is_admin:
        raise HTTPException(status_code=403)

    match = db.query(Match).filter(Match.id == match_id).first()
    if not match:
        raise HTTPException(status_code=404)

    result = await crawl_match_article(nhandinh_url)
    if "error" in result:
        return redirect("/admin", f"Lỗi crawl: {result['error']}", "error")

    existing = db.query(MatchArticle).filter(MatchArticle.match_id == match_id).first()
    if existing:
        existing.source_url = result["source_url"]
        existing.title = result["title"]
        existing.content_html = result["content_html"]
        existing.crawled_at = result["crawled_at"]
    else:
        db.add(MatchArticle(match_id=match_id, **result))
    db.commit()
    return redirect("/admin", "Preview article saved!", "success")


@app.post("/admin/match/{match_id}/nhandinh/delete")
async def admin_delete_nhandinh(
    match_id: int,
    request: Request,
    db: Session = Depends(get_db),
):
    user = get_current_user(request, db)
    if not user or not user.is_admin:
        raise HTTPException(status_code=403)

    article = db.query(MatchArticle).filter(MatchArticle.match_id == match_id).first()
    if article:
        db.delete(article)
        db.commit()
    return redirect("/admin", "Preview article deleted.", "success")


@app.get("/rules", response_class=HTMLResponse)
async def rules_page(request: Request, db: Session = Depends(get_db)):
    user = get_current_user(request, db)
    if not user:
        return RedirectResponse("/login", status_code=302)
    return templates.TemplateResponse("rules.html", {"request": request, "user": user})


@app.get("/", response_class=HTMLResponse)
async def index(request: Request):
    return RedirectResponse("/matches", status_code=302)


# ─── Profile ─────────────────────────────────────────────────────────────────

_USERNAME_RE = _re.compile(r"^[a-zA-Z0-9_]{3,20}$")

@app.get("/profile", response_class=HTMLResponse)
async def profile_page(request: Request, db: Session = Depends(get_db)):
    user = get_current_user(request, db)
    if not user:
        return RedirectResponse("/login", status_code=302)
    return templates.TemplateResponse("profile.html", {
        "request": request, "user": user,
        "username_errors": {}, "password_errors": {},
    })


@app.post("/profile/username")
async def change_username(
    request: Request,
    new_username: str = Form(...),
    password: str = Form(...),
    db: Session = Depends(get_db),
):
    user = get_current_user(request, db)
    if not user:
        return RedirectResponse("/login", status_code=302)

    new_username = new_username.strip()
    errors: dict = {}

    if not _USERNAME_RE.match(new_username):
        errors["new_username"] = "3–20 chars: letters, numbers, underscore only"
    elif new_username == user.username:
        errors["new_username"] = "That's already your username"
    elif db.query(User).filter(User.username == new_username).first():
        errors["new_username"] = "Username is already taken"

    if not errors and not verify_password(password, user.password_hash):
        errors["password"] = "Incorrect password"

    if errors:
        return templates.TemplateResponse("profile.html", {
            "request": request, "user": user,
            "username_errors": errors, "password_errors": {},
        }, status_code=422)

    user.username = new_username
    db.commit()
    return redirect("/profile", "Username updated successfully!", "success")


@app.post("/profile/password")
async def change_password(
    request: Request,
    current_password: str = Form(...),
    new_password: str = Form(...),
    confirm_password: str = Form(...),
    db: Session = Depends(get_db),
):
    user = get_current_user(request, db)
    if not user:
        return RedirectResponse("/login", status_code=302)

    errors: dict = {}

    if not verify_password(current_password, user.password_hash):
        errors["current_password"] = "Incorrect current password"
    if len(new_password) < 8:
        errors["new_password"] = "Password must be at least 8 characters"
    elif new_password == current_password:
        errors["new_password"] = "New password must differ from current"
    if new_password != confirm_password:
        errors["confirm_password"] = "Passwords do not match"

    if errors:
        return templates.TemplateResponse("profile.html", {
            "request": request, "user": user,
            "username_errors": {}, "password_errors": errors,
        }, status_code=422)

    user.password_hash = hash_password(new_password)
    db.commit()
    return redirect("/profile", "Password updated successfully!", "success")


# ─── Notifications ────────────────────────────────────────────────────────────

@app.get("/api/notifications")
async def get_notifications(request: Request, db: Session = Depends(get_db)):
    user = get_current_user(request, db)
    if not user:
        return JSONResponse([])
    notes = db.query(Notification).filter(
        Notification.user_id == user.id,
        Notification.is_read == False,
    ).order_by(Notification.id).all()
    return JSONResponse([
        {"id": n.id, "message": n.message, "emoji": n.emoji}
        for n in notes
    ])


@app.post("/api/notifications/read")
async def mark_notifications_read(request: Request, db: Session = Depends(get_db)):
    user = get_current_user(request, db)
    if not user:
        return JSONResponse({"ok": False})
    db.query(Notification).filter(
        Notification.user_id == user.id,
        Notification.is_read == False,
    ).update({"is_read": True})
    db.commit()
    return JSONResponse({"ok": True})
