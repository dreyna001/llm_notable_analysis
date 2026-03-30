# SPL Query RAG Grounding Implementation Plan

## Purpose

Add a second, optional capability for per-hypothesis SPL generation that uses retrieval grounding from the on-prem knowledge base so generated SPL can be more accurate, more precise, and traceable to specific source sections.

This plan builds on the existing SPL query generation feature and adds retrieval-backed grounding for Splunk-specific guidance.

The goal is to move from:

- "Here is the best SPL query for this hypothesis."

to:

- "Here is the best SPL query for this hypothesis, and here are the exact knowledge-base sections that justified its Splunk-specific details."

## Why This Is Needed

Current SPL generation is effectively stateless LLM generation constrained by anti-hallucination rules.

That is useful, but limited:

- it cannot safely emit environment-specific indexes, sourcetypes, macros, or data-model references
- it cannot point analysts to the exact internal references that informed the query
- it cannot use prior curated SPL examples from the knowledge base to improve precision

RAG grounding should close that gap.

## Scope

This capability is for the structured on-prem analyzer path only:

- in scope: `llm_notable_analysis_onprem/onprem_service/local_llm_client.py`
- out of scope for v1: `freeform_llm_client.py`

This plan assumes the existing SPL generation feature already exists behind:

- `SPL_QUERY_GENERATION_ENABLED`

This new capability adds a second gate for retrieval-grounded SPL:

- `SPL_QUERY_RAG_ENABLED`

## Recommended Feature Flag Design

### Required flags

- `SPL_QUERY_GENERATION_ENABLED=false`
- `SPL_QUERY_RAG_ENABLED=false`

### Expected behavior

When `SPL_QUERY_GENERATION_ENABLED=false`:

- no SPL generation
- `SPL_QUERY_RAG_ENABLED` has no effect

When `SPL_QUERY_GENERATION_ENABLED=true` and `SPL_QUERY_RAG_ENABLED=false`:

- current stateless SPL generation behavior applies
- no KB grounding references are required
- use the existing non-RAG SPL workflow only
- do not perform the extra grounded-SPL LLM call

When `SPL_QUERY_GENERATION_ENABLED=true` and `SPL_QUERY_RAG_ENABLED=true`:

- the system first runs the normal structured analysis call to generate the alert assessment and 6 hypotheses
- the system then retrieves SPL-relevant context from the dedicated SPL corpus using those generated hypotheses
- the system performs a second LLM call dedicated to grounded SPL generation
- each hypothesis query must cite the retrieved sections it relied on
- Splunk-specific tokens may only be emitted when justified by retrieved context or explicit alert facts

## Retrieval Source

### SPL grounding corpus source

The SPL-grounding corpus should build from:

- `/opt/llm-notable-analysis/knowledge_base/spl_query_source_docs`

Supported source formats:

- `.docx`
- `.txt`

Indexed artifacts:

- `spl_query_kb.sqlite3`
- `spl_query_kb.faiss`
- `chunks.jsonl`
- `ingest_report.json`

### What SPL grounding should retrieve

The knowledge base should contain Splunk-specific operational references such as:

- index inventory
- sourcetype inventory
- CIM / data model guidance
- approved macros
- saved-search examples
- field mapping notes
- investigation playbook examples
- customer-specific search conventions

### Important note

FAISS is not the human-readable source of truth for provenance.

For analyst-visible grounding, the citations should come from the chunk metadata stored in SQLite and retrieval structures:

- `source_file`
- `section_path`

This is already how the current RAG system tracks snippet provenance.

## Provenance Model

The current retrieval layer already exposes provenance-friendly fields on snippets:

- `source_file`
- `section_path`
- excerpt text

This is enough to support section-level SPL grounding references.

Recommended user-visible reference shape:

```json
{
  "source_file": "splunk_field_mappings.docx",
  "section_path": "Windows Authentication > Common Fields"
}
```

Optional internal-only metadata:

- chunk row id
- fused rank
- lexical rank
- vector rank

Those may be useful for debugging but do not need to appear in the report.

## Recommended Architecture

### High-level flow

1. Run the first LLM call using the existing structured-analysis workflow.
2. Parse the first-call output and require:
   - the alert assessment
   - the 6 competing hypotheses
3. Build hypothesis-aware retrieval queries for SPL grounding from the first-call output.
4. Retrieve relevant KB snippets from the separate SPL-grounding corpus/index.
5. Construct a dedicated `SPL_QUERY_GROUNDING_CONTEXT` block.
6. Run a second LLM call dedicated to grounded SPL generation using:
   - current alert facts
   - first-call hypothesis output
   - retrieved SPL grounding context
7. Have the second call generate:
   - one grounded SPL query per hypothesis
   - grounding summary per hypothesis
   - grounding refs per hypothesis
8. Validate that any Splunk-specific tokens used in the query are supported by the retrieved context.

### Recommended implementation pattern

Do not overload the current general SOC context block for this feature.

Instead, create a second retrieval path specifically for SPL grounding, for example:

- existing: `SOC_OPERATIONAL_CONTEXT`
- new: `SPL_QUERY_GROUNDING_CONTEXT`

This separation keeps:

- general analyst doctrine grounding
- Splunk-environment grounding

from getting mixed together.

This helper/renderer split is required for implementation:

- keep the current general SOC context helper/renderer for `SOC_OPERATIONAL_CONTEXT`
- add a dedicated SPL grounding helper/renderer for `SPL_QUERY_GROUNDING_CONTEXT`

## Prompt Contract Changes

When `SPL_QUERY_RAG_ENABLED=true`, add a dedicated prompt block such as:

- `SPL_QUERY_GROUNDING_CONTEXT`

Prompt rules should say:

- use retrieved SPL grounding only as operational/query guidance
- do not invent Splunk tokens not present in alert facts or retrieved grounding
- every environment-specific SPL detail must be traceable to retrieved context
- cite the grounding references used for each query

### Per-hypothesis additions

Extend each hypothesis with:

- `primary_spl_query_grounding_refs`
  - list of section references used for the query
- `primary_spl_query_grounding_summary`
  - short note on how retrieved context influenced the query

Suggested shape:

```json
{
  "hypothesis_type": "adversary",
  "hypothesis": "Suspicious PowerShell activity from a compromised endpoint",
  "query_strategy": "resolve_unknown",
  "primary_spl_query": "...",
  "why_this_query": "...",
  "supports_if": "...",
  "weakens_if": "...",
  "primary_spl_query_grounding_summary": "Used customer field mapping guidance and prior saved-search pattern for endpoint process hunting.",
  "primary_spl_query_grounding_refs": [
    {
      "source_file": "splunk_saved_searches.txt",
      "section_path": "Endpoint Process Investigation"
    },
    {
      "source_file": "field_mapping_windows.docx",
      "section_path": "Process Creation Fields"
    }
  ]
}
```

## Retrieval Strategy

### Query input for retrieval

Because this design uses two intentional LLM calls, retrieval can be based on
the first-call hypothesis output.

The retrieval query should combine:

- raw alert text
- hypothesis text
- evidence support
- evidence gaps
- best pivots
- query strategy

This gives retrieval enough signal to find the most relevant Splunk references
for each hypothesis before the grounded SPL generation call.

### Recommended retrieval profile

Use a tighter, SPL-focused retrieval profile than the general SOC context path:

- fewer snippets
- smaller context budget
- stronger prioritization of Splunk/field/search examples

This may require:

- a dedicated retrieval helper
- or a new method on the existing provider

Recommended new method:

- `build_spl_query_context(...)`

It should return structured snippets, not just a single rendered string.
This method should accept hypothesis-aware inputs derived from the first LLM
call.

## Validation and Anti-Hallucination

This feature should relax the current anti-hallucination restrictions only when retrieval provides justification.

### Current stateless restrictions

Today the SPL validator blocks:

- assumed indexes
- assumed sourcetypes
- assumed macros
- assumed CIM/data models

### New grounded behavior

When `SPL_QUERY_RAG_ENABLED=true`, a Splunk-specific token is allowed only if:

1. it appears in retrieved grounding context, or
2. it appears explicitly in the alert input

### Additional checks

Validation should ensure:

- every hypothesis still has exactly one query
- every query still uses only `resolve_unknown` or `check_contradiction`
- every hypothesis has at least one grounding ref when environment-specific tokens are used
- every cited ref exists in the retrieved context set for that alert
- any cited `source_file` and `section_path` pair must match actual retrieved snippet metadata

### Failure behavior

Recommended behavior:

- if SPL generation succeeds but grounding refs are missing or invalid, suppress the grounded SPL block for that alert
- do not fabricate references
- do not fabricate environment-specific SPL
- preserve the rest of the analysis if valid

## Report Placement

Keep grounded SPL under each hypothesis.

Recommended report layout per hypothesis:

- hypothesis
- evidence support
- evidence gaps
- query strategy
- primary SPL query
- why this query
- supports hypothesis if
- weakens hypothesis if
- SPL grounding summary
- SPL grounding refs

Example rendering:

- `Grounding summary: Used saved-search example and field mapping guidance from the KB.`
- `Grounding refs: [splunk_saved_searches.txt :: Endpoint Process Investigation], [field_mapping_windows.docx :: Process Creation Fields]`

Do not dump raw retrieved excerpts directly into the report unless explicitly requested later.

## Configuration Design

### Required new config

- `SPL_QUERY_RAG_ENABLED: bool = False`

### Required separate SPL corpus paths

The SPL-grounding feature uses a separate SPL-focused corpus and separate index files.

Required config:

- `SPL_QUERY_RAG_SQLITE_PATH`
- `SPL_QUERY_RAG_FAISS_PATH`

Recommended self-documenting corpus locations:

- source docs: `knowledge_base/spl_query_source_docs/`
- index artifacts: `knowledge_base/spl_query_index/`

Optional later tuning:

- `SPL_QUERY_RAG_MAX_SNIPPETS`
- `SPL_QUERY_RAG_CONTEXT_BUDGET_CHARS`

## Files Likely To Modify

### Core app

- `llm_notable_analysis_onprem/onprem_service/config.py`
  - add `SPL_QUERY_RAG_ENABLED`
- `llm_notable_analysis_onprem/config.env.example`
  - document the new flag
- `llm_notable_analysis_onprem/README.md`
  - document the feature and how it interacts with existing RAG/SPL flags
- `llm_notable_analysis_onprem/onprem_service/local_llm_client.py`
  - add SPL-grounding prompt block
  - add retrieval invocation
  - add grounding-aware validation
  - add citation/ref handling
- `llm_notable_analysis_onprem/onprem_service/markdown_generator.py`
  - render grounding summary and refs per hypothesis

### Retrieval layer

- `onprem_rag/future/retrieval.py`
  - add a dedicated retrieval method for SPL grounding that returns structured snippets/refs
- `onprem_rag/future/prompt_context_builder.py`
  - add a dedicated renderer/helper for `SPL_QUERY_GROUNDING_CONTEXT`
- `onprem_rag/future/rag_config.py`
  - add SPL-specific retrieval settings/paths as needed

### Tests

- `llm_notable_analysis_onprem/tests/onprem_service/test_local_llm_client_contract.py`
- `llm_notable_analysis_onprem/tests/onprem_service/test_markdown_generator.py`
- new retrieval-focused tests under `onprem_rag/future/tests` or existing test location if available

## Suggested Implementation Phases

### Phase 1: Feature flag and retrieval plumbing

- add `SPL_QUERY_RAG_ENABLED`
- wire flag behavior
- add `SPL_QUERY_RAG_SQLITE_PATH`
- add `SPL_QUERY_RAG_FAISS_PATH`
- create dedicated SPL retrieval method returning structured refs

### Phase 2: Prompt and schema contract

- add `SPL_QUERY_GROUNDING_CONTEXT`
- require `primary_spl_query_grounding_summary`
- require `primary_spl_query_grounding_refs`

### Phase 3: Validation

- enforce reference presence/shape
- ensure cited refs came from retrieved snippets
- only allow Splunk-specific tokens when grounded

### Phase 4: Markdown rendering

- render per-hypothesis grounding summary and refs
- render a concise note when SPL grounding was requested but unavailable

### Phase 5: Corpus curation

- curate Splunk-specific source docs into `knowledge_base/spl_query_source_docs`
- validate that retrieval returns useful section-level matches for real hypotheses

## Recommended Corpus Curation Guidelines

To make this feature actually useful, the KB should include documents such as:

- Splunk index inventory
- sourcetype reference sheets
- CIM/data model usage notes
- macro reference docs
- customer-approved investigation searches
- field mapping docs by log source
- "known good" saved-search examples for common hypothesis types

These docs should use clear section headings so chunk provenance is meaningful.

Good example:

- `splunk_saved_searches.txt`
  - `Authentication > Failed Logon Investigation`
  - `Endpoint > PowerShell Triage`

Bad example:

- one giant unstructured note dump with no headings

## Locked Decisions

The following decisions are locked for implementation:

- `SPL_QUERY_RAG_ENABLED` requires `SPL_QUERY_GENERATION_ENABLED=true`
- grounded SPL mode uses two intentional LLM calls
- call 1 uses the existing structured-analysis workflow
- call 2 is only for grounded SPL generation
- retrieval for SPL grounding runs between call 1 and call 2
- retrieval uses first-call hypothesis output plus alert facts
- use a separate SPL-focused corpus and separate index files
- configure those via:
  - `SPL_QUERY_RAG_SQLITE_PATH`
  - `SPL_QUERY_RAG_FAISS_PATH`
- user-visible grounding refs are shown inline under each hypothesis/query only
- user-visible grounding refs must include:
  - `source_file`
  - `section_path`
- no `reason` field is required in the grounding ref contract
- FAISS remains an internal retrieval mechanism, not the user-facing citation target
- SQLite-backed chunk metadata/provenance is the source for displayed refs
- grounded SPL is allowed to use environment-specific tokens only when supported by retrieved context or explicit alert facts
- token support validation uses normalized token matching rather than strict exact-match
- if grounding is requested but unavailable, suppress grounded SPL rather than inventing refs, inventing environment-specific tokens, or silently falling back to stateless SPL
- when `SPL_QUERY_RAG_ENABLED=false`, do not perform retrieval from the SPL corpus and do not make the second LLM call
- keep the helper/renderer split:
  - general SOC context helper/renderer for `SOC_OPERATIONAL_CONTEXT`
  - dedicated SPL grounding helper/renderer for `SPL_QUERY_GROUNDING_CONTEXT`

## Outcome

If implemented, this feature will give you:

- optional retrieval-grounded SPL generation
- per-hypothesis KB-backed justification
- section-level provenance for analyst review
- a cleaner bridge between your current on-prem RAG stack and precise Splunk query generation
