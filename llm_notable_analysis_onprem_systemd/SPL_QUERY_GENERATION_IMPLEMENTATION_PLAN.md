# SPL Query Generation Implementation Plan

## Purpose

Add analyst-ready Splunk query generation to the on-prem notable analysis workflow without coupling the feature to Phantom/SOAR-specific structures or requiring a fixed incoming alert schema.

The goal is to move from:

- "Here are the competing explanations."

to:

- "Here are the competing explanations, and here is the single best Splunk query to prove or disprove each one."

## Approved Design Decisions

- Generate queries per hypothesis.
- Keep the design alert-agnostic.
- Do not rely on Phantom-specific fields or semantics for query generation.
- Do not introduce a new hidden normalization layer for alert input before prompt use.
- Continue treating the incoming alert as one raw JSON object when JSON is provided.
- Keep the existing 6-hypothesis model:
  - 3 benign hypotheses
  - 3 adversary hypotheses
- Generate exactly 1 primary SPL query per hypothesis.
- Generate 6 primary SPL queries total per alert.
- Remove `expand_scope` from v1 entirely.
- Each hypothesis query must be one of:
  - `resolve_unknown`
  - `check_contradiction`
- Prefer queries that answer a missing, decision-changing question over queries that merely restate already-known alert facts.
- Keep strict anti-hallucination behavior.
- Do not add query readiness levels in v1.
- Do not add explicit grounding/citation objects in v1.
- Make the feature controllable with an environment variable.

## Feature Flag

Add an env-driven feature flag so the capability can be enabled or disabled cleanly at deployment time.

Recommended variable:

- `SPL_QUERY_GENERATION_ENABLED=false`

Why:

- matches the existing config style used by flags such as `RAG_ENABLED` and `SPLUNK_SINK_ENABLED`
- allows gradual rollout without changing the base alert-analysis behavior
- avoids extra token cost and schema complexity when the feature is off

When disabled:

- the prompt should not ask for SPL query fields
- normalization should strip any unexpected SPL query fields returned by the model
- validation should not require SPL query fields
- markdown rendering should not show SPL query sections

When enabled:

- the prompt should request the SPL query fields for each hypothesis
- validation should enforce or repair those fields
- markdown should render the query block under each hypothesis

## Locked Implementation Decisions

The following decisions are locked for implementation:

- v1 scope is the structured JSON analysis path in `onprem_service/local_llm_client.py` only.
- `freeform_llm_client.py` is out of scope for v1.
- When `SPL_QUERY_GENERATION_ENABLED=true`, a successful SPL-enabled result must contain:
  - exactly 6 competing hypotheses total
  - exactly 3 benign hypotheses
  - exactly 3 adversary hypotheses
  - exactly 1 primary SPL query per hypothesis
  - exactly 6 primary SPL queries total per alert
- If the primary model response violates the SPL query contract, run the existing repair path.
- If repair still fails to satisfy the SPL query contract:
  - do not fabricate missing hypotheses
  - do not fabricate missing queries
  - do not insert placeholder or pseudo-queries just to fill the contract
  - suppress SPL query rendering for that alert
  - preserve the rest of the structured analysis/report if it is otherwise valid
- When `SPL_QUERY_GENERATION_ENABLED=false`, the capability is fully off:
  - prompt off
  - normalization strips SPL fields
  - validation ignores SPL fields
  - markdown rendering omits SPL sections

## Query Strategy

Each hypothesis gets one primary query chosen by decision value.

### `resolve_unknown`

Use when the hypothesis is plausible, but one missing fact is blocking confident judgment.

Examples:

- Is this user-host-process combination historically normal?
- Is there corroboration in another log source?
- Is the parent process or authentication context consistent with the hypothesis?

### `check_contradiction`

Use when there is a fast and meaningful way to weaken or disprove the hypothesis.

Examples:

- Does other telemetry show interactive activity that contradicts a benign automation hypothesis?
- Does historical context show normal recurrence that contradicts a "first-seen adversary" theory?

## What The Query Should Optimize For

The model should generate the query that best helps the analyst decide whether a hypothesis is right or wrong.

Priority order:

1. Resolve the most important unknown.
2. If a strong contradiction check is more decisive, use that instead.
3. Do not generate a query that only re-finds evidence already present in the alert unless it answers a new question such as frequency, rarity, corroboration, or contradiction.

## Splunk Environment Context To Support This Feature

This feature should remain alert-agnostic, but query quality will improve when the system later has access to real Splunk environment knowledge.

- Indexes
  Where the data lives in Splunk.
- Sourcetypes
  The source/parser label that tells Splunk what kind of telemetry a given event contains.
- CIM / data models
  Splunk's normalization layer. CIM defines common field names across disparate sources, and data models provide structured views over that normalized data.
- Approved macros
  Reusable, team-approved SPL snippets for common filters, field mappings, or search patterns.
- Saved-search examples
  Existing investigation or detection searches that show how the customer's environment actually queries real data.

## Anti-Hallucination Rules

These rules should be treated as hard constraints in prompt design, validation, and report rendering.

- Never invent indexes.
- Never invent sourcetypes.
- Never invent CIM data model names.
- Never invent macros.
- Never assume alert JSON keys are valid Splunk field names.
- Never emit environment-specific SPL tokens unless they are actually known from configured context or future retrieval context.
- If key Splunk details are unknown, prefer safer generic SPL logic over fabricated environment-specific syntax.
- Never use placeholder tokens such as `<INDEX>`, `<SOURCETYPE>`, or similar filler.
- Never emit pseudo-queries such as `search ...` purely to satisfy the contract.
- Generic SPL is acceptable only when it is still a real query derived from alert-visible facts and does not invent field names or environment-specific tokens.
- State unknowns explicitly in the narrative rather than filling gaps with guessed details.
- Use only evidence available in the alert plus any explicitly supplied Splunk context.

## Report Placement

The SPL query should appear under each hypothesis, not in a detached query appendix.

Recommended report flow:

1. Alert Reconciliation
2. Competing Hypotheses & Pivots
3. For each hypothesis:
   - hypothesis
   - evidence support
   - evidence gaps
   - query strategy
   - primary SPL query
   - why this query
   - supports hypothesis if
   - weakens hypothesis if

This keeps reasoning and next action tightly coupled for the analyst.

## Proposed Output Contract Changes

Extend each hypothesis object with SPL-specific fields instead of creating a disconnected top-level query block.

Suggested fields:

- `query_strategy`
  - `resolve_unknown` or `check_contradiction`
- `primary_spl_query`
  - the single highest-value query for the hypothesis
- `why_this_query`
  - brief explanation of why this is the best next step
- `supports_if`
  - what result pattern would strengthen the hypothesis
- `weakens_if`
  - what result pattern would weaken the hypothesis

`best_pivots` should remain, but become the short human-readable direction while `primary_spl_query` is the executable next step.

## Suggested JSON Shape

```json
{
  "hypothesis_type": "benign",
  "hypothesis": "Scheduled administrative PowerShell activity",
  "evidence_support": [
    "process_name=powershell.exe",
    "host=WKSTN-22"
  ],
  "evidence_gaps": [
    "unknown whether this pattern is normal for the user on this host"
  ],
  "best_pivots": [
    {
      "log_source": "authentication telemetry",
      "key_fields": "user, host, earliest, latest"
    }
  ],
  "query_strategy": "resolve_unknown",
  "primary_spl_query": "search ...",
  "why_this_query": "This query checks whether the observed behavior is historically normal for the same account and system.",
  "supports_if": "The same pattern appears repeatedly during expected maintenance periods.",
  "weakens_if": "The pattern is first-seen, rare, or appears outside expected operational context."
}
```

## Implementation Steps

### 1. Prompt Contract Updates

Update `onprem_service/local_llm_client.py` to extend the existing competing hypothesis instructions so each hypothesis also returns:

- `query_strategy`
- `primary_spl_query`
- `why_this_query`
- `supports_if`
- `weakens_if`

Update prompt rules so the model:

- generates exactly 1 primary query per hypothesis
- uses `resolve_unknown` or `check_contradiction` only
- prefers closing a decision-changing evidence gap
- avoids re-stating already-known alert facts
- avoids inventing Splunk environment specifics
- only emits SPL query fields when `SPL_QUERY_GENERATION_ENABLED=true`

### 2. Response Validation Updates

Extend structured response validation in `onprem_service/local_llm_client.py` to check:

- `query_strategy` is present and valid when hypotheses are present
- `primary_spl_query` is a non-empty string
- `why_this_query`, `supports_if`, and `weakens_if` are strings
- hypothesis objects remain resilient to occasional local-model drift where needed
- the SPL query fields are only required when `SPL_QUERY_GENERATION_ENABLED=true`
- exactly 6 hypotheses are present when SPL query generation is enabled
- exactly 3 benign and 3 adversary hypotheses are present when SPL query generation is enabled
- exactly 1 query bundle is present per hypothesis when SPL query generation is enabled

Validation behavior is locked:

- repair first when the SPL query contract is violated
- if repair still fails, suppress SPL query output for that alert rather than fabricating defaults
- do not create synthetic hypotheses or synthetic queries to satisfy the contract

### 3. Markdown Rendering Updates

Update `onprem_service/markdown_generator.py` so each hypothesis renders:

- query strategy
- primary SPL query
- why this query
- supports hypothesis if
- weakens hypothesis if

Render the SPL in a fenced code block for readability.

Do not render the SPL subsection when `SPL_QUERY_GENERATION_ENABLED=false`.

If SPL query generation is enabled but the SPL contract still fails after repair, omit SPL rendering for that alert and show a brief note that SPL query generation was unavailable for this result.

### 4. Configuration Updates

Update `onprem_service/config.py` and environment documentation to add:

- `SPL_QUERY_GENERATION_ENABLED: bool = False`
- parsing from `os.getenv("SPL_QUERY_GENERATION_ENABLED", "false")`

Update operator-facing config documentation:

- `config.env.example`
- `README.md` if the feature is documented there

### 5. Test Coverage

Add or update focused tests for:

- schema validation of new hypothesis query fields
- normalization/default handling for missing query fields
- markdown rendering of hypothesis query sections
- anti-hallucination prompt rules being present in the constructed prompt
- feature-flag behavior when the capability is enabled vs disabled

Likely test files:

- `tests/onprem_service/test_local_llm_client_contract.py`
- `tests/onprem_service/test_markdown_generator.py`

### 6. Iteration Strategy

Implement in this order:

1. Prompt/schema contract
2. Validation and normalization
3. Markdown rendering
4. Focused tests
5. Real sample alert review against generated output

## Files To Modify (v1)

The following files are in scope for the implementation and why they are needed.

- `onprem_service/config.py`
  - add `SPL_QUERY_GENERATION_ENABLED: bool = False`
  - parse the environment variable in `load_config()`
- `onprem_service/local_llm_client.py`
  - add prompt rules and schema contract for per-hypothesis SPL fields
  - gate SPL generation behavior on `SPL_QUERY_GENERATION_ENABLED`
  - enforce/repair the strict `6 hypotheses -> 6 queries` contract when enabled
  - strip/ignore SPL fields when disabled
- `onprem_service/markdown_generator.py`
  - render SPL query details under each hypothesis when enabled and valid
  - omit SPL query sections when disabled
  - show a short SPL-unavailable note when enabled but contract fails after repair
- `config.env.example`
  - document `SPL_QUERY_GENERATION_ENABLED=false` for operators
- `README.md` (if feature docs are present there)
  - add a short section explaining on/off behavior for SPL query generation
- `tests/onprem_service/test_local_llm_client_contract.py`
  - add tests for feature flag behavior and strict SPL contract enforcement
- `tests/onprem_service/test_markdown_generator.py`
  - add tests for SPL rendering on/off and SPL-unavailable fallback note

### Explicitly Out Of Scope (v1)

- `onprem_service/freeform_llm_client.py`
- `onprem_service/freeform_main.py`
- Phantom/SOAR playbook files

## Notes From Design Discussion

- Query generation should not be tied to Phantom, SOAR, or any single ingest source.
- The feature must remain compatible with arbitrary raw JSON alert payloads.
- The value of the query is in answering a new decision-making question, not rephrasing evidence already visible in the alert.
- The analyst should see the query where they see the hypothesis, not in a separate search dump.
- `best_pivots` remains useful as concise investigative intent even after adding executable SPL.
- A future phase can add explicit grounding/citations and environment-aware query generation once Splunk context retrieval is available.

## Future Enhancements

Not part of v1:

- explicit grounding/citation objects
- query readiness levels
- automatic environment-aware query specialization using retrieval
- follow-on scope expansion queries
- execution or validation of SPL against a real Splunk environment
