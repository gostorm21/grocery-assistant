#!/bin/bash
echo "=== DATABASE_URL set: $([ -n "$DATABASE_URL" ] && echo 'YES' || echo 'NO') ==="
echo "=== URL starts with: ${DATABASE_URL:0:15}... ==="
alembic upgrade head --verbose
echo "=== Migration complete ==="
uvicorn app.main:app --host 0.0.0.0 --port $PORT
