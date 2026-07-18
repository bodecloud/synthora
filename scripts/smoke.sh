#!/usr/bin/env bash
# Self-host smoke test: validate compose, bring the stack up, probe health,
# and confirm durable checkpointer / alembic wiring.
set -euo pipefail
cd "$(dirname "$0")/.."

# Compose defaults hash embeddings (no Ollama required). Override OPENAI/OLLAMA as needed.
export OPENAI_API_KEY="${OPENAI_API_KEY:-}"
export OLLAMA_BASE_URL="${OLLAMA_BASE_URL:-}"
export SYNTHORA_EMBEDDINGS="${SYNTHORA_EMBEDDINGS:-hash}"

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
for i in $(seq 1 60); do
  if curl -fsS "http://localhost:${SYNTHORA_WEB_PORT:-3000}/" >/dev/null 2>&1; then
    break
  fi
  sleep 2
done
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
    'python -c "import asyncio; from synthora.orchestration.checkpoint import ensure_checkpointer; asyncio.run(ensure_checkpointer()); print(\"async postgres checkpointer ok\")"'
  docker compose exec -T postgres \
    psql -U "${POSTGRES_USER:-synthora}" -d "${POSTGRES_DB:-synthora}" -c '\dt' \
    | tee /tmp/synthora-tables2.txt
  grep -Ei 'checkpoint' /tmp/synthora-tables2.txt >/dev/null
fi

echo "==> live research run (fake LLM + fake search)"
RUN_JSON=$(curl -fsS -X POST "http://localhost:${SYNTHORA_API_PORT:-8000}/api/v1/research" \
  -H 'Content-Type: application/json' \
  -d '{
    "question": "What is compose smoke testing?",
    "pipeline_id": "fast_research",
    "config": {
      "planner_model": "fake:m",
      "researcher_model": "fake:m",
      "compressor_model": "fake:m",
      "writer_model": "fake:m",
      "critic_model": "fake:m",
      "search_engines": ["fake"],
      "search_strategy": "source_based",
      "allow_clarification": false,
      "max_react_tool_calls": 2
    }
  }')
echo "$RUN_JSON"
RUN_ID=$(python3 -c 'import json,sys; print(json.load(sys.stdin)["run_id"])' <<<"$RUN_JSON")
STATUS=""
for i in $(seq 1 90); do
  STATUS=$(curl -fsS "http://localhost:${SYNTHORA_API_PORT:-8000}/api/v1/research/${RUN_ID}" | python3 -c 'import json,sys; print(json.load(sys.stdin)["status"])')
  echo "run status: $STATUS"
  if [[ "$STATUS" == "completed" || "$STATUS" == "failed" || "$STATUS" == "cancelled" ]]; then
    break
  fi
  sleep 2
done
[[ "$STATUS" == "completed" ]] || {
  echo "research run did not complete (status=$STATUS)"
  curl -fsS "http://localhost:${SYNTHORA_API_PORT:-8000}/api/v1/research/${RUN_ID}" || true
  echo
  echo "==> worker logs (tail)"
  docker compose logs --tail=80 worker || true
  echo "==> api logs (tail)"
  docker compose logs --tail=40 api || true
  exit 1
}
REPORT=$(curl -fsS "http://localhost:${SYNTHORA_API_PORT:-8000}/api/v1/research/${RUN_ID}/report")
echo "$REPORT" | python3 -c 'import json,sys; d=json.load(sys.stdin); assert d.get("report_markdown"), d; print("report ok:", d["report_markdown"][:80])'

echo "==> export formats"
curl -fsS "http://localhost:${SYNTHORA_API_PORT:-8000}/api/v1/research/${RUN_ID}/export?format=markdown" | head -c 120
echo
curl -fsS "http://localhost:${SYNTHORA_API_PORT:-8000}/api/v1/research/${RUN_ID}/export?format=html" | head -c 120
echo
PDF_HEAD=$(curl -fsS "http://localhost:${SYNTHORA_API_PORT:-8000}/api/v1/research/${RUN_ID}/export?format=pdf" | head -c 4)
[[ "$PDF_HEAD" == "%PDF" ]] || { echo "pdf export failed: $PDF_HEAD"; exit 1; }
echo "pdf export ok"

echo "==> document upload"
printf 'smoke document library content' >/tmp/synthora-smoke-doc.txt
UPLOAD_CODE=$(curl -sS -o /tmp/synthora-upload.json -w "%{http_code}" -X POST   "http://localhost:${SYNTHORA_API_PORT:-8000}/api/v1/documents/upload"   -F "file=@/tmp/synthora-smoke-doc.txt;filename=smoke.txt"   -F "title=Smoke doc")
if [[ "$UPLOAD_CODE" != "201" ]]; then
  echo "document upload failed: HTTP $UPLOAD_CODE"
  cat /tmp/synthora-upload.json || true
  echo
  docker compose logs --tail=60 api || true
  exit 1
fi
UPLOAD=$(cat /tmp/synthora-upload.json)
echo "$UPLOAD" | python3 -c 'import json,sys; d=json.load(sys.stdin); assert d.get("id"), d; print("upload ok:", d["id"])'

echo "==> MCP REST tools/list"
curl -fsS -X POST "http://localhost:${SYNTHORA_API_PORT:-8000}/api/v1/mcp/tools/list" \
  -H 'Content-Type: application/json' -d '{}' \
  | python3 -c "import json,sys; names={t['name'] for t in json.load(sys.stdin)['tools']}; expected={'start_research','get_run_status','get_report','search_documents'}; assert names==expected, names"

echo "smoke test passed"
