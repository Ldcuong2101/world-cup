#!/bin/sh
set -e

mkdir -p /app/data

if [ ! -f /app/data/worldcup.db ]; then
  echo "No database found — running seed..."
  DB_PATH=/app/data/worldcup.db python seed_from_json.py
else
  echo "Database exists — skipping seed."
fi

exec uvicorn main:app --host 0.0.0.0 --port 8000
