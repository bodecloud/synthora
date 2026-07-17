#!/usr/bin/env bash
# Self-host smoke test: validate compose, bring the stack up, probe health,
# and confirm durable checkpointer / alembic wiring.
set -euo pipefail
cd "$(dirname "$0")/.."

echo "==> validating compose file"
docker compose config --quiet

echo "==> building and starting stack"
docker compose up -d --build

cleanup() { docker compose down; }
trap cleanup EXIT

echo "==> waiting for API health"
for i in $(seq 1 90); do
  if curl -fsS "http://localhost:${SYNTHORA_API_PORT:-8000}/health" >/dev/null 2>&1; then
    break
  fi
  sleep 2
done
curl -fsS "http://localhost:${SYNTHORA_API_PORT:-8000}/health"
echo
curl -fsS "http://localhost:${SYNTHORA_API_PORT:-8000}/ready"
echo
curl -fsS "http://localhost:${SYNTHORA_API_PORT:-8000}/api/v1/pipelines"
echo

echo "==> waiting for web UI"
curl -fsS "http://localhost:${SYNTHORA_WEB_PORT:-3000}/" >/dev/null

echo "==> worker heartbeat"
for i in $(seq 1 30); do
  if docker compose exec -T worker test -f /tmp/synthora-worker-heartbeat 2>/dev/null; then
    break
  fi
  sleep 2
done
docker compose exec -T worker test -f /tmp/synthora-worker-heartbeat

echo "==> schema + checkpointer tables"
docker compose exec -T postgres \
  psql -U "${POSTGRES_USER:-synthora}" -d "${POSTGRES_DB:-synthora}" -c '\dt' | tee /tmp/synthora-tables.txt
grep -E 'research_runs|provider_settings|documents' /tmp/synthora-tables.txt >/dev/null

# Prove LangGraph PostgresSaver can talk to Postgres (needs psycopg[binary]
# in slim images). Creates checkpoint_* tables used for interrupt/resume.
if [[ "${SYNTHORA_CHECKPOINT_BACKEND:-postgres}" == "postgres" ]]; then
  echo "==> initializing postgres checkpointer"
  docker compose exec -T worker sh -c \
    'python -c "import os; from langgraph.checkpoint.postgres import PostgresSaver; url=os.environ[\"SYNTHORA_CHECKPOINT_URL\"]; cm=PostgresSaver.from_conn_string(url); s=cm.__enter__(); s.setup(); print(\"postgres checkpointer ok\")"'
  docker compose exec -T postgres \
    psql -U "${POSTGRES_USER:-synthora}" -d "${POSTGRES_DB:-synthora}" -c '\dt' \
    | tee /tmp/synthora-tables2.txt
  grep -Ei 'checkpoint' /tmp/synthora-tables2.txt >/dev/null
fi

echo "smoke test passed"
