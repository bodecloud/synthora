# Synthora parity audit checklist

Living checklist against Open Deep Research, STORM/Co-STORM, and Local Deep
Research. Updated on `feat/synthora-full-parity`.

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
| MCP server (outbound tools API) | done |
| News / subscriptions | done |
| Metrics | done |
| Chat / follow-up research | done |

## Security & isolation (verified by `tests/test_isolation.py`)

| Capability | Status |
|---|---|
| Per-user workspaces on register (session auth) | done |
| News list scoped to caller workspace (IDOR fix) | done |
| RAG collection engine scoped to run workspace (contextvar) | done |
| WebSocket auth: token required in session mode, foreign runs rejected | done |
| MCP outbound URL SSRF guard (`SYNTHORA_MCP_ALLOWLIST`) | done |
| Boot refusal on insecure secret key in session mode | done |
| Durable Postgres checkpointer (compose default `postgres`) | done |

## Residual gaps (deliberate, not silent)

None remaining for in-scope functionality. Compose smoke and Playwright
API-mock e2e are verified.

## Explicit non-goals

- Vendoring upstream source trees as disconnected apps
- Per-user SQLCipher (shared Postgres + optional auth by design)
- STORM Streamlit demo
- Paper eval dataset construction pipelines
