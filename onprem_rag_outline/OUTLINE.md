# On-Prem RAG Grounding Specification

## Purpose

This directory contains the implementation specification for adding on-prem retrieval grounding to the on-prem notable analysis service.

The goal is to improve operationally useful outputs in `LocalLLMClient` while preserving the current response schema and keeping all evidence-bearing outputs strictly alert-grounded.

## Scope

This specification is for the on-prem path only.

In scope:

- prompt grounding for `llm_notable_analysis_onprem`
- local, air-gapped retrieval
- hybrid retrieval across free-text documents
- implementation planning in a new directory only

Out of scope for now:

- modifying existing analyzer code
- changing the current JSON schema
- project-wide cloud/on-prem unification
- final corpus taxonomy details

## Current Constraints And Inputs

- Corpus size is currently expected to be about 200 Word documents.
- Median document size is a few pages.
- Corpus is roughly 70% free text.
- Documents are updated or added only a few times per year.
- Environment is on-prem and air-gapped.
- The corpus is Splunk-heavy, but also contains guidance for other common SOC tools such as CrowdStrike and Microsoft products.
- Latency target is loose enough that a simple single-node design is acceptable; there is no need to optimize for a highly distributed retrieval system.

## Agreed Baseline

The current best-fit retrieval baseline for this use case is:

- `SQLite` for local structured storage
- `FTS5` for keyword retrieval
- `FAISS` for vector retrieval over free-text chunks

This is the agreed retrieval model:

1. Run hybrid retrieval over the corpus (`FTS5` + `FAISS`).
2. Inject only the minimum useful operational context into the prompt.
3. Keep evidence-bearing outputs alert-grounded.

## Non-Negotiable Guardrails

Retrieved SOC context may improve operational guidance, but it must never be treated as direct alert evidence.

The following must remain strictly alert-grounded:

- `evidence_vs_inference.evidence`
- `ttp_analysis[*].evidence_fields`
- `ioc_extraction`

SOC-local context is guidance only. It may improve:

- `alert_reconciliation.recommended_actions`
- `alert_reconciliation.decision_drivers`
- `competing_hypotheses[*].best_pivots`

If grounding is weak, empty, or conflicting:

- prefer generic guidance
- explicitly say `unknown` where needed
- do not invent actions, evidence, pivots, or IOCs

## Existing Components To Reuse By Reference

This specification assumes future work will reuse the current on-prem analyzer code by import or by direct reference, not by copying logic into production blindly.

Primary reference files:

- `llm_notable_analysis_onprem/onprem_service/local_llm_client.py`
- `llm_notable_analysis_onprem/onprem_service/onprem_main.py`
- `llm_notable_analysis_onprem/onprem_service/ingest.py`
- `llm_notable_analysis_onprem/onprem_service/markdown_generator.py`
- `llm_notable_analysis_onprem/README.md`
- `llm_notable_analysis_onprem/s3_notable_pipeline_onprem_airgapped_workflow.md`
- `s3_notable_pipeline/ttp_analyzer.py`

Key reuse intent:

- preserve the existing alert normalization path
- preserve the existing prompt contract and response schema
- add retrieval context before prompt assembly rather than redesigning the analyzer output

## Proposed Future Directory Shape

This is the target module shape for the enhancement. It can live under a dedicated directory without touching the existing analyzer package.

```text
onprem_rag/
  OUTLINE.md
  knowledge_base/
    source_docs/
    index/
  future/
    rag_config.py
    corpus_ingest.py
    chunking.py
    keyword_index.py
    vector_index.py
    retrieval.py
    prompt_context_builder.py
    evaluation/
      gold_set.md
      scoring_rubric.md
```

## File Responsibilities

The future files above are intentional and each has a clear role.

- `future/rag_config.py`
  - central config for corpus paths, chunking, and retrieval limits
- `future/corpus_ingest.py`
  - parses source documents (starting with Word docs) and extracts normalized text
  - writes normalized document/chunk records into SQLite
- `future/chunking.py`
  - applies section-aware chunking for prose
  - preserves query/macro blocks as atomic units when needed
- `future/keyword_index.py`
  - manages SQLite schema and FTS5 virtual tables
  - implements keyword retrieval over corpus text
- `future/vector_index.py`
  - builds/loads embeddings for chunks
  - manages FAISS index build and vector search
- `future/retrieval.py`
  - orchestrates end-to-end retrieval flow:
    - hybrid retrieval (`FTS5` + `FAISS`)
    - score fusion
    - weak/conflicting-context handling
- `future/prompt_context_builder.py`
  - builds bounded `SOC_OPERATIONAL_CONTEXT` prompt block from retrieval outputs
  - enforces context labeling as guidance (not evidence)
- `future/evaluation/gold_set.md`
  - defines representative alerts, allowed behavior, and prohibited behavior
- `future/evaluation/scoring_rubric.md`
  - defines pass/fail scoring for usefulness vs fabrication/evidence leakage

## Planned Software Packages

This section explicitly identifies the package plan for implementation.

### Core runtime (planned)

- `vllm` (on-prem LLM serving for `gpt-oss-120b` or `gpt-oss-20b`)
- `faiss-cpu` (or `faiss-gpu` only if GPU indexing/search is required on-prem)
- `sentence-transformers` (local embeddings for free-text semantic retrieval)
- `numpy` (FAISS/embedding array operations)
- `python-docx` and/or `docx2txt` (Word document text extraction)

### Existing/built-in components leveraged

- `sqlite3` (Python standard library; SQLite + FTS5 backend)

### Optional packages (only if testing shows need)

- `onnxruntime` (embedding inference optimization in constrained environments)

Package versions should be pinned during implementation after compatibility testing in the target air-gapped runtime.

## Locked Implementation Decisions (v1)

This section locks the previously open handoff decisions so implementation can proceed consistently across customer deployments.

### Supported LLM Profiles (vLLM)

Customers may run either:

- `gpt-oss-120b` via vLLM
- `gpt-oss-20b` via vLLM

Default implementation profile for v1:

- `gpt-oss-120b`

Alternate profile for constrained environments:

- `gpt-oss-20b`

Both profiles use the same retrieval backend (`SQLite + FTS5 + FAISS`) and the same evidence guardrails.

### 1) Embedding Model And Vector Runtime (Shared)

For both `gpt-oss-120b` and `gpt-oss-20b` deployments:

- Embedding model: `sentence-transformers/all-MiniLM-L6-v2`
- Embedding dimension: `384`
- Vector normalization: L2-normalize embeddings before indexing and querying
- FAISS index type: `IndexFlatIP` (cosine similarity on normalized vectors)
- Runtime target: CPU-first baseline
- Air-gapped packaging: pre-stage model artifacts offline and pin checksum/version in deployment bundle

### 2) Ingestion/Update Semantics (Shared)

For v1, ingestion mode is explicitly:

- full rebuild on each manual ingestion run (no incremental update logic in v1)
- source directory is source of truth
- removed/renamed source docs are removed from rebuilt index output
- atomic publish behavior: only replace live index artifacts if full ingestion completes successfully
- v1 wording rule: "full rebuild" is authoritative; do not implement partial/incremental update behavior

### 3) `SOC_OPERATIONAL_CONTEXT` Contract (Per LLM Profile)

Common formatting for both:

- labeled block header: `SOC_OPERATIONAL_CONTEXT`
- numbered snippets with provenance: `[source_file :: section_path] <excerpt>`
- coherent excerpts only (do not clip mid-query or mid-procedure step)

Context budget accounting rule (shared):

- budget includes the entire rendered block content:
  - header line
  - numbering
  - provenance wrapper (`[source_file :: section_path]`)
  - excerpt text
  - newline separators
- budget counting is based on Python `len()` over the final rendered context string

Overflow handling rule (shared):

- apply snippets in ranked order
- include a snippet only if it fits fully within remaining budget
- do not clip mid-query or mid-step to force fit
- if a candidate cannot fit coherently, skip it and evaluate the next candidate
- if no coherent snippet fits within budget, send empty `SOC_OPERATIONAL_CONTEXT`

Profile-specific context budgets:

- `gpt-oss-120b`:
  - max snippets: `5`
  - max total context length: about `2200` characters
- `gpt-oss-20b`:
  - max snippets: `4`
  - max total context length: about `1600` characters

For default v1 deployments, apply the `gpt-oss-120b` profile values unless a customer explicitly selects `gpt-oss-20b`.

### 4) Initial Weak/Conflicting Context Quality Gate (Per LLM Profile)

Common selection flow:

1. take fused hybrid candidates (`FTS5 + FAISS`)
2. remove near-duplicates
3. apply model profile quality gate
4. keep only passing snippets up to profile context budget

Near-duplicate rule (shared):

- similarity method: cosine similarity over L2-normalized `all-MiniLM-L6-v2` embeddings of candidate excerpt text
- drop candidate if near-duplicate similarity is `>= 0.80` vs already selected snippet

Alert-term normalization and overlap basis (shared):

- case-fold to lowercase
- collapse repeated whitespace
- tokenize on whitespace, trim leading/trailing punctuation, and preserve internal indicator characters (`.`, `_`, `-`, `/`, `:`, `@`)
- remove stopwords using a fixed English stopword set shipped with the service
- high-signal alert terms include:
  - extracted entities from alert cues (IP, domain, hostname, username/account, process name, hash, URL)
  - detection-name tokens that remain after normalization and stopword removal
  - suspicious action tokens from a fixed v1 allowlist in `future/retrieval.py`
- overlap calculation uses unique normalized non-stopword token intersection count
- "meaningful token overlap >= 2" means intersection count is at least 2

Initial profile gates:

- `gpt-oss-120b` gate:
  - candidate must be in fused top `8`
  - and must satisfy at least one:
    - contains at least 1 high-signal alert token match (entity, detection term, or suspicious action term), or
    - has meaningful token overlap `>= 2` with alert query cues

- `gpt-oss-20b` gate (stricter to reduce weak-context injection):
  - candidate must be in fused top `6`
  - and must contain at least 1 high-signal alert token match

For default v1 deployments, apply the `gpt-oss-120b` quality gate unless a customer explicitly selects `gpt-oss-20b`.

Empty-context fallback (shared):

- if no snippet passes gate, send empty `SOC_OPERATIONAL_CONTEXT`
- downstream analysis should remain broad and explicitly use `unknown` where specificity is not supported

## Corpus Paths, Formats, And Manual Ingestion

Use these production baseline paths for v1 (RHEL 8/9):

- Source documents (you place files here):
  - `/opt/llm-notable-analysis/knowledge_base/source_docs/`
- Ingestion outputs:
  - `/opt/llm-notable-analysis/knowledge_base/index/kb.sqlite3`
  - `/opt/llm-notable-analysis/knowledge_base/index/kb.faiss`
  - `/opt/llm-notable-analysis/knowledge_base/index/chunks.jsonl`
  - `/opt/llm-notable-analysis/knowledge_base/index/ingest_report.json`
- Backups/snapshots:
  - `/opt/llm-notable-analysis/knowledge_base/backups/`
- Logs:
  - `/var/log/llm-notable-analysis/`

Accepted source formats for v1:

- `.docx`
- `.txt`

Manual ingestion command (Linux/RHEL 8/9, v1):

```shell
python3 "/opt/llm-notable-analysis/onprem_rag/future/corpus_ingest.py" \
  --source "/opt/llm-notable-analysis/knowledge_base/source_docs" \
  --sqlite "/opt/llm-notable-analysis/knowledge_base/index/kb.sqlite3" \
  --faiss "/opt/llm-notable-analysis/knowledge_base/index/kb.faiss" \
  --chunks-jsonl "/opt/llm-notable-analysis/knowledge_base/index/chunks.jsonl" \
  --report "/opt/llm-notable-analysis/knowledge_base/index/ingest_report.json"
```

Output locations are for these artifacts:

- `kb.sqlite3`: canonical chunk records plus FTS5 index backing store
- `kb.faiss`: semantic vector index for retrieval
- `chunks.jsonl`: inspectable export of normalized chunks used for indexing
- `ingest_report.json`: ingestion summary (processed/skipped/errors) for operator review

## Knowledge Base Maintenance (Operations)

Baseline maintenance flow:

1. Add/update/remove `.docx` or `.txt` files in `source_docs`.
2. Run the manual ingestion command.
3. Check `ingest_report.json` for conversion/indexing errors.
4. Run a quick retrieval smoke test on 2-3 known prompts.
5. If results degrade, fix source docs and rerun ingestion.

What happens when ingestion runs:

- source files are parsed into normalized text/chunks
- SQLite and FAISS indexes are fully rebuilt from source docs (no incremental updates in v1)
- retrieval immediately uses the latest indexed corpus on next analysis run

## Target Data Model

The baseline retrieval layer uses one logical store: free-text document chunks.

### Free-Text Knowledge Store

Use for:

- SOPs
- runbooks
- KBs
- procedural walkthroughs
- investigation guides
- Splunk triage guidance
- false-positive guidance

Suggested record shape:

```json
{
  "doc_id": "string",
  "chunk_id": "string",
  "title": "string",
  "section_path": "optional string",
  "source_file": "string",
  "text": "chunk text"
}
```

Optional enrichment fields can be added later if needed, but baseline does not require lifecycle metadata or deterministic lookup tables.

## Optional Add-Ons (Later Phase)

If needed later (as corpus grows), consider:

- lifecycle metadata fields (`active`, `valid_from`, `valid_to`, `last_reviewed`)
- deterministic lookup tables for exact routing/mappings

## Retrieval Flow

### Step 1. Parse Alert Context

Extract only the minimum alert cues needed to build a retrieval query:

- alert or detection name if available
- user / host / IP / process indicators
- suspicious activity terms from the alert text

### Step 2. Run Hybrid Retrieval Over The Corpus

Run retrieval over corpus chunks using:

- `FTS5` for exact terms and SOC vocabulary
- `FAISS` for semantic similarity

Fuse results with a simple strategy such as:

- reciprocal rank fusion, or
- weighted keyword/vector score merge

No reranker is required for the first implementation unless quality testing shows a clear need.

### Step 3. Build A Small Operational Context Block

Inject snippets according to the locked profile contract in
`Locked Implementation Decisions (v1)`.

The prompt context should be clearly labeled as operational guidance, not alert evidence.

### Step 4. Enforce Retrieval-Miss Behavior

If retrieval returns weak or conflicting context:

- keep recommendations generic
- say `unknown` when specificity would be speculative
- do not fabricate evidence or new IOCs

Use the locked quality gate in `Locked Implementation Decisions (v1)` to decide
whether context is weak enough to send an empty context block.

## Prompt Integration Strategy

The likely integration point is immediately before prompt assembly in the current on-prem analyzer flow.

Conceptually:

1. build normalized `alert_text`
2. derive retrieval query inputs from that alert
3. fetch hybrid retrieval context
4. append a labeled `SOC_OPERATIONAL_CONTEXT` block
5. call the current prompt builder

Important prompt rule:

- retrieved context may inform investigation guidance
- retrieved context may not be cited as proof of what happened in the alert

## Chunking Strategy

Initial chunking guidance:

- prefer section-aware chunking by headings when possible
- target roughly 300 to 700 words per chunk
- keep Splunk searches, macros, and exact query examples intact as single units where practical
- use minimal overlap
- preserve title and section path metadata

## Conflict Handling And Corpus Curation

Baseline assumption: documents are curated before entering the knowledge base.
No lifecycle metadata is required for v1.

When retrieved snippets appear to disagree:

- do not force a specific recommendation from conflicting text
- surface generic guidance and mark specifics as `unknown`
- preserve evidence guardrails (no fabricated evidence or IOCs)

## Evaluation Plan

Before implementation is considered production-ready, create a small gold set.

Minimum goals:

- verify `recommended_actions` become more specific without becoming fabricated
- verify `decision_drivers` become more operationally relevant
- verify `best_pivots` become more environment-appropriate
- verify evidence-bearing fields stay alert-grounded
- verify retrieval misses do not create false certainty

Suggested gold set structure:

- 2 alerts per topic:
  - 1 true positive case
  - 1 false positive case
- total alerts = `2 x number_of_topics`
- topic mix should still cover identity, endpoint, network, and Splunk-heavy workflows
- expected allowed outputs vs prohibited behaviors

Suggested pass criteria:

- no RAG-only evidence leakage
- no fabricated IOCs
- false-positive cases must not be presented with false certainty
- clearly improved operational usefulness on a reviewed subset

## Implementation Phases

### Phase 0. Planning

- finalize corpus categories later
- define simple ingestion inputs and output paths

### Phase 1. Offline Ingestion Prototype

- parse Word docs into text
- store free-text chunks in SQLite
- build FTS5 index
- build FAISS index

### Phase 2. Retrieval API

- implement hybrid retrieval and score fusion
- implement retrieval-miss logic

### Phase 3. Prompt Grounding Integration

- append operational context into prompt assembly
- keep schema unchanged
- enforce evidence guardrails in prompt instructions

### Phase 4. Evaluation

- run gold-set tests
- measure specificity vs fabrication risk
- tune retrieval thresholds

### Phase 5. Productionization

- batch refresh indexes when documents change
- add internal logging for retrieval health
- add maintenance procedure for corpus updates

## Optional Refinements

These can improve retrieval quality later, but they are not blockers for this specification:

- expanded document category taxonomy
- lifecycle metadata fields (`active`, `valid_from`, `valid_to`, `last_reviewed`)
- deterministic lookup tables for exact routing/mappings

## Decision Summary

The current sign-off position is:

- keep the on-prem `LocalLLMClient` schema unchanged
- default to `gpt-oss-120b` via vLLM, with `gpt-oss-20b` supported as an alternate profile
- use `SQLite + FTS5 + FAISS` for hybrid free-text retrieval
- keep evidence-bearing outputs strictly alert-grounded
- use retrieved SOC context only as operational guidance
- enforce `unknown` on weak grounding
- validate the design with a gold set before production rollout
