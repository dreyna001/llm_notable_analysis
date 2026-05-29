# LLM Workflow and Harness Position

This repository contains bounded LLM workflows for notable analysis. The system
can be exercised by validation, smoke, integration, and replay harnesses, but
the production analyzer itself is not an open-ended agentic runtime.

## Position

The most accurate description is:

> A bounded analyst-assist LLM workflow with RAG grounding, policy-gated query
> execution, structured validation, and harness support for testing, smoke
> validation, and replay.

This framing is intentionally more precise than calling the system an
“agentic harness.”

## What the Workflow Does

The analyzer follows an application-controlled path:

1. Accept one notable or alert payload.
2. Normalize the input into a stable internal shape.
3. Add bounded advisory context, such as RAG knowledge base snippets, when
   enabled.
4. Call the configured LLM with a controlled prompt and output contract.
5. Parse, validate, and optionally repair the model response.
6. Optionally generate or execute read-only Splunk queries behind deterministic
   policy gates.
7. Produce analyst-facing reports and optional approved writeback outputs.

The application controls this sequence. The model does not freely choose goals,
select arbitrary tools, plan unbounded actions, or iterate until it decides the
task is complete.

## Future Notable Archive Assistant

The planned Notable Archive Assistant / Case Q&A surface is still consistent
with this position when implemented as a bounded read-only assistant workflow.
One user question may coordinate several application-controlled retrieval steps,
but those steps should be explicit and constrained:

1. Retrieve retained case metadata, reports, snippets, or validated JSON from
   the 90-day case archive.
2. Retrieve advisory customer context from the existing RAG/SPL knowledge base,
   such as SOPs, Splunk index/field/macro references, detection notes, and
   threat-hunting playbooks.
3. Call the configured LLM only for bounded answer synthesis over retrieved
   sources.
4. Return citations to case evidence and advisory context, or return `unknown`
   / no-match when retrieval is weak.

This is acceptable to describe as a bounded read-only assistant workflow or
retrieval agent. It should not be described as an open-ended autonomous SOC
agent. The assistant must not execute SPL, call external systems, re-run
analysis, create tickets, trigger SOAR, update cases, or answer from broad model
memory.

## What Harnesses Exist

Harnesses sit around the workflow. They run the same analyzer path with
controlled inputs, dependencies, and assertions.

- `llm_notable_analysis_onprem_systemd/scripts/smoke_postgres_rag.sh` is a
  Docker-backed validation harness for the Postgres/pgvector RAG path.
- `llm_notable_analysis_onprem_systemd/scripts/smoke_service_chain.sh` validates
  the deployed service chain from vLLM to LiteLLM to analyzer report output.
- `s3_notable_pipeline/scripts/test-pipeline.ps1` acts as an AWS integration
  harness by uploading a sample notable to S3 and checking generated output.
- Unit and contract tests provide deterministic harness coverage for parsers,
  validators, routing, policy behavior, and output contracts.

Future batch replay or evaluation tooling would also be a harness: it would feed
historical or fixture notables through the existing workflow and compare outputs
or metrics across versions.

## Why This Is Not Automatically Agentic

RAG, a knowledge base, generated SPL, and bounded query execution make the
workflow tool-augmented and grounded. They do not, by themselves, make it
agentic.

An agentic harness would normally give the model or agent more control over the
loop: choosing tools, deciding next steps, changing strategy from observations,
and determining when to stop. This system intentionally keeps those decisions in
deterministic application logic and policy gates.

## LangGraph and Human-in-the-Loop Fit

If this system had to adopt a LangChain-family runtime, LangGraph would be the
better fit than LangChain because it provides explicit graph/state-machine
primitives. Its strongest value is in workflows that need durable checkpoints,
human-in-the-loop pauses, analyst edits, approvals, resumptions, node-level
retry, and inspection of intermediate state.

That is not the default shape of this product today. The current design is a
backend, mostly hands-off notable-processing workflow. It is meant to process SOC
volume without making every notable an interactive human bottleneck. Human input
belongs at consequential boundaries such as writeback, ticket creation,
suppression, or response actions, not in the hot path for every analysis.

The practical threshold for adopting LangGraph is when orchestration state itself
becomes a product problem: checkpoint tables, resume tokens, approval interrupts,
node retry policy, fan-out/fan-in enrichment, and graph execution traces. Until
then, maturing the direct Python application keeps the workflow simpler, easier
to audit, and better aligned with backend throughput.

## Recommended Language

Use:

- “bounded LLM workflow”
- “analyst-assist workflow”
- “RAG-grounded notable analysis workflow”
- “policy-gated query execution”
- “validation, smoke, integration, or replay harness”
- “harnessed LLM workflow”

Avoid unless intentionally adding autonomous behavior:

- “open-ended agent”
- “agentic runtime”
- “agentic harness”
- “autonomous investigation agent”

