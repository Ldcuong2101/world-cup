#!/bin/sh
set -e

if [ ! -f /app/worldcup.db ]; then
  echo "No database found — running seed..."
  python seed_from_json.py
else
  echo "Database exists — skipping seed."
fi

exec uvicorn main:app --host 0.0.0.0 --port 8000
