"""
knockout.py - Resolve knockout-stage brackets from group results and advance winners.
"""

import re
from collections import defaultdict
from sqlalchemy.orm import Session
from models import Match, Team


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


def advance_to_next_round(db: Session, match: Match):
    """
    After a match result is saved:
    - Push winner into next-round match labelled 'W{match_num}'.
    - For semi-finals, also push the loser into the 3rd-place match labelled 'L{match_num}'.
    """
    if not match.match_num or not match.winner_id:
        return

    winner_ref = f"W{match.match_num}"
    loser_ref = f"L{match.match_num}"

    winner = db.query(Team).get(match.winner_id)
    if winner:
        nxt = db.query(Match).filter(
            (Match.team_home_label == winner_ref) | (Match.team_away_label == winner_ref)
        ).first()
        if nxt:
            if nxt.team_home_label == winner_ref:
                nxt.team_home_id = winner.id
                nxt.team_home_label = winner.name
            else:
                nxt.team_away_id = winner.id
                nxt.team_away_label = winner.name

    # Loser slot (only exists for semi-finals → 3rd-place match)
    loser_id = (
        match.team_away_id if match.winner_id == match.team_home_id else match.team_home_id
    )
    if loser_id:
        loser = db.query(Team).get(loser_id)
        if loser:
            third = db.query(Match).filter(
                (Match.team_home_label == loser_ref) | (Match.team_away_label == loser_ref)
            ).first()
            if third:
                if third.team_home_label == loser_ref:
                    third.team_home_id = loser.id
                    third.team_home_label = loser.name
                else:
                    third.team_away_id = loser.id
                    third.team_away_label = loser.name

    db.commit()
