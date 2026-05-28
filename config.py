SECRET_KEY = "worldcup-secret-key-change-in-production-2026"
SESSION_COOKIE = "wc_session"

STAGE_POINTS = {
    "group": 10,
    "r32": 15,
    "r16": 20,
    "r8": 40,
    "r4": 80,
    "semi": 160,
    "final": 320,
}

STAGE_LABELS = {
    "group": "Group Stage",
    "r32": "Round of 32",
    "r16": "Round of 16",
    "r8": "Quarter-Final",
    "r4": "3rd Place",
    "semi": "Semi-Final",
    "final": "Final",
}

STAGE_ORDER = ["group", "r32", "r16", "r8", "semi", "r4", "final"]

UPSET_BONUS_MULTIPLIER = 1.5
WRONG_GUESS_PENALTY = -5
UNDERDOG_THRESHOLD = 0.45
