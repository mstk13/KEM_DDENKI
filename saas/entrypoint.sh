#!/bin/sh
set -e

echo "=== Running migrations ==="
python manage.py migrate --no-input

echo "=== Seeding data ==="
python manage.py seed 2>/dev/null || true

echo "=== Collecting static files ==="
python manage.py collectstatic --no-input 2>/dev/null || true

echo "=== Starting server ==="
exec "$@"
