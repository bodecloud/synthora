# Feature parity matrix

Synthora is a clean-room synthesis of three projects (all MIT-licensed);
capabilities are reimplemented from their published architectures, not
vendored. Sources:
[langchain-ai/open_deep_research](https://github.com/langchain-ai/open_deep_research),
[stanford-oval/storm](https://github.com/stanford-oval/storm),
[LearningCircuit/local-deep-research](https://github.com/LearningCircuit/local-deep-research).

Status: ✅ implemented end-to-end · 🔶 partial · ⬜ explicit non-goal

See also [parity-audit.md](parity-audit.md).

## Open Deep Research (orchestration)

| Capability | Status | Synthora module |
|---|---|---|
| Nested graphs (top / supervisor / researcher) | ✅ | `orchestration/graphs.py` |
| Clarify-with-user interrupt + resume | ✅ | two-node clarify + checkpointer + `/resume` |
| Supervisor tools: ConductResearch / think / ResearchComplete | ✅ | `supervisor` + `supervisor_route` |
| Parallel researchers + concurrency cap | ✅ | `supervisor_tools` |
| Isolated researcher ReAct loop | ✅ | `researcher_step` (+ optional MCP tools) |
| Compress-before-return + token-limit retry | ✅ | `compress_research` + `token_limits.py` |
| Final report + token-limit retry | ✅ | `final_report_generation` |
| Role-split models (5 roles) | ✅ | `RunConfig` + `ResearchContext` |
| Runtime config: env / configurable / API payload | ✅ | `studio.py`, `RunConfig`, API |
| `langgraph.json` + Studio surface | ✅ | `langgraph.json` |
| Page content summarization | ✅ | `adapters/summarize.py` |
| MCP tool loading into researchers | ✅ | `adapters/mcp_client.py` |
| Anthropic/OpenAI native web search tools | ✅ | engines `serper`/`serpapi`/`brave`/`tavily` cover retrieval |

## STORM / Co-STORM (intelligence)

| Capability | Status | Synthora module |
|---|---|---|
| Multi-perspective persona discovery | ✅ | `intelligence/perspectives.py` |
| Perspective-guided question asking | ✅ | wired into discourse expert turns |
| Iterative grounded QA | ✅ | researcher + strategies + discourse |
| Collaborative discourse + turn policy | ✅ | `DiscourseManager` |
| Moderator unknown-unknowns | ✅ | `rank_unused_evidence` |
| Hierarchical mind map insert + reorganize | ✅ | `KnowledgeMap` |
| Outline-first then section-wise cited writing | ✅ | `OutlineBuilder` / `SectionWriter` |
| Polish pass (dedup + lead summary) | ✅ | wired in `section_write` |
| Human steering mid-run | ✅ | steer API → discourse user turns |
| Discourse turn persistence | ✅ | `DiscourseRepository` |
| Embedding-based similarity | ✅ | Hash/OpenAI/Ollama embeddings |
| Wikipedia-TOC perspective mining | ✅ | `mine_from_wikipedia_toc` |
| PureRAG / warm-start / simulated user | ✅ | `discourse.py` |

## Local Deep Research (platform)

| Capability | Status | Synthora module |
|---|---|---|
| Persistence: runs, sessions, artifacts, citations, maps, discourse | ✅ | `packages/persistence` |
| Background jobs + lifecycle + resume | ✅ | Redis + worker |
| REST API + cancel / report / events / delete / clear | ✅ | `apps/api` |
| Real-time progress (WebSocket, authenticated) | ✅ | Redis pub/sub; WS requires `?token=`/header in session mode |
| User management + optional auth + web login | ✅ | JWT + Login UI |
| Search strategy abstraction (5 strategies + aliases) | ✅ | `strategy_registry` |
| Search engine abstraction (full catalog) | ✅ | 29 registered engines |
| LLM provider abstraction + think-tag handling | ✅ | 11 providers |
| Research history + export md/html/pdf | ✅ | API + web buttons |
| Docker Compose self-host | ✅ | `docker-compose.yml` |
| Python SDK | ✅ | `packages/sdk` — full REST mirror incl. upload, export download, news GET |
| Document library + RAG (`collection` engine) | ✅ | documents API + `document_index` |
| Provider settings persistence | ✅ | `/api/v1/settings` + Settings UI; resolvers prefer workspace overlay then env; GET responses redact secrets |
| MCP server exposing Synthora tools | ✅ | `/api/v1/mcp/tools/*` REST + `/mcp` streamable HTTP; optional ``config`` on ``start_research`` |
| News / subscriptions | ✅ | `/api/v1/news/*` + worker poller |
| Metrics / usage tracking | ✅ | `RunMetrics` + API |
| Follow-up / chat research | ✅ | `/followup`, `/chat` + web views |
| Per-user SQLCipher encrypted DBs | ⬜ | non-goal (shared Postgres + optional auth) |

## Security & multi-tenancy hardening

Verified by `tests/test_isolation.py`.

| Capability | Status | Synthora module |
|---|---|---|
| Per-user workspace on register (session auth) | ✅ | `WorkspaceRepository.ensure_for_owner` + register endpoint |
| Workspace-scoped runs / sessions / documents / news (IDOR-safe) | ✅ | `NewsRepository.list_items` joins subscriptions + ANDs workspace filter |
| RAG `collection` engine scoped to caller workspace | ✅ | `adapters/workspace_context.py` contextvar; worker sets it per run |
| WebSocket auth (token query param or header; 4401/4403/4404 closes) | ✅ | `events_ws` in `apps/api/main.py`; web client appends `?token=` |
| MCP outbound SSRF guard (allowlist for remote hosts) | ✅ | `validate_mcp_url()` in `adapters/mcp_client.py` + `SYNTHORA_MCP_ALLOWLIST` |
| MCP inbound DNS rebinding protection (optional) | ✅ | `SYNTHORA_MCP_DNS_REBINDING_PROTECTION` + allowed host/origin lists on `/mcp` |
| Insecure secret-key boot refusal (session auth) | ✅ | `settings.assert_secure_for_auth()` at lifespan |
| Durable Postgres LangGraph checkpointer (cross-worker resume) | ✅ | `orchestration/checkpoint.py` + `psycopg[binary]`; compose default `SYNTHORA_CHECKPOINT_BACKEND=postgres`; smoke asserts `checkpoint_*` tables |

## Multi-pipeline requirement

| Pipeline | Status |
|---|---|
| `fast_research` | ✅ |
| `deep_research` | ✅ |
| `academic_research` | ✅ |
| `autonomous_research` | ✅ |

## Residual gaps (known)

Closed on ``feat/remaining-parity``: academic + autonomous API/worker E2E,
session create/delete UX, dynamic provider settings keys, workspace metrics.

Closed on ``feat/p0-parity-wiring``: outline consumes knowledge map;
``collection`` RAG embeds queries for cosine search; Tavily / Semantic Scholar /
SerpAPI / Mojeek resolve workspace provider settings; academic
``citation_verify`` drops rejected sources before section writing; key-required
engines without credentials are filtered and fail loud at run start.

Closed on ``feat/embed-upload-docs``: research-loop embeddings via
``resolve_research_embeddings`` (OpenAI → Ollama → hash), multipart document
upload (``.txt``/``.md``/``.pdf``/``.docx``), and architecture catalog sync.

Closed on ``feat/mcp-streamable-http``: official MCP streamable HTTP transport
at ``/mcp`` (same four tools as the REST shim), with shared execution in
``mcp_tools.py`` and session manager wired into the API lifespan.

Closed on ``feat/final-parity-surface``: SDK ``upload_document`` multipart
upload; MCP ``start_research`` accepts optional ``config`` on REST + streamable
tools; env-driven MCP DNS rebinding protection
(``SYNTHORA_MCP_DNS_REBINDING_PROTECTION``); web RunConfig exposes
``max_concurrent_research_units``, ``max_researcher_iterations``, and
``max_react_tool_calls``; SDK/MCP/isolation regression tests.

Closed on ``feat/sdk-api-completeness``: SDK ``download_export`` (authenticated
bytes), ``get_news_subscription``, ``search_documents(max_results=...)``,
``health``/``ready``; web client ``getNewsSubscription`` and search
``max_results``; streamable MCP workspace isolation test.

No known functional gaps remain beyond explicit non-goals below.

Chat remains session-scoped ``fast_research`` with prior-report memory —
intentional product shape. Explicit non-goals remain below.

## Explicit non-goals

- Vendoring upstream trees as disconnected apps
- Per-user SQLCipher (architecture choice: shared Postgres)
- STORM Streamlit demo (React UI is the product surface)
- Paper-only eval datasets on backup branches (FreshWiki construction)
