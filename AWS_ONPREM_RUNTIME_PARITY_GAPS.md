# AWS / On-Prem Runtime Parity Gaps (Current State)

## Purpose

This document lists **observed gaps between production behavior today** in:

- **On-prem:** `llm_notable_analysis_onprem_systemd/` (FastAPI portal, Postgres +
  pgvector case archive, local OpenAI-compatible LLM)
- **AWS:** `s3_notable_pipeline/` (portal Lambda, DynamoDB case index, S3 case
  chunks, Bedrock synthesis)

It is a **current-state delta index** and **Wave 3 decision record** for closing
runtime gaps. Wave 1 and Wave 2 are marked complete in
[`TODO_AWS_PIPELINE_FEATURE_PARITY_WITH_ONPREM.md`](TODO_AWS_PIPELINE_FEATURE_PARITY_WITH_ONPREM.md).

For post–Wave 3 chat UX (multi-turn synthesis) and intentional non-goals see
[`PORTAL_CHATBOT_CAPABILITY_GAPS.md`](PORTAL_CHATBOT_CAPABILITY_GAPS.md).

**Related specs:**

- [`s3_notable_pipeline/docs/planning/AWS_ONPREM_PARITY_REQUIREMENTS_AND_DESIGN.md`](s3_notable_pipeline/docs/planning/AWS_ONPREM_PARITY_REQUIREMENTS_AND_DESIGN.md)
- [`llm_notable_analysis_onprem_systemd/docs/planning/PROMPT_ENHANCEMENTS_PLAN.md`](llm_notable_analysis_onprem_systemd/docs/planning/PROMPT_ENHANCEMENTS_PLAN.md)

---

## Locked Wave 3 Decisions (Portal Chat)

**Goal:** AWS Case Q&A behavior and API contract match **on-prem today**. On-prem
is the source of truth unless noted below.

| Topic | Decision |
| --- | --- |
| Prompts | Port on-prem `_build_prompt` and `_build_general_knowledge_prompt` verbatim (or via shared module). |
| Model output shape | **Plain Markdown text** in `answer`, not JSON from the model. AWS stops asking Bedrock for `{answer, answer_status, citations}` JSON. |
| Markdown format | Same as on-prem: formatted text the portal UI already renders (see plain-language note below). |
| Citations | **Remove** from AWS external API and synthesis contract. Do not require or return `citations` in `ChatResponseModel`. Strip any citation markers in post-processing like on-prem. |
| `answer_status` | **`answered` \| `unknown` \| `refused` only.** Retire `insufficient_context` in live chat responses; map legacy stored values at read time if needed. |
| General-knowledge fallback | Same orchestration as on-prem: empty/weak retrieval or insufficient-archive phrase -> `_finalize_general_knowledge_response` when `CASE_QA_GENERAL_KNOWLEDGE_ENABLED=true`. |
| KB / RAG in chat | Same as on-prem: merge advisory KB snippets into retrieval sources before synthesis when `rag` / SPL / Elastic grounding flags are on (Bedrock KB on AWS, Postgres RAG on-prem). |
| Post-LLM guards | Port on-prem: `sanitize_portal_chat_answer`, `synthesized_answer_crosses_action_boundary` -> `refused`, `_should_fallback_to_general_knowledge` -> general-knowledge path. **No** chat LLM repair loop (on-prem does not use one). |
| Context packaging | Match on-prem `<CONTEXT_BLOCK>` + `UNTRUSTED_TEXT_JSON:` + JSON-escaped chunk text. Drop numbered `[1] chunk_id=...` source blocks. |
| Query-specific retrieval | **Still open** (separate diff, W3-4). Not part of this locked prompt/contract slice. |

**Plain language — what “GitHub-flavored Markdown” means in the prompt:**

The model should return **normal formatted analyst text**, not JSON and not raw
HTML. Concretely:

- **Headings** (`## Section`) and **bullet lists** for scanability.
- **Bold** and short paragraphs where useful.
- **Code blocks** for draft SPL, KQL, or shell: opening ` ``` ` on its own line,
  optional language tag (`spl`, `bash`), code, closing ` ``` ` on its own line.
- **Blank lines** before/after headings, lists, and code blocks so the React
  chat panel renders cleanly.

“GitHub-flavored” (GFM) is the Markdown variant the portal UI already supports:
tables, fenced code, lists, etc. Analysts see the same styled chat bubbles on
on-prem today; AWS should produce the same kind of string in `answer`.

**Implementation note:** Port prompt builders and post-LLM helpers from
`llm_notable_analysis_onprem_systemd/onprem_service/case_chat.py` into
`s3_notable_pipeline/portal_chat.py` and wire orchestration through
`s3_notable_pipeline/case_chat.py` + `portal_handler.py` to mirror
`answer_case_chat()` flow. Bedrock call becomes single-turn text completion
(Converse or invoke) like on-prem `openai_chat_complete`.

---

## Suggested Solutions (Q&A)

This section records recommended fixes for the parity questions that motivated
Wave 3. On-prem is the source of truth for portal chat unless noted.

### Portal chat (Case Q&A)

**Match AWS prompts to on-prem**

Suggested solution: Copy `_build_prompt` and `_build_general_knowledge_prompt`
from `onprem_service/case_chat.py` into `s3_notable_pipeline/portal_chat.py`
(or a small shared module both deployments import). Replace the current
six-line JSON prompt. Keep only typing adapters so AWS chunk dicts map to the
same source-block shape on-prem expects. Do not import `ttp_analyzer.py`.

**What does “GitHub-flavored Markdown” mean?**

Suggested solution: Treat this as a **UI formatting instruction**, not a separate
output protocol. The model returns a plain string in `answer` that the React chat
panel renders as Markdown: headings, bullets, bold, numbered steps, and fenced
code blocks (` ``` ` on their own lines) for draft SPL/KQL/shell. No JSON wrapper,
no HTML. AWS Bedrock should return that string directly; the portal already
displays it the same way on on-prem.

**Remove citations on AWS to match on-prem**

Suggested solution: Delete `citations` from `ChatResponseModel`, `PortalAnswer`,
and `portal_handler` responses. Remove prompt/validation logic that requires
citations for `answered`. Port `sanitize_portal_chat_answer` to strip any
`[1]`, `Source:`, or footnote markers the model emits anyway. Align OpenAPI and
frontend parsers with on-prem (answer + answer_status + session_id only).

**Match `answer_status` to on-prem**

Suggested solution: Emit only `answered`, `unknown`, and `refused` from AWS chat
synthesis. Set `unknown` when archive context is insufficient and general
knowledge is off or unusable; set `refused` when action-boundary regex fires;
set `answered` otherwise. Stop emitting `insufficient_context` in new responses.
Optionally map legacy `insufficient_context` to `unknown` when loading old chat
history rows.

**General-knowledge fallback same as on-prem**

Suggested solution: Refactor AWS `case_chat.py` / `portal_handler.py` to follow
`answer_case_chat()` branching: call general-knowledge synthesis when retrieval
returns no sources, when sanitized answer is empty, or when
`_should_fallback_to_general_knowledge` matches the insufficient-archive phrase
— all gated by `CASE_QA_GENERAL_KNOWLEDGE_ENABLED`. Reuse on-prem
`_finalize_general_knowledge_response` logic (including out-of-scope -> `unknown`
and action-boundary -> `refused`).

**KB / RAG context in chat same as on-prem**

Suggested solution: Add a chat-side provider (mirror
`_default_knowledge_base_provider`) that, before synthesis, calls existing
Bedrock KB retrieve helpers when `rag`, `spl_readonly`, or `elastic_readonly`
profiles/flags are on. Append retrieved text as extra `CONTEXT_BLOCK` sources
with section labels matching on-prem (`knowledge_base.rag`,
`knowledge_base.spl_query_grounding`, etc.). Keep KB advisory-only; do not treat
it as case evidence in the prompt beyond what on-prem already allows.

**Post-LLM guards same as on-prem**

Suggested solution: Port three helpers unchanged from on-prem `case_chat.py`:
`sanitize_portal_chat_answer`, `synthesized_answer_crosses_action_boundary`, and
`_should_fallback_to_general_knowledge` (plus their regex constants). Run them
in the same order as on-prem after every Bedrock text completion. Do **not** add
a chat repair LLM call on AWS; on-prem does not use one—use general-knowledge
fallback instead when the grounded answer is weak.

**Context packaging same as on-prem**

Suggested solution: Replace numbered `[1] chunk_id=...` blocks with:

```text
<CONTEXT_BLOCK>
UNTRUSTED_TEXT_JSON: <json.dumps(chunk_text)>
</CONTEXT_BLOCK>
```

Use `search_text` or `text` from each S3 chunk. Keep chunk_id internal for
retrieval/debug only; do not expose it in the prompt layout on-prem uses.

**Query-specific retrieval (separate from prompt/API slice)**

Suggested solution: See **Section 3 — Hybrid retrieval parity (W3-4)**. Implement
AWS Decision 7 (BM25 + Bedrock Titan query embed + RRF) so chunk selection depends
on the analyst question, matching on-prem `_execute_chunk_retrieval` behavior.
Config keys already exist; runtime code does not.

### Notable analyzer

**Match verdict vocabulary to on-prem**

Suggested solution: Change AWS `ttp_analyzer.py` OUTPUT_CONTRACT and
`analyze_notable` tool enum to the three on-prem values:
`likely_benign`, `likely_malicious`, `unknown`. Update `case_archive.py` to
persist normalized verdicts on write. Add read-time mapping for legacy AWS cases:
`likely_true_positive` -> `likely_malicious`, `likely_false_positive` ->
`likely_benign`. Align portal list/detail filters and UI labels with on-prem
`verdicts.py`.

**Can structured output transport be matched across AWS and on-prem?**

Suggested solution: **Not at the wire level** — keep platform adapters
(OpenAI-compatible HTTP on-prem, Bedrock Converse on AWS). **Do match at the
contract level:** same JSON schema, same validators, same repair-once behavior,
same fallback when tool mode fails. Document adapters in each codebase; share
validators and prompt *content* where practical. Do not force one HTTP shape on
both platforms.

**Can response parsing be matched?**

Suggested solution: **Not as shared parser code.** On-prem needs thinking-trace
stripping and optional `literal_eval` for local models; AWS needs Bedrock
toolUse/text extraction. **Do match the outcome:** both paths produce the same
validated dict before markdown/report generation. Add cross-platform fixture
tests that assert identical validation pass/fail on the same parsed objects,
not identical parsing implementation.

**Are on-prem repair prompts more mature?**

Suggested solution: **No.** Policy is the same on both sides (repair shape/enums
only; never add facts). AWS has explicit tool vs raw-JSON repair templates;
on-prem covers the same ground via transport fallback. Keep templates in sync
when OUTPUT_CONTRACT changes; extract a shared repair template module only if
drift becomes a maintenance problem. Do not prioritize a one-way port from
either side unless a diff shows real divergence.

**What should we do for the SOC context block label?**

Suggested solution: **Standardize on the on-prem header** on both platforms.
Use `SOC_OPERATIONAL_CONTEXT` followed by body text or `(none)` when empty.
Remove AWS-only `(advisory only; not direct alert evidence):` from the header in
`ttp_analyzer.py`; advisory semantics already live in the shared
`SOC_CONTEXT_RULES` block. No extra one-line rule needed unless product wants
redundant labeling—rules section is enough.

---

## Why Wave 2 Was Marked Complete

Wave 2 closed against **Diff 1–5 checklists** (API exists, retrieval path, tests
green), not full on-prem behavioral parity. Several Wave 2 design decisions
(for example external citations) **contradict** on-prem; Wave 3 **supersedes**
those for chat with the locked table above.

---

## Summary Matrix (Before Wave 3)

| Area | On-prem today | AWS today | Wave 3 action |
| --- | --- | --- | --- |
| Portal chat prompts | Rich Markdown prompts | Minimal JSON prompt | **Match on-prem** |
| General-knowledge fallback | Implemented | Config flag only | **Match on-prem** |
| Chat KB context | Postgres RAG merged into sources | Not in chat path | **Match on-prem** |
| Case chunk retrieval | Per-query hybrid RRF (Postgres) | Bounded S3 list (spec: hybrid not shipped) | **W3-4: implement Decision 7** |
| Case-chunk reranker | None (same as AWS) | None | No parity action |
| Chat `answer_status` | `answered`, `unknown`, `refused` | `insufficient_context` | **Match on-prem** |
| Chat API citations | Not exposed | Required in API | **Remove on AWS** |
| Post-LLM guards | Sanitize, refuse, fallback | JSON validate only | **Match on-prem** |
| Context packaging | `CONTEXT_BLOCK` / `UNTRUSTED_TEXT_JSON` | Numbered sources | **Match on-prem** |
| Analyzer verdict enum | 3-value on-prem set | 4-value AWS set | **Match on-prem** (Section 2) |
| Analyzer transport/parsing | Platform adapters | Platform adapters | **Contract parity only** (Section 2) |

---

## 1. Portal Chat (Case Q&A) — Largest Gap

Wave 3 portal chat work splits into **two slices** (see **Section 3** for
definitions). **Slice A — prompt/API parity** (W3-1 through W3-3, W3-5 through
W3-8) can ship first. **Slice B — hybrid retrieval** (W3-4) fixes *which* chunks
reach the model on large cases; ship as soon as possible after or in parallel
with Slice A.

This section expands Slice A (locked decisions) into an implementation checklist.

### 1.1 Prompts — match on-prem

**Suggested solution:** See **Suggested Solutions (Q&A)** — portal chat,
prompts and Markdown format.

**Source of truth:** `onprem_service/case_chat.py`

| Function | Purpose |
| --- | --- |
| `_build_prompt` | Case-grounded chat when retrieval returned sources |
| `_build_general_knowledge_prompt` | Technology / cyber fallback when archive context is insufficient |

**AWS changes:**

1. Replace `_build_prompt` in `portal_chat.py` with on-prem equivalent (adapt
   only the `RetrievedSource` / chunk dict input typing).
2. Add `_build_general_knowledge_prompt` and wire fallback orchestration.
3. Remove prompt lines that ask for JSON, `citations`, or `insufficient_context`.
4. Keep OUTPUT FORMAT instructions that require **Markdown text** (GFM as
   described above).

### 1.2 API response — remove citations; match `answer_status`

**Suggested solution:** See **Suggested Solutions (Q&A)** — citations and
`answer_status`.

**On-prem** `ChatResponseModel`:

```json
{
  "answer": "string (Markdown)",
  "answer_status": "answered | unknown | refused",
  "session_id": "string | null"
}
```

**AWS after Wave 3:** Same shape. Delete `citations` from:

- `portal_api_models.ChatResponseModel`
- `portal_handler.py` response payload
- `portal_chat.PortalAnswer` (or drop dataclass citations field)
- OpenAPI / generated client schemas
- Tests in `test_portal_chat.py`, `test_portal_handler.py`

**Status mapping (AWS implementation):**

| Condition | `answer_status` |
| --- | --- |
| Normal grounded or general-knowledge answer | `answered` |
| Archive insufficient and general knowledge disabled/unusable | `unknown` |
| Action-boundary regex triggered | `refused` |
| General-knowledge out-of-scope prefix | `unknown` (same as on-prem) |

Do **not** expose `insufficient_context` in new responses. Chat history may
still accept legacy stored values for backward compatibility.

### 1.3 General-knowledge fallback — match on-prem

**Suggested solution:** See **Suggested Solutions (Q&A)** — general-knowledge
fallback.

Mirror `answer_case_chat()` branching:

1. Retrieve case sources (+ KB sources per 1.4).
2. If **no sources** -> `_finalize_general_knowledge_response` when enabled,
   else standard insufficient-archive message with `unknown`.
3. After case-grounded synthesis -> `sanitize_portal_chat_answer`.
4. If empty answer or `_should_fallback_to_general_knowledge(answer)` -> general
   knowledge path when enabled.
5. If `synthesized_answer_crosses_action_boundary(answer)` -> `refused`.

Port helper functions and regexes from on-prem `case_chat.py` (or shared module).

### 1.4 KB / RAG context in chat — match on-prem

**Suggested solution:** See **Suggested Solutions (Q&A)** — KB / RAG in chat.

**On-prem:** `_default_knowledge_base_provider` appends advisory chunks when
`RAG_ENABLED`, `SPL_QUERY_RAG_ENABLED`, or `ELASTICSEARCH_GROUNDING_ENABLED`.

**AWS:** Before synthesis, retrieve from configured Bedrock Knowledge Bases
(same IDs/flags as analyzer grounding) and append as additional `CONTEXT_BLOCK`
sources with sections like `knowledge_base.rag`, `knowledge_base.spl_query_grounding`,
etc. Label as advisory in prompt rules only (same as on-prem — not direct case
evidence).

Reuse `bedrock_kb_retrieval.py` retrieve helpers; do **not** call analyzer
`ttp_analyzer.py` from chat.

### 1.5 Post-LLM guards — match on-prem

**Suggested solution:** See **Suggested Solutions (Q&A)** — post-LLM guards.

Port unchanged logic:

| Helper | Effect |
| --- | --- |
| `sanitize_portal_chat_answer` | Strip citation markers and whitespace noise from display text |
| `synthesized_answer_crosses_action_boundary` | Return `refused` if model claims it ran searches/tickets/actions |
| `_should_fallback_to_general_knowledge` | Detect “archive did not contain enough…” boilerplate and retry general knowledge |

**Explicit non-goal:** Chat LLM repair loop — see **Section 1.7**.

### 1.6 Context packaging — match on-prem

**Suggested solution:** See **Suggested Solutions (Q&A)** — context packaging.

**On-prem per source:**

```text
<CONTEXT_BLOCK>
UNTRUSTED_TEXT_JSON: "<json-escaped chunk text>"
</CONTEXT_BLOCK>
```

**AWS today:** `[1] chunk_id=...\n<text>` — replace with on-prem packaging.
Chunk text comes from `search_text` or `text` field in S3 chunk JSON.

The `UNTRUSTED_TEXT_JSON` label tells the model archive text is evidence, not
instructions (prompt-injection mitigation). On-prem system prompt references this;
AWS must use the same label once prompts are ported.

### 1.7 Chat LLM repair loop — not parity; do not implement on AWS chat

**What this is:** A second LLM call that tries to fix malformed **chat** output
(for example invalid JSON or missing citations).

**On-prem today:** Portal chat does **not** use a repair loop. One synthesis
call → `sanitize_portal_chat_answer` → action-boundary check → optional
general-knowledge fallback. The **notable analyzer** does use a one-shot JSON
repair on both platforms; that is separate and stays.

**AWS today:** `portal_chat.py` does **not** implement chat repair. The Wave 2
**design spec** (`AWS_ONPREM_PARITY_REQUIREMENTS_AND_DESIGN.md`, chat validation
rules) described one repair attempt when the model returned bad JSON or missing
citations — that matched the old JSON+citations chat contract, not on-prem
behavior.

**Wave 3 decision:** Do **not** add chat repair on AWS. Match on-prem: plain
Markdown text from one Bedrock call, then deterministic post-LLM guards. This
is **not** removing shipped AWS chat functionality; it **supersedes** a Wave 2
design direction that was never on-prem parity and was not implemented in portal
chat code.

### 1.8 Out of scope for Slice A (prompt/API)

- **Hybrid retrieval (Slice B / W3-4):** see Section 3 — required for large-case
  Q&A quality; does not block Slice A but should follow quickly.
- **Multi-turn synthesis:** committed post–Wave 3 on both platforms; see
  `PORTAL_CHATBOT_CAPABILITY_GAPS.md` item 2.

---

## 2. Notable Analyzer — Remaining Deltas

Wave 1 analyzer parity is largely code-complete. Remaining **behavioral / data**
differences:

### 2.1 Verdict vocabulary — match on-prem (locked)

**Suggested solution:** See **Suggested Solutions (Q&A)** — verdict vocabulary.

**Decision:** AWS analyzer prompt, tool schema, and archive writes use on-prem
verdicts only:

| Value | Meaning |
| --- | --- |
| `likely_benign` | Benign / admin / false-positive supported by alert evidence |
| `likely_malicious` | Adversary or true-positive concern supported by alert evidence |
| `unknown` | Insufficient or conflicting evidence |

Retire AWS-only values `likely_true_positive` and `likely_false_positive` in
`ttp_analyzer.py` OUTPUT_CONTRACT and Bedrock tool enum.

**Migration:** Map legacy archived AWS values at portal read/list time until
cases age out (`likely_true_positive` -> `likely_malicious`;
`likely_false_positive` -> `likely_benign`).

**Touchpoints:** `ttp_analyzer.py`, `case_archive.py`, tests, portal verdict
filters.

### 2.2 Structured output transport — platform-specific; match contract, not wire format

**Suggested solution:** See **Suggested Solutions (Q&A)** — structured output
transport.

**Cannot match byte-for-byte.** On-prem talks to vLLM/LiteLLM via OpenAI-compatible
HTTP; AWS uses Bedrock Converse. Different APIs, different error shapes.

**Can and should match:**

- Same JSON **schema** (keys, types, verdict enum after 2.1).
- Same **validation** and **repair-once** policy after the model responds.
- Same **fallback** (raw JSON mode when tool use fails on AWS; prompt-json /
  tool_call fallback on on-prem).

Treat transport as a **thin adapter** per platform; shared validators and prompt
**content** are the parity surface.

### 2.3 Response parsing — platform-specific; match validated result

**Suggested solution:** See **Suggested Solutions (Q&A)** — response parsing.

**Cannot share one parser.** Differences that stay platform-local:

| Concern | On-prem | AWS |
| --- | --- | --- |
| Thinking traces | `strip_llm_thinking_preamble` (Qwen-style) | N/A for Bedrock |
| Malformed JSON | `extract_json_object` + optional `ast.literal_eval` | Bedrock toolUse / text block extraction |
| Tool output | OpenAI `tool_calls[].function.arguments` | Bedrock `toolUse` blocks |

**Parity rule:** Both paths must produce the same validated Python dict before
markdown/report generation. Tests should assert identical schema validation
outcomes on fixture payloads, not identical parser code.

### 2.4 Repair prompts — equivalent maturity; keep in sync

**Suggested solution:** See **Suggested Solutions (Q&A)** — repair prompts.

On-prem and AWS repair templates are **the same policy** (repair shape/enums
only; do not add facts). AWS has two templates (tool mode vs raw JSON); on-prem
has raw JSON plus tool-call path via transport layer.

**Action:** When changing OUTPUT_CONTRACT, update **both** codepaths. Neither side
is materially more mature; avoid porting AWS -> on-prem or vice versa unless diff
shows drift. Prefer a shared repair template string if edits become frequent.

### 2.5 SOC context block label — match on-prem (locked)

**Suggested solution:** See **Suggested Solutions (Q&A)** — SOC context block
label.

**Decision:** Use on-prem header format on both platforms.

**When context present:**

```text
SOC_OPERATIONAL_CONTEXT
<retrieved advisory text>
```

**When absent:**

```text
SOC_OPERATIONAL_CONTEXT
(none)
```

Advisory semantics stay in the shared `SOC_CONTEXT_RULES` block (already identical).
Remove AWS-only inline suffix `(advisory only; not direct alert evidence):` from
the header in `ttp_analyzer.py` `_build_prompt`; the rules section already states
that SOC context is not direct alert evidence.

**Optional one-line addition to rules (both sides):** none required — current
`SOC_CONTEXT_RULES` is sufficient once headers align.

---

## 3. Wave 3 Portal Chat — Two Workstreams

AWS portal chat parity is two related efforts. They can ship in separate PRs;
Slice A improves *how answers are written*; Slice B improves *which evidence is
selected*.

### 3.1 What is “prompt/API parity”? (Slice A)

**Plain language:** Make AWS chat **look and behave like on-prem chat** to the
analyst and to the frontend — same instructions to the model, same JSON response
shape, same fallback and safety rules — even though AWS still calls Bedrock
instead of vLLM.

| Layer | What changes on AWS | On-prem reference |
| --- | --- | --- |
| **Prompts** | Port `_build_prompt` and `_build_general_knowledge_prompt` | `case_chat.py` |
| **Model I/O** | Bedrock returns **Markdown text**, not JSON with citations | `openai_chat_complete` |
| **API contract** | `answer`, `answer_status`, `session_id` only; no `citations` | `portal_api_models.py` |
| **Orchestration** | Same branches: empty retrieval, weak answer, general knowledge, refuse | `answer_case_chat()` |
| **KB in chat** | Merge advisory Bedrock KB snippets into sources | `_default_knowledge_base_provider` |
| **Post-LLM guards** | Sanitize, action-boundary, fallback regexes | `sanitize_portal_chat_answer`, etc. |
| **Context packaging** | `<CONTEXT_BLOCK>` + `UNTRUSTED_TEXT_JSON` | Same |

**What Slice A does *not* fix:** On a large case, AWS may still send the **wrong
chunks** if Slice B is not done — the model will answer more professionally but
from irrelevant context.

**Checklist IDs:** W3-1, W3-2, W3-3, W3-5, W3-6, W3-7, W3-8, W3-12 (plus W3-11
optional).

### 3.2 What is “hybrid retrieval parity”? (Slice B)

**Plain language:** When an analyst asks a question, **pick the best case chunks
for that question** — not the first N files in S3. On-prem already does this
with keyword search + semantic search + score fusion. AWS **spec requires it**
(Decision 7) but **code does not implement it yet**.

**On-prem today** (`case_chat._execute_chunk_retrieval`):

1. Embed the analyst question (local Mixedbread model).
2. **Lexical lane:** Postgres full-text search over `case_chunks.search_text`
   for the pinned case (`CASE_QA_LEXICAL_TOP_K`, default 30).
3. **Vector lane:** pgvector cosine similarity on stored chunk embeddings
   (`CASE_QA_VECTOR_TOP_K`, default 30).
4. **Merge:** Reciprocal rank fusion (`_merge_rrf`, `CASE_QA_RRF_K=60`).
5. **Trim:** Apply `CASE_QA_MAX_TOTAL_CHUNKS`, `CASE_QA_CONTEXT_BUDGET_CHARS`,
   then pass ranked chunks to synthesis.

**AWS today** (`case_chat.retrieve_selected_case_chunks`):

- Lists S3 keys under `case_chunks/{case_id}/`, loads until
  `CASE_QA_MAX_TOTAL_CHUNKS` — **question is ignored**.
- Weaker on large cases; order is storage order, not relevance.

**AWS target (match on-prem behavior, Decision 7 storage):**

1. Load chunk JSON objects for the pinned case from S3 (all chunks for the case,
   or a bounded pre-load if case size requires caps).
2. **Lexical lane:** In-memory BM25 (stdlib) over each chunk’s `search_text`.
3. **Vector lane:** Bedrock Titan embed the question (`amazon.titan-embed-text-v2:0`,
   1024-d, normalized); cosine similarity vs chunk vectors written at embed time.
4. **Merge:** Port `_merge_rrf` logic; use existing `CASE_QA_RRF_K`.
5. **Trim:** Same caps as on-prem; pass top chunks to `portal_chat` synthesis.

No OpenSearch, Kendra, or Bedrock KB for **case-archive** retrieval — only for
optional advisory KB (Slice A / W3-3).

**Validity note:** Wave 2 marked retrieval “complete” because S3 chunks and
embed Lambda exist. **Per-query hybrid rank in the portal Lambda was not
shipped** — config knobs (`CASE_QA_LEXICAL_TOP_K`, etc.) are ahead of the code.

**Checklist ID:** W3-4.

### 3.3 Post–Wave 3 product commitment and non-goals

| Topic | Decision |
| --- | --- |
| Multi-turn synthesis (ChatGPT-style follow-ups) | **Committed** on both platforms after Wave 3; see `PORTAL_CHATBOT_CAPABILITY_GAPS.md` item 2 |
| Holistic / full-case inject / separate long-context mode | **Not pursuing** — stay retrieval-bound |
| Reranker on **case** chunks | No on either side; optional future only if measured |
| Reranker on **KB** snippets | Optional (`RAG_RERANK_ENABLED` on-prem, default off); not Wave 3 |

Do not block Slice A or B on multi-turn; ship Wave 3 first, then multi-turn as
the next chat UX slice on both platforms together.

**Plain language — reranker vs case-chunk retrieval:**

Chat pulls context from two different places:

1. **Case archive chunks** — pieces of the pinned case (alert, analysis, hypotheses,
   etc.). On-prem ranks these with keyword + vector search + RRF. There is **no
   second “rerank” pass** on that list. AWS should match that same hybrid rank
   (Slice B); it also has no case-chunk reranker.

2. **General knowledge base (KB)** — optional SOPs, runbooks, Splunk index notes,
   etc., when `RAG_ENABLED` (and related flags) are on. On-prem can optionally
   run a **reranker** on KB hits (`RAG_RERANK_ENABLED`, default **off**) to reorder
   KB snippets before they are added as advisory context. That reranker is **not**
   used when scoring case chunks.

So: **rerank is a KB-only optional refinement on on-prem, not part of case-chunk
retrieval.** Neither platform reranks case chunks today; AWS parity for chat
quality is hybrid retrieval (Slice B), not turning on rerank for case chunks.

**Prompt/API parity (Slice A)** is documented in Section 3.1 and checklist W3-1
through W3-8 — same prompts, API shape, guards, and Markdown answers as on-prem.

### 3.4 Suggested implementation order

```text
Slice A (prompt/API)     ──► ship first; analyst-visible contract alignment
Slice B (hybrid retrieval) ──► ship next; fixes large-case wrong-chunk problem
Optional: W3-9–W3-11 (analyzer verdict, diagnostics, OpenAPI)
```

Slice A and B touch different files (`portal_chat.py` vs `case_chat.py` retrieval).
They can run in parallel if staffed; merge Slice A before Slice B if only one
sequence is possible — Slice A is smaller and unblocks UI/API tests.

**Suggested solution (W3-4):**

1. Add `retrieve_selected_case_chunks_for_question(case_id, question, ...)` that
   replaces list-order loading in `answer_selected_case_question`.
2. Port or reimplement `_merge_rrf` and candidate trimming from on-prem
   `case_chat.py` (BM25 in stdlib; no new dependencies).
3. Call Bedrock Titan embed for the question in portal Lambda (same model/dims as
   embed Lambda at chunk write).
4. Unit-test with fixture chunks: question about “hypothesis 3” ranks the chunk
   containing that string above unrelated chunks.
5. Keep `retrieve_selected_case_chunks` name as thin wrapper or deprecate in favor
   of question-aware entrypoint.

---

## 4. Wave 3 Implementation Checklist

### Slice A — Prompt/API parity

| ID | Item | Status | Notes |
| --- | --- | --- | --- |
| W3-1 | Port case-grounded + general-knowledge prompts | Open | From `case_chat.py` |
| W3-2 | General-knowledge orchestration | Open | Mirror `answer_case_chat()` |
| W3-3 | KB context in chat retrieval | Open | Bedrock KB retrieve |
| W3-5 | Post-LLM guards | Open | Sanitize, refuse, fallback |
| W3-6 | API: drop citations, match `answer_status` | Open | Locked |
| W3-7 | Context packaging `UNTRUSTED_TEXT_JSON` | Open | Locked |
| W3-8 | Bedrock text completion (not JSON from model) | Open | Locked |
| W3-12 | OpenAPI sync | Open | After API shape change |

### Slice B — Hybrid retrieval parity

| ID | Item | Status | Notes |
| --- | --- | --- | --- |
| W3-4 | Per-query BM25 + Titan vector + RRF over S3 chunks | Open | Decision 7; match `_execute_chunk_retrieval` |

### Other Wave 3

| ID | Item | Status | Notes |
| --- | --- | --- | --- |
| W3-9 | Analyzer verdict enum | Open | Locked |
| W3-10 | SOC context header format | Open | Locked |
| W3-11 | `/api/diagnostics/chat-readiness` route | Open | Lower priority |

**Post–Wave 3 (not in Wave 3 checklist):**

| ID | Item | Status | Notes |
| --- | --- | --- | --- |
| P3-1 | Multi-turn conversation memory in synthesis | Open | Both platforms; see `PORTAL_CHATBOT_CAPABILITY_GAPS.md` item 2 |

**Cancelled / superseded:**

- Chat LLM repair loop on AWS chat (Wave 2 design only; on-prem never had it;
  use post-LLM guards and general-knowledge fallback instead — Section 1.7).
- External citations in chat API (Wave 2 design superseded by Wave 3).
- Holistic / full-case inject as a product lane (not pursuing).
- Analyst-visible retrieval debug UI (not pursuing; do not reintroduce in plans).

---

## 5. Intentional Platform Differences (Unchanged)

| Topic | On-prem | AWS |
| --- | --- | --- |
| LLM backend | vLLM / LiteLLM | Bedrock |
| Case archive | Postgres + pgvector | DynamoDB + S3 |
| KB storage | Postgres RAG / SQLite+FAISS | Bedrock Knowledge Base |
| Analyzer HTTP vs Converse | OpenAI-compatible | Bedrock Converse |

These stay different; **behavior and contracts** converge via Wave 3.

---

## Revision

| Date | Change |
| --- | --- |
| 2026-06-18 | Initial gap index |
| 2026-06-18 | Locked Wave 3 portal chat decisions; analyzer Q&A; plain-language GFM note |
| 2026-06-18 | Added **Suggested Solutions (Q&A)** section with concrete fixes per question |
| 2026-06-18 | Section 3: prompt/API vs hybrid retrieval workstreams; W3-4 implementation plan |
| 2026-06-18 | Plain-language reranker vs case-chunk retrieval note in Section 3.3 |
| 2026-06-18 | Committed multi-turn (P3-1); chat repair loop clarified (Section 1.7); dropped holistic and retrieval-debug tracking |
