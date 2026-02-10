#!/bin/bash
set -e

# Run database migrations
alembic upgrade head

# Start the server
uvicorn app.main:app --host 0.0.0.0 --port $PORT
