# Case-Aware Knowledge Base Retrieval Plan

## Status

Implemented on branch `feature/case-aware-kb-retrieval`.

## Locked Decisions

| Topic | Decision |
|-------|----------|
| AWS production vector store | **S3 Vectors** for typical SOC KB corpora (up to about 1,000 docs). OpenSearch Serverless is an alternative for larger scale or advanced search needs. |
| AWS production embedding | **`amazon.titan-embed-text-v2:0`** (1024 dimensions). |
| Preview / demo KB | **Fixture docs only** (`data/preview_scenarios/knowledge_base/`). Do not wire preview to Bedrock KB or S3 Vectors. Bedrock in preview remains chat synthesis only. |
| On-prem production KB | **Postgres/pgvector** (`RAG_BACKEND=postgres`) — unchanged. |

## Problem

Portal chat already retrieves selected-case context before synthesis, and
production retrieval paths include hybrid or managed semantic retrieval
capabilities. The gap is that Knowledge Base retrieval is queried with only the
raw chat question.

For example, if an analyst asks "summarize case 5 in a few sentences", the
question may not mention `db-prod-01.corp.local`, HVA, escalation, database
tier, or containment. Case retrieval can still find the case, but KB retrieval
may not retrieve the HVA registry or other advisory documents because those
case entities are not in the KB query.

## Goal

Make KB retrieval in selected-case chat case-aware:

- retrieve KB context from the analyst question plus high-signal entities and
  facts from the selected case
- preserve read-only portal boundaries
- keep case evidence separate from KB advisory material in synthesis
- make preview demos show KB intelligence without requiring analysts to name
  every KB concept explicitly

## Current Behavior

### On-prem

`answer_case_chat()` retrieves selected-case sources, then calls the KB provider
with `request.question`.

General KB retrieval uses the configured RAG backend when `RAG_ENABLED=true`.
The on-prem RAG configuration already exposes lexical, vector, RRF, and optional
rerank knobs. SPL and Elasticsearch grounding also use question text as their
retrieval input.

### AWS

`answer_selected_case_question()` retrieves selected-case chunks, then calls
`build_chat_knowledge_sources(question=normalized_question, ...)`.

Case archive retrieval uses BM25 plus Titan embeddings merged with RRF over S3
case chunks. Advisory SOC KB retrieval uses Bedrock Knowledge Base retrieval
when `RAG_ENABLED=true`; SPL and Elasticsearch grounding use the same raw
question input shape.

### Preview

Preview uses committed KB fixtures and keyword matching instead of production
RAG. Because the preview KB provider currently sees only the user question,
generic questions like "summarize this case" do not activate HVA, network,
Tier 2, or containment fixtures unless the user includes matching keywords.

## Target Behavior

For selected-case chat, build a deterministic KB retrieval query from:

- the analyst's question
- selected case identifiers such as hostnames, IPs, usernames, service accounts,
  alert/search name, case ID, and notable type
- high-signal case text already retrieved for synthesis, bounded by a small
  character budget

Then use that enriched query for KB retrieval.

Example:

```text
User question:
Summarize case 5 in a few sentences.

Case-aware KB query:
Summarize case 5 in a few sentences.
selected_case_id=case-5
dest_host=db-prod-01.corp.local
src_host=jump-01.corp.local
user=corp\svc-backup
alert_type=Suspicious RDP Lateral Movement
case facts: interactive RDP after six failed logons; production database tier
```

Expected result: KB retrieval can find the HVA registry, network architecture,
and escalation guidance even when the user did not say HVA.

## Scope Contract

### In Scope

- Selected-case chat only.
- Deterministic case-aware KB query construction.
- On-prem KB, SPL-query grounding, and Elasticsearch grounding query input
  enrichment where those features are already enabled.
- AWS portal KB, SPL-query grounding, and Elasticsearch grounding query input
  enrichment where those features are already enabled.
- Preview fixture retrieval using the same enriched query string passed through
  the production app path.
- Prompt labeling that distinguishes current-case evidence from KB advisory
  context.
- Unit tests and preview regression tests for generic summaries retrieving HVA
  context.

### Out Of Scope

- Executing Splunk, Elasticsearch, ServiceNow, EDR, SOAR, or host actions from
  chat.
- Replacing preview with full vector retrieval.
- Adding a new shared cross-package retrieval framework.
- Building a golden eval harness beyond focused regression tests.
- Changing case archive write, embedding, or chunk generation contracts unless a
  test proves case chunks lack the needed identifiers.

### Assumptions

- KB context remains advisory and cannot create case evidence.
- Existing retrieval budgets and trimming remain the guardrail for prompt size.
- The enriched KB query is not shown to the user.
- The selected case has enough identifiers in retrieved chunks for the initial
  implementation.

## Design

### 1. Deterministic KB Query Builder

Add a small helper in each product surface rather than a shared abstraction:

- on-prem: `onprem_service/case_chat.py`
- AWS: `s3_notable_pipeline/src/s3_notable_pipeline/case_chat.py` or
  `portal_chat_kb.py`

The helper should:

- accept the raw question and selected-case sources or chunks
- include only `current_case` lane content when deriving case context
- extract high-signal tokens with simple deterministic rules
- cap output length with a dedicated budget
- preserve exact identifiers such as `db-prod-01.corp.local`
- avoid using model-generated extraction or inference

Initial extraction can be intentionally simple:

- hostnames and fully qualified domain names
- IPv4 addresses
- `domain\user` style account names
- explicit `key=value` facts already present in case chunks
- alert/search name when available in source text

### 2. KB Retrieval Wiring

Use the enriched KB query instead of the raw question for advisory retrieval.

On-prem:

```text
case_sources = retrieve_case_sources(...)
kb_query = build_case_aware_kb_query(request.question, case_sources)
sources.extend(provider(kb_query))
```

AWS:

```text
case_chunks = retrieve_case_chunks_for_question(...)
kb_query = build_case_aware_kb_query(normalized_question, case_chunks)
sources.extend(build_chat_knowledge_sources(question=kb_query, ...))
```

Preview should benefit automatically if its provider receives the enriched
query through the existing `answer_case_chat()` path.

### 3. Source Lane Prompt Labeling

Update on-prem `_build_prompt()` and AWS `build_case_grounded_prompt()` so each
context block includes source metadata:

```text
SOURCE_LANE_JSON: "current_case"
SECTION_JSON: "..."
UNTRUSTED_TEXT_JSON: "..."
```

Prompt rules should state:

- `current_case` blocks are the only source of case evidence.
- `knowledge_base` blocks are advisory organizational context.
- When KB advisory context materially affects risk, priority, escalation,
  containment, or ownership, include it in summaries and triage answers.
- Do not describe KB advisory content as observed case evidence.

### 4. Preview Demo Behavior

For case-5, a generic selected-case question such as:

```text
Summarize this case in a few sentences.
```

should retrieve the HVA registry because the selected case contains
`db-prod-01.corp.local`. The answer should mention that KB advisory context
identifies `db-prod-01.corp.local` as an HVA, while keeping the RDP activity,
failed logons, and service account facts as case evidence.

## Acceptance Criteria

### Functional

- On-prem selected-case chat builds a KB query containing the raw question plus
  selected-case identifiers.
- AWS selected-case chat builds a KB query containing the raw question plus
  selected-case identifiers.
- Generic selected-case summaries can retrieve KB docs keyed by case entities.
- Preview case-5 summary retrieves the HVA registry without the user saying HVA.
- Prompted answers separate case evidence from KB advisory context.
- Empty or missing case sources fall back to the raw question.
- KB retrieval failures keep the existing suppress or fail-closed behavior.

### Non-Functional

- No new third-party dependencies.
- No LLM call is introduced for query expansion.
- Query expansion is deterministic, bounded, and testable.
- Read-only chat action boundaries remain unchanged.
- Retrieval and synthesis token budgets remain bounded.
- Logs must not include secrets or raw auth headers.

## Diff Plan

### Diff 1: On-prem Case-Aware KB Query

Objective: enrich on-prem KB retrieval with selected-case context.

Files:

- `llm_notable_analysis_onprem_systemd/src/llm_notable_analysis_onprem_systemd/onprem_service/case_chat.py`
- `llm_notable_analysis_onprem_systemd/tests/onprem_service/test_case_chat.py`

Tests:

- helper preserves exact hostnames, IPs, and `domain\user` values
- generic question plus case source containing `db-prod-01.corp.local` passes
  that hostname to the KB provider
- empty source list uses the raw question
- provider failure behavior remains unchanged

Commands:

```powershell
cd llm_notable_analysis_onprem_systemd
python -m pytest tests/onprem_service/test_case_chat.py -q
```

Rollback note: revert to passing `request.question` directly into the provider.

### Diff 2: AWS Case-Aware KB Query

Objective: enrich AWS KB retrieval with selected-case chunk context.

Files:

- `s3_notable_pipeline/src/s3_notable_pipeline/case_chat.py`
- `s3_notable_pipeline/src/s3_notable_pipeline/portal_chat_kb.py` if the helper
  is placed beside KB source assembly
- `s3_notable_pipeline/tests/test_portal_handler.py`
- `s3_notable_pipeline/tests/test_portal_api_contract.py` if contract fixtures
  need updated mocks

Tests:

- `build_chat_knowledge_sources()` receives an enriched query for selected-case
  chat
- enriched query includes exact case identifiers from chunks
- no KB sources are added when all KB features are disabled
- existing read-only and action-boundary tests still pass

Commands:

```powershell
cd s3_notable_pipeline
python -m pytest tests/test_portal_handler.py tests/test_portal_api_contract.py -q
```

Rollback note: revert to `question=normalized_question` for
`build_chat_knowledge_sources()`.

### Diff 3: Source Lane Prompt Labels

Objective: make synthesis treat KB content as advisory context rather than case
evidence, and include material KB advisory facts in summaries.

Files:

- `llm_notable_analysis_onprem_systemd/src/llm_notable_analysis_onprem_systemd/onprem_service/case_chat.py`
- `s3_notable_pipeline/src/s3_notable_pipeline/portal_chat.py`
- `llm_notable_analysis_onprem_systemd/tests/onprem_service/test_case_chat.py`
- `s3_notable_pipeline/tests/test_portal_chat.py`

Tests:

- prompt includes `SOURCE_LANE_JSON` and `SECTION_JSON`
- prompt instructs that `knowledge_base` is advisory, not case evidence
- prompt instructs inclusion of material advisory context for summaries and
  triage answers
- source-number stripping and Markdown formatting tests still pass

Commands:

```powershell
cd llm_notable_analysis_onprem_systemd
python -m pytest tests/onprem_service/test_case_chat.py -q

cd ..\s3_notable_pipeline
python -m pytest tests/test_portal_chat.py -q
```

Rollback note: prompt can return to unlabeled context blocks without changing
API schemas.

### Diff 4: Preview Regression

Objective: prove the demo behavior works without literal HVA prompting.

Files:

- `llm_notable_analysis_onprem_systemd/scripts/preview_knowledge_base.py`
- `llm_notable_analysis_onprem_systemd/tests/scripts/test_preview_knowledge_base.py`
- `PREVIEW_CASE_INVESTIGATION_GUIDE.md`
- `llm_notable_analysis_onprem_systemd/docs/operations/analyst_portal/ANALYST_PORTAL_PREVIEW.md`

Tests:

- preview KB retrieval returns the HVA registry when the enriched query contains
  `db-prod-01.corp.local`
- preview selected-case chat regression shows a generic case-5 summary can
  receive HVA KB context
- docs no longer tell demo users they must include HVA keywords for KB behavior

Commands:

```powershell
cd llm_notable_analysis_onprem_systemd
python -m pytest tests/scripts/test_preview_knowledge_base.py tests/onprem_service/test_case_chat.py -q
```

Rollback note: preview can return to question-only keyword matching by removing
the enriched query call site.

### Diff 5: Documentation Alignment

Objective: update operator and product docs after behavior lands.

Files:

- `PORTAL_CHATBOT_CAPABILITY_GAPS.md`
- `llm_notable_analysis_onprem_systemd/docs/planning/PROMPT_ENHANCEMENTS_PLAN.md`
- `s3_notable_pipeline/docs/technical_specs/AWS_ONPREM_PARITY_TECHNICAL_SPEC.md`
- `llm_notable_analysis_onprem_systemd/docs/operations/analyst_portal/ANALYST_PORTAL_CHAT_SECURITY.md`

Tests:

- documentation references match shipped behavior and config names
- no docs imply chat executes KB-driven actions

Commands:

```powershell
python -m pytest llm_notable_analysis_onprem_systemd/tests/onprem_service/test_case_chat.py s3_notable_pipeline/tests/test_portal_chat.py -q
```

Rollback note: docs can be reverted independently if implementation rolls back.

## Open Questions

- Should the enriched KB query budget be a new config knob or a fixed internal
  constant for v1?
- Should SPL and Elasticsearch query-grounding retrieval always use the enriched
  query, or only general SOC KB retrieval in the first implementation?
- Do we need a deterministic materiality filter before injecting KB snippets, or
  are existing retrieval scores plus context budgets sufficient for v1?

## Hard Stops

Stop before implementation if:

- selected-case chunks do not reliably include core identifiers needed for KB
  query expansion
- a proposed change would require chat to call external action systems
- a config or schema change would break existing deployed portal clients
- test fixtures cannot prove the preview case-5 behavior deterministically

