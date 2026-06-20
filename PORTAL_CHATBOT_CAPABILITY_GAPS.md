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
assistant. The only committed post–Wave 3 enhancement (multi-turn synthesis) is
**shipped** on both platforms.

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
| Synthesis input | Current question + bounded prior session turns + retrieved case context (+ optional KB grounding) |
| Retrieval | On-prem and AWS: per-query hybrid lexical + vector RRF over case chunks |
| Response | Single non-streaming completion; Markdown rendering in UI |
| History | Optional transcript persistence (Postgres on-prem, DynamoDB on AWS) for UI reload, session limits, stop/cancel cleanup, and multi-turn synthesis when enabled |
| Safety | No tool execution from chat; post-LLM action-boundary checks; draft-query guidance only |
| UI | Case attach, multi-session sidebar, stop/cancel in-flight request, local + server session storage |

## Shipped Enhancement (P3-1)

### Multi-turn conversation memory in synthesis

**Status:** Shipped on both on-prem and AWS.

**Behavior:** When chat history is enabled, prior user and assistant turns in the
session are included in the model context (bounded by
`CASE_QA_MAX_CONVERSATION_TURNS` and `CASE_QA_MAX_CONVERSATION_CHARS`) so
follow-ups work naturally ("expand on that", "what about hypothesis 2?",
"rewrite the SPL more narrowly").

Retrieval still runs on each turn; transcript context supplements, not replaces,
case-chunk evidence.

**Out of scope for this item:** Holistic "summarize the entire case" modes,
full-case inject, raised chunk budgets as a separate product lane, streaming,
regenerate, and file upload.

---

## Intentional Differences (Not Treated as Defects)

These are product choices aligned with a **read-only SOC case archive assistant**:

| Choice | Rationale |
| --- | --- |
| No tool execution from chat | Prevent unapproved Splunk/ITSM/SOAR actions; keep chat query-transport only |
| Case facts via retrieval on each turn | Reduce hallucination and stale-context drift; multi-turn adds transcript context, not replacement |
| Pinned-case scope | Clear evidence boundary for v1 |
| Stripped citations (on-prem UI) | Simpler UX; avoids implying clickable provenance we do not implement |
| Default-off server chat history | Optional transcript feature; enable when multi-turn synthesis is desired |
| Fixed temperature 0.0 | More deterministic analyst-facing answers |

## Priority Lens

| Item | Status |
| --- | --- |
| Multi-turn memory in synthesis (P3-1) | **Shipped** on both platforms |
| Holistic / full-case inject / higher budgets as a separate mode | **Not pursuing** — stay retrieval-bound |
| Analyst-visible retrieval debug in the portal UI | **Not pursuing** — removed from planning docs |
| Streaming, regenerate, file upload | **Not pursuing** for v1 read-only assistant |

## Platform Parity Notes

| Capability | On-prem | AWS |
| --- | --- | --- |
| Multi-turn synthesis (when history enabled) | Yes | Yes |
| Per-query case retrieval | Hybrid FTS + vector | Hybrid BM25 + Titan vector + RRF |
| UI citations | Stripped | Stripped (Wave 3 Slice A) |
| Chat history store | Postgres | DynamoDB |
| General-knowledge fallback | Configurable | Configurable (Wave 3 Slice A) |

Runtime parity checklist: [`AWS_ONPREM_RUNTIME_PARITY_GAPS.md`](AWS_ONPREM_RUNTIME_PARITY_GAPS.md).

## Revision

| Date | Change |
| --- | --- |
| 2026-06-18 | Committed multi-turn synthesis (item 2); dropped holistic Q&A and retrieval-debug tracking |
| 2026-06-19 | Marked P3-1 shipped; refreshed baseline and parity notes after Wave 3 closeout |

Update this document when portal chat behavior or API contracts change. Do not
duplicate detailed implementation specs here — link to the technical specs above.

