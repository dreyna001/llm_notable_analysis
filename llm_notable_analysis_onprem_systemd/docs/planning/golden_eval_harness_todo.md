# Golden Evaluation Harness TODO

## Status

Planning TODO for a future `llm_notable_analysis_onprem_systemd` quality and
regression harness. This is not a runtime contract yet.

## Goal

Add an automated evaluation harness that can run against the deployed analyzer
and future Notable Archive Assistant on a regular cadence, such as weekly, to
detect quality regressions that unit tests and smoke tests do not catch.

The existing tests prove contracts, validators, retrieval plumbing, policy
gates, and service health. This harness should evaluate whether the produced
analysis and assistant answers are grounded, useful, and stable against a
representative set of known cases.

Long term, every feature surface that can be meaningfully evaluated should get
golden coverage, with separate fixtures and rubrics added as each capability
stabilizes.

## TODO

- Build a representative notable corpus with expected outcomes and rubrics.
- Include true positives, false positives, benign administrative activity,
  noisy low-confidence alerts, weak-signal alerts, malformed or sparse inputs,
  and cases where the correct answer is `unknown` or no-match.
- Pair each notable or assistant question with expected source evidence,
  expected advisory KB/SOP references, and acceptable answer properties.
- Add hallucination scoring that checks whether answers introduce unsupported
  facts, cite missing sources, treat SOP guidance as case evidence, or fail to
  use `unknown` when facts are absent.
- Add bad-analysis regression checks for verdict drift, missing direct evidence,
  unsupported ATT&CK mappings, unsafe recommendations, and failure to separate
  evidence from inference.
- Add weak-retrieval and no-match quality evaluation for RAG, SPL query
  grounding, and future Notable Archive Assistant retrieval.
- Add assistant Q&A evaluations for questions such as:
  - "What was the last notable about, and how should we handle it per our SOPs?"
  - "Have we seen this host, user, IOC, or search name in the last 90 days?"
  - "What recent notables look related to this one?"
  - "Summarize this week's high-confidence alerts with source links."
  - "Which weekly patterns should an analyst review?"
- Add weekly summary evaluations that check whether generated summaries cite
  retained cases, avoid unsupported trend claims, and separate case facts from
  advisory customer guidance.
- Add portal chatbot evaluations once the analyst portal exists:
  - selected-case questions over the current alert plus stored analysis
  - global questions over the retained 30-day case archive
  - mixed questions that require separating current alert facts, prior case
    facts, and SOC advisory guidance
  - no-match and weak-retrieval questions that should return `unknown`
  - action-request questions that must be refused because the portal is
    read-only

## Proposed Automation Shape

- Run as an explicit operator command first, then optionally as a weekly
  systemd timer such as `notable-eval.timer` after the corpus and thresholds are
  approved.
- Execute in a lab, staging, or approved evaluation profile by default. Do not
  make production analysis dependent on eval availability.
- Use fixed eval inputs and fixed KB/SPL source docs so regressions are
  attributable to prompt, model, retrieval, validator, or report-rendering
  changes.
- Record prompt version, model id, capability profile, retrieval source ids,
  citations, validation failures, latency, and pass/fail scores.
- For portal-chatbot evals, also record selected case id, retrieved case ids,
  source lanes used (`current_alert`, `case_analysis`, `knowledge_base`,
  `prior_case`), citation coverage, and refusal/no-match reasons.
- Store eval outputs under an operator-controlled artifact directory, not in the
  normal case archive unless an explicit audit/evaluation capability enables it.
- Fail closed for malformed eval fixtures and invalid expected-output rubrics.

## Acceptance Criteria For First Slice

- A small golden set exists with at least one true positive, one false positive,
  one benign/admin case, one weak-retrieval case, and one no-match case.
- The harness can run end to end from one command against a configured analyzer
  service or local test harness.
- The harness reports pass/fail for:
  - schema validity
  - source citation coverage
  - hallucination/unsupported-claim checks
  - evidence-vs-inference separation
  - RAG/SPL advisory-context separation
  - expected `unknown` / no-match behavior
- The harness produces a stable machine-readable report and a short human
  summary suitable for release review.

## Non-Goals

- Do not call live Splunk, ServiceNow, SOAR, or other external systems from the
  eval harness unless a separate integration evaluation profile explicitly
  allows it.
- Do not use production-sensitive customer payloads in the shared golden set.
- Do not treat LLM self-grading as the only quality gate; deterministic checks
  and explicit rubrics remain required.
- Do not make this a replacement for analyst acceptance testing.

## Open Decisions

- Golden-set storage location and redaction standard.
- Whether the first version runs against the live service, a local mocked
  service, or both.
- Score thresholds for blocking release vs warning only.
- Who owns ongoing true-positive/false-positive corpus curation.
- How eval results tie back to prompt versions, KB versions, and model changes.
