from sqlalchemy.orm import Session
from models import Match, Prediction, User, SpecialEvent, SpecialEventAnswer, ChampionEvent, ChampionBet
from config import STAGE_POINTS, STAR_MULTIPLIER


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

    for pred in predictions:
        star = bool(pred.use_star)
        multiplier = STAR_MULTIPLIER if star else 1

        if effective_winner is None:
            earned = 0  # handicap draw — star has no effect
        elif pred.predicted_winner_id == effective_winner:
            earned = int(base_points * multiplier)
        else:
            earned = -base_points * multiplier  # penalty = same magnitude as reward

        old_points = pred.points_earned or 0
        pred.points_earned = earned

        user = db.query(User).filter(User.id == pred.user_id).first()
        if user:
            user.total_score = (user.total_score or 0) - old_points + earned

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
