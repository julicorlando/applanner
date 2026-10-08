#!/bin/sh
set -eu

python manage.py bootstrap_application --lock-timeout "${BOOTSTRAP_LOCK_TIMEOUT:-120}"

exec gunicorn applanner.wsgi:application \
  --bind 0.0.0.0:8000 \
  --workers "${GUNICORN_WORKERS:-3}" \
  --threads "${GUNICORN_THREADS:-2}" \
  --timeout "${GUNICORN_TIMEOUT:-60}" \
  --access-logfile - \
  --error-logfile -
