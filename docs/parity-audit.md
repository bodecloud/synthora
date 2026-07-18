# Synthora parity audit checklist

Living checklist against Open Deep Research, STORM/Co-STORM, and Local Deep
Research. Last verified on `main` after PR #15 (`feat/route-parity-guard`).

## Open Deep Research

| Capability | Status |
|---|---|
| Nested graphs | done |
| Clarify interrupt + resume | done |
| Research brief | done |
| Supervisor + parallel researchers | done |
| Researcher ReAct + compress | done |
| Final report | done |
| Role-split models | done |
| Token-limit retry/truncation | done |
| Page summarization | done |
| MCP tools into researchers | done |
| Native/provider web search coverage | done |
| Studio / langgraph.json | done |

## STORM / Co-STORM

| Capability | Status |
|---|---|
| Perspective discovery | done |
| Perspective-guided questions | done |
| Discourse + moderator unknown-unknowns | done |
| Knowledge map insert/reorganize | done |
| Outline + section write + polish | done |
| PureRAG / warm-start / simulated user | done |
| Wikipedia TOC mining | done |
| Embedding similarity | done |
| Discourse persistence | done |

## Local Deep Research

| Capability | Status |
|---|---|
| Persistence / jobs / WS / auth | done |
| Strategies (5) | done |
| Search engines (catalog) | done |
| LLM providers (catalog) | done |
| Document library + RAG | done |
| Settings persistence | done |
| Export md/html/pdf | done |
| Delete / clear history | done |
| MCP server (inbound agent surface + outbound researcher tools) | done |
| News / subscriptions | done |
| Metrics | done |
| Chat / follow-up research | done |
| Python SDK (sync + async + WebSocket iterators) | done |

## Security & isolation (verified by `tests/test_isolation.py`)

| Capability | Status |
|---|---|
| Per-user workspaces on register (session auth) | done |
| News list scoped to caller workspace (IDOR fix) | done |
| RAG collection engine scoped to run workspace (contextvar) | done |
| WebSocket auth: token required in session mode, foreign runs rejected | done |
| MCP outbound URL SSRF guard (`SYNTHORA_MCP_ALLOWLIST`) | done |
| MCP inbound DNS rebinding protection (optional) | done |
| Boot refusal on insecure secret key in session mode | done |
| Durable Postgres checkpointer (compose default `postgres`) | done |

## Deployment defaults

| Item | Status |
|---|---|
| Compose default embeddings (`SYNTHORA_EMBEDDINGS=hash`) without Ollama profile | done (PR #13) |
| Ollama profile overlay (`docker-compose.ollama.yml` sets service URL) | done (PR #14) |
| Live compose smoke (`scripts/smoke.sh`: research, export, upload, MCP list) | done |
| Route parity CI guard (`tests/test_api_route_parity.py`) | done (PR #15) |
| Playwright UI e2e | API-mocked (CI speed); live-stack browser gate (nightly) |

## Residual gaps (deliberate, not silent)

No in-scope product/API/worker gaps. Inbound MCP exposes four agent tools
(not the full REST catalog) by design. Chat enqueues `fast_research` by design.

## Explicit non-goals

- Vendoring upstream source trees as disconnected apps
- Per-user SQLCipher (shared Postgres + optional auth by design)
- STORM Streamlit demo
- Paper eval dataset construction pipelines
- Full CommonMark/GFM export (Synthora report subset only)
