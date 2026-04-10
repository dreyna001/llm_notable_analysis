# Agentic Maturity Target For Notable Analysis

## Scope
This note covers:

- `llm_notable_analysis_onprem_systemd`
- `s3_notable_pipeline`
- `aws_notable_ecs_demo`

## Current State
Both the on-prem and AWS implementations are best described as **LLM-powered, guardrailed analysis pipelines**.

They currently:

- ingest one alert or notable at a time
- run one bounded model analysis
- validate and optionally repair the model output
- generate a markdown report
- write to fixed sinks such as filesystem, S3, or Splunk comments

They do **not** currently:

- perform open-ended multi-step investigation
- choose among multiple external tools at runtime
- maintain case state across multiple investigative steps
- execute a true plan-act-observe loop
- autonomously take consequential response actions

## Planning Rule
Use:

- **Primary:** backend capability roadmap
- **Secondary:** agentic maturity label for autonomy, control, and risk

Rule of thumb:

- **Roadmap by capability**
- **Describe by autonomy level**

## Target
For today's technology, the recommended end goal is:

**Bounded investigative agent with strong guardrails and human approval for consequential actions**


## Current Placement
### On-Prem

- one notable is processed at a time
- the service runs a bounded LLM analysis
- output is validated and normalized
- there is a single repair path when output is invalid
- the model does not drive a multi-step investigation loop

### AWS


- one uploaded object triggers one analysis run
- Bedrock tool use is being used for structured output enforcement, not open-ended tool selection
- output is validated and optionally repaired once
- the system routes the result to fixed sinks such as S3 and/or Splunk
- the model does not choose investigative tools or maintain case state across steps

## Capability Roadmap
Not limited to just these:

1. **Ground SPL & output with RAG** over Splunk schema, indexes, fields, macros & SOPs.
2. **Execute read-only SPL** against Splunk
3. **Summarize results** back into confidence, disposition, and next steps (need to refine this)
4. **Ticketing System Integration** such as Archer/SNOW to automate portions of ticket creating and data entry for each notable.

## Notes For Single-Call Design
If SPL and related structured fields are returned in one LLM JSON response, there is no need for a separate persisted evidence model.

In that design:

- parse the structured JSON response in code
- keep the schema strict and validated
- use RAG for environment grounding, not for current-alert facts

## Near-Term Recommendation
Best next enhancement:

- **RAG-grounded SPL generation**

Next major milestone after that:

- **safe read-only SPL execution with validation and limits**

or

- **Ticketing System Integration** such as Archer/SNOW to automate portions of ticket creating and data entry for each notable.

## Guardrails Needed Before SPL Execution
- allowed indexes and commands
- banned risky constructs
- read-only enforcement
- time bounds
- result count caps
- cost and complexity limits
- timeouts
- audit logging and correlation IDs

## Optional Scope Expansion
Examples beyond the current system:

- Archer
- ServiceNow
- SOAR platforms
- asset, identity, and threat-intel enrichments

## Agentic Maturity Overlay
### Level 1: Deterministic Automation
- Rules and fixed logic only

### Level 2: Single-Shot LLM Assistant
- One prompt in, one answer out

### Level 3: Guardrailed LLM Workflow
- Schema-bound output with deterministic orchestration

### Level 4: Bounded Tool-Using Agent
- Limited approved read-only tools and bounded investigative steps

### Level 5: Investigative Agent
- Multi-step bounded investigation with evidence tracking and human approval for consequential actions

### Level 6: Semi-Autonomous SOC Operator
- Narrow-domain semi-autonomy with very strong controls

## Capability-To-Level Mapping
- current system: **Level 3**
- add grounded SPL generation only: **Level 3**, but stronger
- add safe automated read-only query execution and summarization: entering **Level 4**
- add bounded multi-step evidence gathering across tools: solid **Level 4**
- add maintained case state and structured recommendations across steps: **Level 5**
