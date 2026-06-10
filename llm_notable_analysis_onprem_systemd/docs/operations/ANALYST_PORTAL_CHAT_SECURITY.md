# Analyst portal chat — security and execution boundaries

This document describes how **portal case chat** is bounded so the LLM cannot
execute commands, write files, call external systems, or mutate case data — even
when an analyst asks it to run Splunk searches, isolate hosts, or create tickets.

It applies to:

- Production portal (`notable-portal.service`)
- Local preview (`scripts/preview_portal_ui.py`)

It does **not** describe the separate **notable analyzer** pipeline, which can
perform approval-gated Splunk writeback, ServiceNow actions, and read-only query
execution through deterministic code paths outside portal chat.

Related docs:

- [`ANALYST_PORTAL_OPERATIONS.md`](ANALYST_PORTAL_OPERATIONS.md) — portal ops
- [`ANALYST_PORTAL_PREVIEW.md`](ANALYST_PORTAL_PREVIEW.md) — local preview setup
- [`../security/SECURITY_POSTURE.md`](../security/SECURITY_POSTURE.md) — host hardening
- [`../technical_specs/analyst_portal_case_archive_technical_spec.md`](../technical_specs/analyst_portal_case_archive_technical_spec.md) — contracts

## Summary

Portal chat is **text-in / text-out only**. The backend never parses model
output as commands, never invokes tools on the chat path, and never wires
Splunk, ServiceNow, SOAR, EDR, or filesystem operations to chat responses.

The LLM may **draft** SPL, KQL, shell snippets, or hunt ideas for a human analyst
to review and run elsewhere. That text is not executed by this service.

## Threat model (chat scope)

In scope:

- Analyst asks chat to run searches, change tickets, quarantine hosts, or write files
- Prompt injection via archived case text (`alert`, `analysis`, chunks)
- Model claims it already performed an action
- Cross-site browser POST to `/api/chat`
- Oversized or abusive chat payloads

Out of scope for this document:

- Compromise of nginx, Postgres, or the host OS (see `SECURITY_POSTURE.md`)
- Analyzer pipeline actions (writeback, query execution) — separate service and gates
- Analyst copy-pasting draft query text into Splunk or a shell (human action)

## Architecture: no execution hook

Chat request flow:

```text
POST /api/chat
  -> validate payload (mode, question size, session rules)
  -> retrieve archive chunks (read-only SQL)
  -> build bounded prompt
  -> single LLM call (text completion only)
  -> sanitize + post-check answer
  -> JSON response to browser
```

There is **no** agent loop, tool registry, or “run what the model said” step on
this path.

### What the chat path does not include

| Capability | Portal chat |
|------------|-------------|
| Tool / function calling | No — uses `openai_chat_complete` or Bedrock `converse` with one user message |
| Subprocess or shell | No |
| Local filesystem read/write from model output | No |
| Splunk / Elastic / CrowdStrike API calls | No |
| ServiceNow / SOAR / ticket mutations | No |
| Case archive writes from chat | No |
| Notable analyzer writeback | No — different service |

Tool calling exists in **`LocalLLMClient`** (notable **analyzer** structured
output). That code is not invoked by `answer_case_chat()` or `/api/chat`.

Implementation references:

- Chat orchestration: `onprem_service/case_chat.py` — `answer_case_chat()`
- Portal routes: `onprem_service/portal_app.py` — `/api/chat` only for synthesis
- Text-only LLM transport: `onprem_service/openai_transport_nonsdk.py` —
  `openai_chat_complete()` (no `tools` in body)
- Preview Bedrock: `scripts/preview_bedrock_llm.py` — `converse()` text only

## Prompting guardrails

Two synthesis prompts in `case_chat.py`:

### Case-grounded chat (`_build_prompt`)

- Assistant is **read-only**; answers from retrieved `CONTEXT_BLOCK` entries only
- Archive text is labeled **`UNTRUSTED_TEXT_JSON`** — evidence, not instructions
  (prompt-injection mitigation)
- Instructs model that the endpoint **cannot execute** searches, tickets, or host
  actions
- Allows **draft** SPL, SQL, shell, API examples for human review; must not claim
  execution; label drafts as unvalidated guidance
- Output is Markdown only (no structured action schema consumed by code)

### General-knowledge fallback (`_build_general_knowledge_prompt`)

- Used when archive retrieval is empty and `CASE_QA_GENERAL_KNOWLEDGE_ENABLED=true`
- Same non-execution rules for external systems and live telemetry
- Dual-use / offensive requests: model instructed to start with `Refused:` and
  offer defensive alternatives

Preview Bedrock reuses these prompts via `build_preview_bedrock_synthesizers()`.

## Post-LLM output handling (code)

Model text is **never** parsed as SPL to run, paths to open, or tickets to create.

After synthesis, before returning to the UI:

| Step | Module | Purpose |
|------|--------|---------|
| `sanitize_portal_chat_answer()` | `case_chat.py` | Remove citation markers from display text; does not execute fenced code |
| `synthesized_answer_crosses_action_boundary()` | `case_chat.py` | If answer claims the portal ran/created/wrote something, return `answer_status=refused` |
| `_GENERAL_REFUSAL_RE` | `case_chat.py` | Honor model `Refused:` on harmful dual-use general answers |
| Weak retrieval | `case_chat.py` | Return `answer_status=unknown` when archive context is insufficient |

Analyst questions that ask to “run a search” or “create a ticket” are **not**
pre-refused. The model is expected to respond with investigation guidance and
draft query text. Pre-refusal was removed because chat has no integrations to
invoke; refusing the question blocked legitimate analyst workflow.

## HTTP and API boundaries

- **Case data**: list, detail, and raw section routes are GET-only
- **Chat**: `POST /api/chat` returns synthesized text only
- **Optional chat history**: bounded DELETE on session/turn tables when enabled
- **Same-origin check** on browser mutating requests (CSRF-style) — see
  `_same_origin_request()` in `portal_app.py`
- **Proxy secret + trusted user headers** required behind nginx
- **Input bounds**: `CASE_QA_MAX_QUESTION_CHARS`, `CASE_QA_MAX_ANSWER_TOKENS`,
  chat concurrency semaphore

Vite dev preview: proxy must preserve browser `Host` so same-origin checks pass
for chat POSTs (see `ANALYST_PORTAL_PREVIEW.md` troubleshooting).

## Database privileges

Designed separation (see technical spec):

- **`notable_portal` role**: read-only on `notable_cases.cases` and
  `notable_cases.case_chunks`
- **Chat history** (optional): read/write on chat session tables only when
  `CASE_QA_CHAT_HISTORY_ENABLED=true`
- No portal path writes case verdicts, notables, or integration state from LLM output

Preview mode uses an in-memory fake connection — no production Postgres.

## Preview mode

Local preview adds further isolation:

- Cases 1–5: committed stored bundles (no analyzer LLM on page load)
- Cases 6–55: in-memory fillers
- Chat: optional Bedrock / OpenAI / stub — still text-only, same prompts and
  post-checks
- No `config.portal.env` production stack required

Config: `config.portal-preview.env` (gitignored) — chat LLM only.

## Local preview vs production LLM

| Mode | Chat LLM | Can chat execute integrations? |
|------|----------|--------------------------------|
| Production portal | Local LiteLLM / vLLM (loopback) | No |
| Preview + Bedrock | AWS Bedrock Converse | No — only generates text |
| Preview + stub | No external LLM | No |

Bedrock calls leave the host for inference but still return **text only**; the
portal does not act on that text.

## Separation from the analyzer service

The **notable-analyzer** service (file-drop pipeline) is a different process:

- May use tool-style structured LLM output for analysis schemas
- May perform read-only Splunk/Elastic query execution when capability profiles
  and config allow
- May perform Splunk writeback or ServiceNow actions through **deterministic**
  code and approval gates — not through portal chat

Operators should not conflate “LLM in the SOC stack” with “portal chat can take
actions.” Only the analyzer pipeline has those integration adapters, and they
are not exposed on `/api/chat`.

## Known limits (honest boundaries)

What this design **does not** prevent:

- **Human execution**: an analyst can copy draft SPL or shell from chat into
  Splunk or a terminal — that is intentional workflow outside this service
- **Harmful text in answers**: offensive guidance is mitigated by prompts and
  `Refused:` handling, not a deterministic content filter on every token
- **Model provider trust**: Bedrock/OpenAI/local LLM are trusted for availability
  and confidentiality per your deployment agreement; prompts should not send secrets
- **Compromised host**: a rooted host bypasses application boundaries

What it **does** prevent:

- The portal backend treating LLM output as executable code or integration calls
- Silent case or ticket mutation from chat
- Filesystem access driven by chat responses
- Tool loops or autonomous agent behavior on the chat path

## Verification

Manual checks:

1. Ask chat to “run this Splunk search now” — expect draft SPL and guidance, not
   a executed result; `answer_status` should be `answered` (not a hard pre-refusal)
2. Ask chat to “create a ServiceNow ticket” — expect steps/draft text, not ticket ID
3. Inspect `/api/chat` response — answer is Markdown string + `answer_status`; no
   action payload or side-effect fields

Automated tests (repo):

- `tests/onprem_service/test_case_chat.py` — synthesis, refusal of false action
  claims, query authoring
- `tests/onprem_service/test_portal_app.py` — auth, same-origin, chat API

## Related configuration

Portal chat (narrow env file in production):

- [`config.portal.env.example`](../../config.portal.env.example)

Preview chat only:

- [`config.portal-preview.env.example`](../../config.portal-preview.env.example)

Key flags:

- `CASE_QA_ENABLED` — master chat switch
- `CASE_QA_GENERAL_KNOWLEDGE_ENABLED` — allow non-archive technology answers
- `CASE_QA_MAX_QUESTION_CHARS` / `CASE_QA_MAX_ANSWER_TOKENS` — bounds
- `CASE_QA_CHAT_HISTORY_ENABLED` — optional session persistence
