import os
from dotenv import load_dotenv
load_dotenv()

SECRET_KEY = "worldcup-secret-key-change-in-production-2026"
FOOTBALL_DATA_API_KEY = os.environ.get("FOOTBALL_DATA_API_KEY", "")
SESSION_COOKIE = "wc_session"

STAGE_POINTS = {
    "group": 10,
    "r32": 15,
    "r16": 20,
    "r8": 30,
    "r4": 40,
    "semi": 50,
    "final": 70,
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

STAR_COUNT = 3          # stars each user gets for the tournament
STAR_MULTIPLIER = 2     # star doubles both reward and penalty
