# Preview Portal Closer To Production Parity

Planning note for tightening the on-prem **analyst portal preview** (`scripts/preview_portal_ui.py`) toward production `portal_app` behavior without turning preview into a full host install.

Normative production contract: [`../technical_specs/analyst_portal_case_archive_technical_spec.md`](../technical_specs/analyst_portal_case_archive_technical_spec.md).

Current preview runbook: [`../operations/analyst_portal/ANALYST_PORTAL_PREVIEW.md`](../operations/analyst_portal/ANALYST_PORTAL_PREVIEW.md).

**Status:** Implemented on branch `feature/preview-portal-prod-parity`.

## Goal

Make preview exercise **production portal functionality** (API routes, UI panels, chat behavior, capabilities/readiness contract) using the same `build_portal_app()` code path, while keeping the preview-friendly shortcuts below.

## Accepted Constraints (Locked For This Plan)

| Area | Preview choice |
| --- | --- |
| Chat LLM | **Bedrock Converse** via `config.portal-preview.env` (not local LiteLLM/vLLM) |
| Embeddings / hybrid retrieval | **Foregone** — keep fake embedding stub; no sentence-transformers download, no vector-quality work |
| Auth / front door | **Keep as-is** — Vite dev proxy, optional loopback auth injection, no nginx/TLS/basic auth |
| Case archive storage | **Fake Postgres** in memory — sufficient for cases 1–5 bundles + synthetic list fillers |
| Sample data | **Keep current synthetic layout** — cases 1–5 stored bundles, cases 6–55 list fillers |
| Analyzer pipeline | **Out of scope** — no file-drop ingest, no live `notable-analyzer`, no Splunk/Elastic execution |
| Host install layout | **Repo-local** — `<repo>/.venv`, no `/opt/notable-analyzer` or systemd |
| KB grounding in chat | **Out of scope** — no RAG/KB fixture provider for preview |

## Locked Product Decisions

| Decision | Choice |
| --- | --- |
| Multi-turn chat (P3-1) | **In scope** — follow-up questions must include bounded prior turns in Bedrock synthesis prompts |
| Chat sessions | **In scope** — enable `CASE_QA_CHAT_HISTORY_ENABLED=true` in preview and implement session/message persistence on the fake connection |
| Richer in-memory chunks | **In scope** — derive multiple chunk rows per case from bundle alert/analysis (cases 1–5; minimal chunks for 6–55 OK) |
| Case detail optional tabs (Query Results / ServiceNow) | **Tentative** — static section content in bundles only if needed after chunk/chat work lands |
| Embedding readiness / capabilities semantics | **No change** — keep current preview shortcuts (`chat_llm_gateway_ready` when Bedrock configured) |
| Chat retrieval (item 3) | **Dumb but working** — richer chunks + 1024-dim fake vector stub; return pinned-case chunks without real semantic ranking |

Preview intentionally enables chat history even though production defaults it **off**. That is a dev-demo choice so session UI and multi-turn behavior can be exercised locally.

## Locked Technical Decisions

| # | Topic | Decision |
| --- | --- | --- |
| 1 | Multi-turn Bedrock | **Option B** — add `chat_text_complete(prompt)` hook in production `case_chat` / `portal_app`; preview passes Bedrock transport only; production keeps building prompts (including history) |
| 2 | Fake Postgres | **Merge** preview case/chunk fake DB with test `_HistoryFakeConnection` session/message behavior in one connection object |
| 3 | Chat retrieval | **Dumb retrieval** — use `build_case_chunks()` for richer rows; fake embed stub returns 1024 dims so chat does not error; fake DB returns pinned-case chunks for lexical/vector queries; do not simulate real hybrid search quality |

## What Preview Already Shares With Production

- Same React UI (`frontend/analyst-portal/`) and OpenAPI-shaped routes.
- Same FastAPI app builder (`build_portal_app()`).
- Cases 1–5 use real archive record construction (`build_case_archive_record`, schema validation) from committed bundles.
- Bedrock preview transport reuses production chat prompts (`_build_prompt`, `_build_general_knowledge_prompt`) and post-LLM sanitization path through `answer_case_chat()`.

## In-Scope Gaps To Close

### 1. Multi-turn Bedrock synthesis

Production includes bounded prior turns in the synthesis prompt when chat history is enabled (`_default_synthesize_answer` + `_render_conversation_history`).

Preview today injects custom Bedrock synthesizers that call `_build_prompt(question, sources)` **without** conversation history, so follow-up questions do not behave like production.

**Work:** Add `chat_text_complete` hook; preview stops injecting custom `chat_synthesizer` for Bedrock and passes `bedrock_preview_chat_complete` instead. Production `_default_synthesize_answer` / general-knowledge paths build the full prompt (including history).

### 2. Chat session persistence on fake Postgres

Enable preview config:

- `CASE_QA_CHAT_HISTORY_ENABLED=true`
- production-aligned session limits from `config.portal.env.example` (`CASE_QA_MAX_SESSIONS_PER_USER`, `CASE_QA_MAX_MESSAGES_PER_SESSION`, retention days, etc.)

Adapt test `_HistoryFakeConnection` and merge into preview fake DB (one connection for cases + sessions). Implement chat-history SQL used by:

- `GET /api/chat/sessions`
- `GET /api/chat/sessions/{session_id}/messages`
- `DELETE /api/chat/sessions/{session_id}`
- `DELETE /api/chat/sessions/{session_id}/turns/last`
- `POST /api/chat` session create/append via `persist_chat_history`

This unlocks session sidebar, reload, stop/cancel cleanup, and stale-session recovery in the React UI.

### 3. Production config parity in `_preview_config()`

Mirror production portal defaults from `config.portal.env.example` for limits that affect UI and chat:

- `CASE_QA_MAX_QUESTION_CHARS`, `CASE_QA_MAX_ANSWER_TOKENS`
- `CASE_QA_MAX_CHUNKS_PER_LANE`, `CASE_QA_MAX_TOTAL_CHUNKS`, `CASE_QA_CONTEXT_BUDGET_CHARS`
- `CASE_QA_GENERAL_KNOWLEDGE_ENABLED` (prod default `true`)
- `PORTAL_CHAT_MAX_CONCURRENCY`
- `CASE_RETENTION_DAYS` (surfaced in `/api/capabilities`)

### 4. Richer synthetic chunks (no Splunk)

Cases 1–5 currently index ~one synthetic chunk per case. Production archives many chunks (alert fields + analysis sections).

**Work:** Call production `build_case_chunks(record, config)` and store rows on the fake connection. Pair with a **1024-dim** fake embedding stub (no model download). Fake `case_chunks` queries return pinned-case rows; ranking quality is not a goal.

### 5. Bootstrap / dependency closeout

Install `boto3` (or full package `requirements.txt`) in `scripts/bootstrap_dev_venv.*`. Keep `aws sso login` and model access as operator prereqs.

### 6. Test coverage

Add targeted preview tests:

- Bedrock stubbed → `POST /api/chat` on case-1 returns grounded answer
- Multi-turn: second question prompt includes prior turn text when `session_id` is reused
- Chat session CRUD against fake connection (list, load messages, delete session, delete last turn)
- Richer chunk fixture: retrieval returns multiple sources for a case question

## Tentative (Do After Core Slices)

### Optional case detail UI panels in stored bundles

Cases 1–5 bundles may omit optional analysis sections the UI renders when present:

- `query_result_section` / `query_result_interpretation` (Query Results tab)
- `servicenow_section` (ServiceNow tab)

Add **static** section content to bundles only if chunk/chat parity is done and those tabs are still missing in the UI demo. No live query execution. Cases 6–55 remain minimal.

## Explicitly Out Of Scope

- `notable-analyzer` file-drop pipeline, vLLM, LiteLLM, model weights
- Live Splunk / Elasticsearch / ServiceNow / writeback / SOAR
- Real Postgres, pgvector HNSW, chunk rebuild jobs, retention timer
- nginx TLS, basic auth, production static UI build (Vite dev is fine)
- Per-case RBAC, cross-case chat mode, portal-triggered actions
- Full parity for cases 6–55 detail panels
- Knowledge-base / RAG grounding in chat (`_default_knowledge_base_provider`)
- Real embedding model download or hybrid search quality parity
- Capabilities/readiness redesign (beyond current Bedrock `chat_llm_gateway_ready` shortcut)

## Proposed Work Slices (Implementation Order)

1. **Config alignment** — production portal limits in `_preview_config()`; set `CASE_QA_CHAT_HISTORY_ENABLED=true` for preview.
2. **Richer in-memory chunks** — multi-chunk fake rows for cases 1–5 from bundle content.
3. **Fake chat history store** — session/message tables on `_FakeConnection`; wire all chat-history HTTP routes.
4. **Bedrock via `chat_text_complete`** — production prompt assembly + history; preview Bedrock answers the finished prompt string only.
5. **Bootstrap** — install `boto3` during dev bootstrap.
6. **Tests + doc sync** — preview parity tests; update `ANALYST_PORTAL_PREVIEW.md` and `DEVELOPING.md`.
7. **Tentative: bundle UI sections** — static Query Results / ServiceNow blocks in cases 1–5 if still needed.

## Success Criteria

Preview is "close enough" to production portal when, on cases 1–5 with Bedrock configured:

- All portal API routes used by the React UI behave like production (status codes, payload shapes, capabilities contract).
- Case list/detail/raw-section flows match production rendering for bundled scenarios.
- Chat uses production prompts, sanitization, general-knowledge fallback, **multi-turn synthesis**, and **persisted chat sessions**.
- Chat retrieval returns multiple grounded chunks per case (fake vectors OK).
- No dependency on `/opt/...`, systemd, nginx, real Postgres, local LLM gateway, Splunk, or KB/RAG.
- Bootstrap from a clean repo clone + `config.portal-preview.env` + `aws sso login` is sufficient to demo portal functionality.

## Related Docs

- [`../operations/analyst_portal/ANALYST_PORTAL_OPERATIONS.md`](../operations/analyst_portal/ANALYST_PORTAL_OPERATIONS.md)
- [`../operations/analyst_portal/ANALYST_PORTAL_CHAT_SECURITY.md`](../operations/analyst_portal/ANALYST_PORTAL_CHAT_SECURITY.md)
- [`../../../DEVELOPING.md`](../../../DEVELOPING.md)
- [`../../../PREVIEW_CASE_INVESTIGATION_GUIDE.md`](../../../PREVIEW_CASE_INVESTIGATION_GUIDE.md)
