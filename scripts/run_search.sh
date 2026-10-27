#!/usr/bin/env bash
set -euo pipefail
PLUSFOLIO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$PLUSFOLIO_ROOT"
mkdir -p .local
if [[ ! -x .local/embedding-venv/bin/python ]]; then
  "${PLUSFOLIO_PYTHON:-python3}" -m venv .local/embedding-venv
fi
if [[ ! -f .local/embedding-dependencies-installed || embeddings/requirements.lock -nt .local/embedding-dependencies-installed ]]; then
  .local/embedding-venv/bin/python -m pip install --disable-pip-version-check -r embeddings/requirements.lock
  touch .local/embedding-dependencies-installed
fi
.local/embedding-venv/bin/python embeddings/download.py
EMBEDDING_THREADS="${EMBEDDING_THREADS:-2}" .local/embedding-venv/bin/python embeddings/server.py &
PLUSFOLIO_MODEL_PID=$!
cleanup(){
  kill "$PLUSFOLIO_MODEL_PID" 2>/dev/null || true
  if [[ -n "${PLUSFOLIO_INDEX_PID:-}" ]]; then kill "$PLUSFOLIO_INDEX_PID" 2>/dev/null || true; fi
}
trap cleanup EXIT
trap 'exit 130' INT
trap 'exit 143' TERM
for attempt in {1..60}; do
  if ! kill -0 "$PLUSFOLIO_MODEL_PID" 2>/dev/null; then exit 1; fi
  if .venv/bin/python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8011/health',timeout=1)" 2>/dev/null; then break; fi
  sleep 1
done
printf 'CPU search ready. Starting resumable index worker. Ctrl+C stops both processes.\n'
.venv/bin/python -u backend/manage.py index_problem_search --watch &
PLUSFOLIO_INDEX_PID=$!
wait "$PLUSFOLIO_INDEX_PID"
