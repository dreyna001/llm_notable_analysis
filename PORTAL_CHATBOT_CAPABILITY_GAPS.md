# Analyst Portal Chatbot — Capability Gaps vs SOTA Interfaces

## Purpose

This document lists chatbot capabilities that the analyst portal Case Q&A assistant
does **not** provide today, measured against state-of-the-art consumer and
enterprise chat interfaces (for example ChatGPT, Claude, Gemini, Copilot, and
similar products).

It covers both deployments:

- **On-prem:** `llm_notable_analysis_onprem_systemd/` (FastAPI portal, Postgres +
  pgvector case archive)
- **AWS:** `s3_notable_pipeline/` (portal Lambda, DynamoDB case index, S3 case
  chunks, Bedrock synthesis)

Use this as a product gap index. Some gaps are intentional for a read-only SOC
assistant; one gap is a **committed** post–Wave 3 enhancement (see below).

**Related contracts:**

- On-prem chat: `llm_notable_analysis_onprem_systemd/docs/technical_specs/analyst_portal_case_archive_technical_spec.md`
- On-prem chat security: `llm_notable_analysis_onprem_systemd/docs/operations/ANALYST_PORTAL_CHAT_SECURITY.md`
- AWS portal parity: `s3_notable_pipeline/docs/planning/AWS_ONPREM_PARITY_REQUIREMENTS_AND_DESIGN.md`
- Runtime parity gaps and Wave 3 decisions: [`AWS_ONPREM_RUNTIME_PARITY_GAPS.md`](AWS_ONPREM_RUNTIME_PARITY_GAPS.md)

## What We Ship Today (Baseline)

The portal chatbot is a **read-only, retrieval-bound case assistant**, not a
general-purpose agent.

| Area | Current behavior |
| --- | --- |
| Scope | Requires a pinned `selected_case_id`; one supported mode: `selected_case` |
| Synthesis input | Current question + retrieved case context (+ optional KB grounding on on-prem) |
| Retrieval | On-prem: per-query hybrid lexical + vector RRF over `case_chunks`. AWS: bounded load of pre-stored S3 chunks for the case (not query-specific hybrid search until Wave 3 Slice B) |
| Response | Single non-streaming completion; Markdown rendering in UI |
| History | Optional transcript persistence (Postgres on-prem, DynamoDB on AWS) for UI reload, session limits, and stop/cancel cleanup |
| Safety | No tool execution from chat; post-LLM action-boundary checks; draft-query guidance only |
| UI | Case attach, multi-session sidebar, stop/cancel in-flight request, local + server session storage |

## Committed Enhancement (Post–Wave 3)

### 2. Multi-turn conversation memory in synthesis

**Product decision:** Add ChatGPT-style follow-up conversation on **both**
on-prem and AWS after Wave 3 runtime parity ships. This is the only SOTA
conversational UX gap we are committing to close from this document.

**Target behavior:** Prior user and assistant turns in the session are included
in the model context so follow-ups work naturally ("expand on that", "what about
hypothesis 2?", "rewrite the SPL more narrowly").

**Gap today:** Each `POST /api/chat` is **stateless for the LLM**. The backend
builds the prompt from the **current question only** plus retrieved archive
chunks (and optional KB context). Persisted chat history is transcript storage for
the UI — it is **not** replayed into synthesis on the next turn.

**Applies to:** On-prem and AWS (implement together; not part of Wave 3 parity
checklist).

**Note:** Enabling `CASE_QA_CHAT_HISTORY_ENABLED` does not change synthesis
today; it only persists and reloads transcripts.

**Out of scope for this item:** Holistic "summarize the entire case" modes,
full-case inject, raised chunk budgets as a separate product lane, streaming,
regenerate, and file upload.

---

## Intentional Differences (Not Treated as Defects)

These are product choices aligned with a **read-only SOC case archive assistant**:

| Choice | Rationale |
| --- | --- |
| No tool execution from chat | Prevent unapproved Splunk/ITSM/SOAR actions; keep chat query-transport only |
| Case facts via retrieval on each turn (today) | Reduce hallucination and stale-context drift; multi-turn will add transcript context, not replace retrieval |
| Pinned-case scope | Clear evidence boundary for v1 |
| Stripped citations (on-prem UI) | Simpler UX; avoids implying clickable provenance we do not implement |
| Default-off server chat history | Optional transcript feature until multi-turn synthesis is implemented |
| Fixed temperature 0.0 | More deterministic analyst-facing answers |

## Priority Lens

| Item | Status |
| --- | --- |
| Multi-turn memory in synthesis (item 2 above) | **Committed** post–Wave 3 on both platforms |
| Holistic / full-case inject / higher budgets as a separate mode | **Not pursuing** — stay retrieval-bound |
| Analyst-visible retrieval debug in the portal UI | **Not pursuing** — removed from planning docs |

## Platform Parity Notes

| Capability gap | On-prem | AWS |
| --- | --- | --- |
| Stateless synthesis (today) | Yes | Yes |
| History not in prompt (today) | Yes | Yes |
| Per-query case retrieval | Hybrid FTS + vector | Bounded S3 chunk load until Wave 3 Slice B |
| UI citations | Stripped | Backend citations until Wave 3 Slice A removes them |
| Chat history store | Postgres | DynamoDB |
| General-knowledge fallback | Configurable | Not equivalent to on-prem path until Wave 3 Slice A |

For AWS portal parity (prompt/API and hybrid retrieval), see
[`AWS_ONPREM_RUNTIME_PARITY_GAPS.md`](AWS_ONPREM_RUNTIME_PARITY_GAPS.md).

## Revision

| Date | Change |
| --- | --- |
| 2026-06-18 | Committed multi-turn synthesis (item 2); dropped holistic Q&A and retrieval-debug tracking |

Update this document when portal chat behavior or API contracts change. Do not
duplicate detailed implementation specs here — link to the technical specs above.
