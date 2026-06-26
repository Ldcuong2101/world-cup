from sqlalchemy.orm import Session
from models import Match, Prediction, User, SpecialEvent, SpecialEventAnswer, ChampionEvent, ChampionBet, MatchPenalty, Notification
from config import STAGE_POINTS, STAR_MULTIPLIER


def _notify(db: Session, user_id: int, type: str, value: int, message: str, emoji: str) -> None:
    """Create a notification only if one with the same (user, type, value) doesn't already exist."""
    exists = db.query(Notification).filter(
        Notification.user_id == user_id,
        Notification.type == type,
        Notification.value == value,
    ).first()
    if not exists:
        db.add(Notification(user_id=user_id, type=type, value=value, message=message, emoji=emoji))


def _award_streak_bonuses(db: Session) -> None:
    """Award bonus stars when a user hits a new 10-streak milestone (correct or wrong).
    streak_bonus_stars tracks milestones for the current unbroken streak; resets when streak breaks.
    """
    match_dates = {m.id: m.match_date for m in db.query(Match).all()}
    users = db.query(User).filter(User.is_admin == False).all()

    for user in users:
        scored = sorted(
            [p for p in user.predictions if p.points_earned is not None and p.match_id in match_dates],
            key=lambda p: match_dates[p.match_id]
        )
        if not scored:
            if (user.streak_bonus_stars or 0) > 0:
                user.streak_bonus_stars = 0
            continue

        # Determine direction of the last prediction
        last_pts = scored[-1].points_earned
        if last_pts > 0:
            direction = 1
        elif last_pts < 0:
            direction = -1
        else:
            direction = 0  # 0-point result breaks any streak

        streak_len = 0
        if direction != 0:
            for p in reversed(scored):
                if (direction == 1 and p.points_earned > 0) or (direction == -1 and p.points_earned < 0):
                    streak_len += 1
                else:
                    break

        milestones_owed = streak_len // 10
        current = user.streak_bonus_stars or 0

        if milestones_owed > current:
            stars_gained = milestones_owed - current
            user.stars_remaining = (user.stars_remaining or 0) + stars_gained
            user.streak_bonus_stars = milestones_owed
            # Notify for each newly earned star
            for m in range(current + 1, milestones_owed + 1):
                _notify(db, user.id, 'star', m,
                        f"You earned a bonus star! {m * 10} predictions in a row — keep it up!",
                        "⭐")
        elif milestones_owed < current:
            user.streak_bonus_stars = milestones_owed

        # Streak milestone notification (every 10, win or lose)
        if streak_len > 0 and streak_len % 10 == 0:
            if direction == 1:
                msgs = {
                    10: "10 correct in a row! You're on fire 🔥",
                    20: "20 correct picks straight — are you a football oracle?! 🚀",
                    30: "30 correct in a row. Absolutely unreal 🏆",
                }
                msg = msgs.get(streak_len, f"{streak_len} correct in a row — legendary! 🏆")
                _notify(db, user.id, 'streak_win', streak_len, msg, "🔥")
            else:
                msgs = {
                    10: "10 wrong in a row... but you're still here. Respect 😅",
                    20: "20 wrong straight — have you considered coaching instead? 😂",
                    30: "30 wrong in a row. This is historically bad 💀",
                }
                msg = msgs.get(streak_len, f"{streak_len} wrong in a row — history books territory 💀")
                _notify(db, user.id, 'streak_lose', streak_len, msg, "💀")


def _get_effective_winner(match: Match):
    """Winner for scoring purposes after applying handicap rating. None = handicap draw (0 pts)."""
    if match.score_home is None or match.score_away is None:
        return None
    rh = match.rating_home or 0
    ra = match.rating_away or 0
    adj_home = match.score_home + rh
    adj_away = match.score_away + ra
    if adj_home > adj_away:
        return match.team_home_id
    elif adj_away > adj_home:
        return match.team_away_id
    return None  # handicap draw → 0 pts


def compute_match_predictions(db: Session, match: Match) -> None:
    """Recompute points for all predictions on a finished match."""
    if match.score_home is None or match.score_away is None:
        return

    effective_winner = _get_effective_winner(match)
    base_points = STAGE_POINTS.get(match.stage, 10)
    predictions = db.query(Prediction).filter(Prediction.match_id == match.id).all()
    predicted_user_ids = set()

    home_pick_count = sum(1 for p in predictions if p.predicted_winner_id == match.team_home_id)
    away_pick_count = sum(1 for p in predictions if p.predicted_winner_id == match.team_away_id)

    for pred in predictions:
        predicted_user_ids.add(pred.user_id)
        star = bool(pred.use_star)
        multiplier = STAR_MULTIPLIER if star else 1

        if effective_winner is None:
            earned = 0  # handicap draw — star has no effect
        elif pred.predicted_winner_id == effective_winner:
            pick_count = home_pick_count if pred.predicted_winner_id == match.team_home_id else away_pick_count
            if pick_count == 1:
                multiplier *= 2  # lone correct picker gets ×2
            earned = int(base_points * multiplier)
        else:
            earned = -base_points * multiplier  # penalty = same magnitude as reward

        old_points = pred.points_earned or 0
        pred.points_earned = earned

        user = db.query(User).filter(User.id == pred.user_id).first()
        if user:
            user.total_score = (user.total_score or 0) - old_points + earned

    # Apply -half penalty to non-admin users who didn't submit a prediction
    no_pred_penalty = -(base_points // 2)
    all_users = db.query(User).all()
    for user in all_users:
        existing = db.query(MatchPenalty).filter(
            MatchPenalty.user_id == user.id,
            MatchPenalty.match_id == match.id,
        ).first()
        if user.id in predicted_user_ids:
            # Has a real prediction — remove any stale no-prediction penalty
            if existing:
                user.total_score = (user.total_score or 0) - existing.points_earned
                db.delete(existing)
        else:
            old_pts = existing.points_earned if existing else 0
            if existing:
                existing.points_earned = no_pred_penalty
            else:
                db.add(MatchPenalty(user_id=user.id, match_id=match.id, points_earned=no_pred_penalty))
            user.total_score = (user.total_score or 0) - old_pts + no_pred_penalty

    _award_streak_bonuses(db)
    db.commit()


def compute_special_event(db: Session, event: SpecialEvent) -> None:
    """Award points for a special event once correct_answer is set."""
    if not event.correct_answer:
        return

    answers = db.query(SpecialEventAnswer).filter(
        SpecialEventAnswer.special_event_id == event.id
    ).all()

    for ans in answers:
        old_points = ans.points_earned or 0
        earned = 50 if ans.answer == event.correct_answer else 0
        ans.points_earned = earned

        user = db.query(User).filter(User.id == ans.user_id).first()
        if user:
            user.total_score = (user.total_score or 0) - old_points + earned

    db.commit()


def compute_champion_event(db: Session, event: ChampionEvent) -> None:
    """Award winnings for a champion bet event once the winner is set."""
    if not event.winner:
        return

    bets = db.query(ChampionBet).filter(ChampionBet.champion_event_id == event.id).all()

    for bet in bets:
        old_earned = bet.points_earned or 0
        earned = int(bet.bet_amount * bet.rate) if bet.team_name == event.winner else 0
        bet.points_earned = earned

        user = db.query(User).filter(User.id == bet.user_id).first()
        if user:
            user.total_score = (user.total_score or 0) - old_earned + earned

    db.commit()
