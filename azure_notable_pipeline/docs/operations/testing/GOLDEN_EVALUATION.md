# Golden evaluation

## Purpose

Golden evaluation protects deterministic contracts around model-assisted
analysis. It is not a claim that three fixtures represent production quality.
The shipped manifest is `data/golden_eval/manifest.json` and currently covers
an obvious true positive, an approved administrative false positive, and a
sparse unknown case.

## Evaluation rules

For each case, compare the output with the reference while keeping these
boundaries strict:

- verdict must match the expected enum;
- direct evidence must be present and distinguishable from inference;
- unsupported facts, TTP IDs, and IOCs are omitted or marked unknown;
- the one-sentence summary and decision drivers stay bounded and case-grounded;
- competing hypotheses include evidence gaps rather than invented certainty;
- generated SPL/Elasticsearch queries pass the read-only policy before execution;
- recommended actions remain advisory unless a separate human approval gate is
  satisfied.

## Test procedure

1. Pin the Azure OpenAI deployment, API version, prompt/schema version, and
   local MITRE catalog version in the evaluation record.
2. Run deterministic rubric tests offline first.
3. Run a customer-approved model evaluation with synthetic fixtures and capture
   raw output hash, parsed output, validator result, latency, and token usage.
4. Review every mismatch by category: evidence, verdict, TTP, IOC, query,
   schema, or policy.
5. Do not promote a prompt/model change on aggregate score alone; investigate
   unknown-to-confident and benign-to-malicious regressions first.

## Expansion and thresholds

Customers should add sanitized cases for their telemetry, approved admin
activity, sparse evidence, duplicate delivery, malformed payload, and action
approval boundaries. Store references outside this repository when they contain
customer data. Set release thresholds in the customer evaluation record,
including maximum severe regressions, schema failure rate, and unknown handling.
There is no universal production-quality threshold in this source tree.
