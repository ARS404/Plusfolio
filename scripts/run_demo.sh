#!/usr/bin/env bash
set -euo pipefail
PLUSFOLIO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$PLUSFOLIO_ROOT"
# This launcher always uses the local SQLite demo, even if the shell has DB settings.
export PLUSFOLIO_DEMO=1
export POSTGRES_HOST=''
if [[ ! -x .venv/bin/python ]]; then
  "${PLUSFOLIO_PYTHON:-python3}" -m venv .venv
fi
.venv/bin/python -m pip install --disable-pip-version-check -r requirements.lock
if [[ ! -d frontend/node_modules || ! -f .local/npm-lock-installed || frontend/package-lock.json -nt .local/npm-lock-installed ]]; then
  (cd frontend && npm ci --no-audit --no-fund)
  mkdir -p .local
  touch .local/npm-lock-installed
fi
(cd frontend && npm run build)
.venv/bin/python backend/manage.py migrate --noinput
.venv/bin/python backend/manage.py seed_demo
if [[ ! -x .local/tools/tectonic || ! -d .local/tectonic-cache ]]; then
  .venv/bin/python scripts/setup_tex.py
fi
printf '\nPlusfolio: http://127.0.0.1:8000\nОстановка: Ctrl+C. Изменения сохраняются в .local/demo.sqlite3.\n\n'
if [[ "${PLUSFOLIO_SEARCH:-1}" == 1 ]]; then
  scripts/run_search.sh &
  PLUSFOLIO_SEARCH_PID=$!
  trap 'kill "$PLUSFOLIO_SEARCH_PID" 2>/dev/null || true' EXIT
  trap 'exit 130' INT
  trap 'exit 143' TERM
  .venv/bin/python backend/manage.py runserver 127.0.0.1:8000 --noreload
else
  exec .venv/bin/python backend/manage.py runserver 127.0.0.1:8000 --noreload
fi
