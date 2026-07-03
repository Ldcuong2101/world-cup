"""
knockout.py - Resolve knockout-stage brackets from group results and advance winners.
"""

import json
import os
import re
from collections import defaultdict
from sqlalchemy.orm import Session
from models import Match, Team, Prediction, User, MatchPenalty
from scoring import _award_streak_bonuses


def _compute_group_standings(db):
    all_teams = db.query(Team).all()
    standings = defaultdict(dict)
    for team in all_teams:
        if team.group:
            standings[team.group][team.id] = {
                "team": team, "pts": 0, "w": 0, "d": 0, "l": 0, "gf": 0, "ga": 0, "mp": 0,
            }
    for m in db.query(Match).filter(Match.stage == "group").order_by(Match.match_date).all():
        if m.result is None:
            continue
        if not m.team_home or not m.team_away:
            continue
        g = m.team_home.group
        if not g:
            continue
        for tid in [m.team_home_id, m.team_away_id]:
            if tid not in standings[g]:
                standings[g][tid] = {
                    "team": (m.team_home if tid == m.team_home_id else m.team_away),
                    "pts": 0, "w": 0, "d": 0, "l": 0, "gf": 0, "ga": 0, "mp": 0,
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
            standings[g][m.team_home_id]["d"] += 1
            standings[g][m.team_away_id]["d"] += 1
            standings[g][m.team_home_id]["pts"] += 1
            standings[g][m.team_away_id]["pts"] += 1
    groups_sorted = {}
    for grp, teams_dict in sorted(standings.items()):
        rows = sorted(teams_dict.values(), key=lambda r: (-r["pts"], -(r["gf"] - r["ga"]), -r["gf"]))
        groups_sorted[grp] = rows
    return groups_sorted


def _best_third_place(groups_sorted, count=8):
    """Return {group_letter: Team} for the best `count` third-place finishers."""
    thirds = []
    for grp, rows in groups_sorted.items():
        if len(rows) >= 3:
            thirds.append((grp.replace("Group ", ""), rows[2]))
    thirds.sort(key=lambda x: (-x[1]["pts"], -(x[1]["gf"] - x[1]["ga"]), -x[1]["gf"]))
    return {letter: row["team"] for letter, row in thirds[:count]}


# Official FIFA 2026 third-place bracket assignment tables.
# Key: frozenset of the 8 qualifying group letters.
# Value: {match_num (int) → group_letter} assignment.
# Derived from the confirmed 2026 World Cup bracket.
_FIFA2026_THIRD_PLACE = {
    frozenset("BDEFIJKL"): {74: "D", 77: "F", 79: "E", 80: "K", 81: "B", 82: "I", 85: "J", 87: "L"},
}


def _assign_third_place(slots, qualifying):
    """
    Assign qualifying third-place teams to bracket slots.

    First tries the official FIFA 2026 lookup table (keyed on which 8 groups
    qualified).  Falls back to a backtracking solver for any combination not
    in the table — note the fallback may not match FIFA's tiebreaker ordering.

    slots: list of (frozenset of eligible group letters, match_num)
    qualifying: {group_letter: Team}

    Returns: {match_num: Team}
    """
    q_letters = frozenset(qualifying.keys())

    # Official lookup: table is {match_num: group_letter}
    table = _FIFA2026_THIRD_PLACE.get(q_letters)
    slot_match_nums = {mid for _, mid in slots}
    if table:
        return {
            match_num: qualifying[letter]
            for match_num, letter in table.items()
            if match_num in slot_match_nums and letter in qualifying
        }

    # Fallback: backtracking with MRV (most-constrained slot first)
    candidates = [
        (frozenset(eligible & q_letters), mid)
        for eligible, mid in slots
    ]
    candidates.sort(key=lambda x: len(x[0]))

    def bt(idx, remaining):
        if idx == len(candidates):
            return {}
        eligible, mid = candidates[idx]
        avail = eligible & remaining
        for letter in sorted(avail):
            sub = bt(idx + 1, remaining - {letter})
            if sub is not None:
                return {mid: qualifying[letter], **sub}
        return None

    return bt(0, set(q_letters)) or {}


def resolve_r32_from_group_standings(db: Session):
    """
    Populate R32 match team IDs from completed group stage standings.
    Resolves placeholder labels: '1A'→Group A winner, '2B'→runner-up,
    '3A/B/C/D/F'→best qualifying third-place from those groups.

    Returns (updated_count, warnings_list).
    """
    groups_sorted = _compute_group_standings(db)

    first_place = {}
    second_place = {}
    for grp, rows in groups_sorted.items():
        letter = grp.replace("Group ", "")
        if rows:
            first_place[letter] = rows[0]["team"]
        if len(rows) >= 2:
            second_place[letter] = rows[1]["team"]

    qualifying_thirds = _best_third_place(groups_sorted)

    r32_matches = db.query(Match).filter(Match.stage == "r32").all()

    # Collect third-place slots separately for batch matching
    third_slots = []          # (eligible frozenset, match.id)
    third_slot_info = {}      # match.id → (match, id_attr, label_attr)
    warnings = []
    updated = 0

    for match in r32_matches:
        for id_attr, label_attr in [
            ("team_home_id", "team_home_label"),
            ("team_away_id", "team_away_label"),
        ]:
            label = getattr(match, label_attr) or ""

            m1 = re.match(r'^1([A-L])$', label)
            m2 = re.match(r'^2([A-L])$', label)
            m3 = re.match(r'^3([A-L/]+)$', label)

            if m1:
                team = first_place.get(m1.group(1))
                if team:
                    setattr(match, id_attr, team.id)
                    setattr(match, label_attr, team.name)
                    updated += 1
                else:
                    warnings.append(f"No 1st-place team found for Group {m1.group(1)}")
            elif m2:
                team = second_place.get(m2.group(1))
                if team:
                    setattr(match, id_attr, team.id)
                    setattr(match, label_attr, team.name)
                    updated += 1
                else:
                    warnings.append(f"No 2nd-place team found for Group {m2.group(1)}")
            elif m3:
                eligible = frozenset(m3.group(1).split('/'))
                third_slots.append((eligible, match.id))
                third_slot_info[match.id] = (match, id_attr, label_attr)

    # Batch-assign third-place teams via bipartite matching
    assignment = _assign_third_place(third_slots, qualifying_thirds)
    for match_id, team in assignment.items():
        match, id_attr, label_attr = third_slot_info[match_id]
        setattr(match, id_attr, team.id)
        setattr(match, label_attr, team.name)
        updated += 1

    unresolved = [info for mid, info in third_slot_info.items() if mid not in assignment]
    for match, id_attr, label_attr in unresolved:
        warnings.append(f"Could not assign 3rd-place team for match {match.match_num} slot '{getattr(match, label_attr)}'")

    db.commit()
    return updated, warnings


_BRACKET_JSON_PATH = os.path.join(os.path.dirname(__file__), "metadata", "worldcup.json")

# Mirrors seed_from_json.ROUND_TO_STAGE; kept local to avoid importing seed_from_json
# (which drops/recreates the schema as a module-level side effect).
_ROUND_TO_STAGE = {
    "Round of 32": "r32",
    "Round of 16": "r16",
    "Quarter-final": "r8",
    "Semi-final": "semi",
    "Match for third place": "r4",
    "Final": "final",
}

_reverse_bracket_map = None


def _get_reverse_bracket_map():
    """
    (source match_num, 'W'|'L') -> {stage, match_num, side, label} describing which
    match/slot that winner or loser feeds into, per the static tournament fixture.

    Built from metadata/worldcup.json rather than live Match rows: once a winner is
    pushed forward, advance_to_next_round overwrites the destination's placeholder
    label ("W74") with the resolved team name, so the DB alone can no longer answer
    "where did this match's winner go" for reverting.
    """
    global _reverse_bracket_map
    if _reverse_bracket_map is not None:
        return _reverse_bracket_map

    with open(_BRACKET_JSON_PATH, encoding="utf-8") as f:
        fixtures = json.load(f)["matches"]

    mapping = {}
    for m in fixtures:
        stage = _ROUND_TO_STAGE.get(m["round"])
        if stage is None:
            continue  # group-stage matches are never a W/L destination
        dest_num = m.get("num")  # None for Final / Match for third place
        for side, field in (("home", "team1"), ("away", "team2")):
            ref = m.get(field) or ""
            mo = re.match(r'^([WL])(\d+)$', ref)
            if mo:
                kind, src_num = mo.group(1), int(mo.group(2))
                mapping[(src_num, kind)] = {
                    "stage": stage, "match_num": dest_num, "side": side, "label": ref,
                }
    _reverse_bracket_map = mapping
    return mapping


def revert_match_result(db: Session, match: Match) -> list:
    """
    Undo a saved result: reverses prediction scoring, no-prediction penalties, and
    bracket advancement for this match, restoring it to a not-yet-played state.

    Raises ValueError if a downstream match has already been played off this
    match's winner/loser — that match must be reverted first, since un-advancing
    would rip a team out from under an already-scored result.

    Returns a list of warning strings (e.g. a group-stage caveat about R32).
    """
    if match.result is None and match.winner_id is None and match.score_home is None:
        raise ValueError("This match has no result to revert.")

    bracket_map = _get_reverse_bracket_map()

    winner_id = match.winner_id
    loser_id = None
    if winner_id:
        loser_id = match.team_away_id if winner_id == match.team_home_id else match.team_home_id

    # 1) Resolve downstream slots and refuse if any of them already has a result.
    downstream = []
    if match.match_num:
        for kind, team_id in (("W", winner_id), ("L", loser_id)):
            if not team_id:
                continue
            entry = bracket_map.get((match.match_num, kind))
            if not entry:
                continue
            dest = db.query(Match).filter(
                Match.stage == entry["stage"],
                Match.match_num == entry["match_num"],
            ).first()
            if not dest:
                continue
            if dest.result is not None:
                raise ValueError(
                    f"Cannot revert: match #{dest.match_num or dest.id} ({dest.round_name}) "
                    f"already has a result built on this match's outcome. Revert that match first."
                )
            downstream.append((dest, entry))

    # 2) Reverse prediction scoring.
    for pred in db.query(Prediction).filter(Prediction.match_id == match.id).all():
        old_points = pred.points_earned or 0
        pred.points_earned = None
        user = db.query(User).filter(User.id == pred.user_id).first()
        if user:
            user.total_score = (user.total_score or 0) - old_points

    # 3) Reverse no-prediction penalties.
    for penalty in db.query(MatchPenalty).filter(MatchPenalty.match_id == match.id).all():
        user = db.query(User).filter(User.id == penalty.user_id).first()
        if user:
            user.total_score = (user.total_score or 0) - (penalty.points_earned or 0)
        db.delete(penalty)

    # 4) Undo bracket advancement.
    for dest, entry in downstream:
        if entry["side"] == "home":
            dest.team_home_id = None
            dest.team_home_label = entry["label"]
        else:
            dest.team_away_id = None
            dest.team_away_label = entry["label"]

    # 5) Clear the match's own result.
    if match.result is not None:
        db.delete(match.result)
    match.score_home = None
    match.score_away = None
    match.winner_id = None

    db.commit()

    # Streak bonuses depend on the full ordered prediction history, not just this
    # match, so they're recomputed globally rather than reversed in place.
    _award_streak_bonuses(db)
    db.commit()

    warnings = []
    if match.stage == "group":
        warnings.append(
            "This was a group-stage match — if R32 slots were already resolved from "
            "standings, re-run 'Resolve R32' after fixing the correct result."
        )
    return warnings


def advance_to_next_round(db: Session, match: Match):
    """
    After a match result is saved:
    - Push winner into the next-round match's 'W{match_num}' slot.
    - For semi-finals, also push the loser into the 3rd-place match's 'L{match_num}' slot.

    Destinations are looked up via the static bracket map (keyed on match_num)
    rather than by searching for the placeholder label text — the label gets
    overwritten with the team name on the first advance, so a label-text search
    would silently no-op on a corrected result being re-saved.
    """
    if not match.match_num or not match.winner_id:
        return

    bracket_map = _get_reverse_bracket_map()
    loser_id = (
        match.team_away_id if match.winner_id == match.team_home_id else match.team_home_id
    )

    for kind, team_id in (("W", match.winner_id), ("L", loser_id)):
        if not team_id:
            continue
        entry = bracket_map.get((match.match_num, kind))
        if not entry:
            continue
        dest = db.query(Match).filter(
            Match.stage == entry["stage"],
            Match.match_num == entry["match_num"],
        ).first()
        if not dest:
            continue
        team = db.query(Team).get(team_id)
        if not team:
            continue
        if entry["side"] == "home":
            dest.team_home_id = team.id
            dest.team_home_label = team.name
        else:
            dest.team_away_id = team.id
            dest.team_away_label = team.name

    db.commit()
