# Synthora

Next-generation deep research platform unifying three lineages:

- **[LangChain Open Deep Research](https://github.com/langchain-ai/open_deep_research)** — the research operating system: LangGraph nested graphs, a supervisor that plans and delegates, parallel researchers, tool loops, context compression.
- **[Stanford STORM / Co-STORM](https://github.com/stanford-oval/storm)** — the intelligence layer: multi-perspective expert personas, simulated collaborative discourse with a moderator surfacing unknown unknowns, hierarchical knowledge maps, outline-first cited writing.
- **[Local Deep Research](https://github.com/LearningCircuit/local-deep-research)** — the platform layer: persistence, sessions, REST + WebSocket APIs, background jobs, pluggable search engines/strategies/LLM providers, self-hosting.

## Research pipelines

| Pipeline | Flow |
|---|---|
| `fast_research` | plan → search → summarize → answer |
| `deep_research` | plan → parallel research → perspectives → discourse → knowledge map → outline → cited sections → criticism → report |
| `academic_research` | literature search → citation verification → outline → synthesis → peer review → bibliography |
| `autonomous_research` | hypothesize → investigate → gap discovery → new research paths → knowledge base update → repeat (bounded) |

## Layout

```
apps/
  api/       FastAPI gateway (REST + WebSocket, optional auth)
  worker/    Queue consumer that executes LangGraph pipelines
  web/       React + Vite UI
packages/
  core/           Domain models, ports, events
  adapters/       LLM providers, search engines, search strategies, MCP bridge
  intelligence/   Perspectives, discourse, knowledge map, outline writer
  orchestration/  LangGraph pipelines + pipeline registry
  persistence/    SQLAlchemy models, repositories, Alembic migrations
  sdk/            Python client
```

## Quickstart (development)

```bash
uv sync                                   # install workspace
uv run pytest                             # run tests
uv run uvicorn synthora.api.main:app --reload --port 8000
uv run python -m synthora.worker.main    # in another shell
```

LangGraph Studio: `uv run langgraph dev` (uses `langgraph.json`).

## Self-hosting

```bash
docker compose up -d
```

Brings up: API (`:8000`), worker, web UI (`:3000`), Postgres, Redis, SearXNG. Optional local LLM:

```bash
docker compose --profile ollama -f docker-compose.yml -f docker-compose.ollama.yml up -d
```

The overlay sets `OLLAMA_BASE_URL=http://ollama:11434` on API/worker. Default embeddings use `SYNTHORA_EMBEDDINGS=hash` (no Ollama required).

Key environment variables (see `.env.example`): `SYNTHORA_DATABASE_URL`, `SYNTHORA_REDIS_URL`, `SYNTHORA_AUTH_MODE` (`none`|`session`), `OPENAI_API_KEY` / `OPENAI_BASE_URL`, `TAVILY_API_KEY`, `SEARXNG_URL`.

## Docs

- [docs/architecture.md](docs/architecture.md) — layer contracts and data flow
- [docs/pipelines.md](docs/pipelines.md) — pipeline graph designs
- [docs/feature-parity.md](docs/feature-parity.md) — parity matrix vs the three source projects
