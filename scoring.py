from sqlalchemy.orm import Session
from models import Match, Prediction, User, SpecialEvent, SpecialEventAnswer
from config import STAGE_POINTS, UPSET_BONUS_MULTIPLIER, WRONG_GUESS_PENALTY, UNDERDOG_THRESHOLD


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
    return None  # handicap draw → no points awarded or deducted


def compute_match_predictions(db: Session, match: Match) -> None:
    """Recompute points for all predictions on a finished match."""
    if match.score_home is None or match.score_away is None:
        return

    effective_winner = _get_effective_winner(match)
    base_points = STAGE_POINTS.get(match.stage, 10)
    predictions = db.query(Prediction).filter(Prediction.match_id == match.id).all()

    for pred in predictions:
        if effective_winner is None:
            earned = 0  # handicap draw
        elif pred.predicted_winner_id == effective_winner:
            earned = int(base_points * UPSET_BONUS_MULTIPLIER) if is_predicted_underdog(match, pred.predicted_winner_id) else base_points
        else:
            earned = WRONG_GUESS_PENALTY

        old_points = pred.points_earned or 0
        pred.points_earned = earned

        user = db.query(User).filter(User.id == pred.user_id).first()
        if user:
            user.total_score = (user.total_score or 0) - old_points + earned

    db.commit()


def is_predicted_underdog(match: Match, predicted_winner_id: int) -> bool:
    """Return True if the predicted winner is the underdog based on home_strength_rating."""
    home_strong = match.home_strength_rating >= (1 - UNDERDOG_THRESHOLD)
    home_weak = match.home_strength_rating <= UNDERDOG_THRESHOLD
    if home_strong and predicted_winner_id == match.team_away_id:
        return True
    if home_weak and predicted_winner_id == match.team_home_id:
        return True
    return False


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
