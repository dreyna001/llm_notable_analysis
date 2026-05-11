# AWS Notable Analysis Enhancements

Assumption: AWS notable analysis reaches planned feature parity with the on-prem enhancements, including structured SPL generation, read-only Splunk investigation, query-result enrichment, approval-gated ServiceNow handling, RAG/KB grounding, and validated structured LLM output.

- **AWS-native security context enrichment**: enrich notables with GuardDuty, Security Hub, Detective, CloudTrail, VPC Flow Logs, IAM Access Analyzer, and AWS Config context where available.
- **Security Lake / Athena read-only query tool**: generate bounded investigative queries over Security Lake or curated S3 datasets, validate them, cap cost and time range, then feed summarized results into the LLM.
- **Account and asset context lookup**: resolve AWS account, OU, workload owner, tags, environment, criticality, public exposure, and resource relationships before LLM analysis.
- **Event-driven investigation orchestration**: use Step Functions or EventBridge to coordinate multi-step enrichment, retries, timeouts, and human approval without turning the workflow into open-ended autonomy.
- **AWS-shaped RAG grounding**: use Bedrock Knowledge Bases, OpenSearch, Aurora/pgvector, or a small retrieval service for SOPs, detection docs, field dictionaries, and escalation rules.
- **Cross-account correlation**: correlate related notables across accounts, regions, users, IPs, resources, detections, and time windows.
- **Threat intel enrichment adapters**: call VirusTotal, AbuseIPDB, GreyNoise, URLhaus, MISP, OTX, commercial feeds, or internal TI through bounded adapters with caching and rate-limit controls.
- **Enrichment caching and replay support**: store normalized enrichment snapshots in DynamoDB or S3 so reruns are explainable, cheaper, and consistent.
- **Deterministic risk scoring before the LLM**: compute severity signals from alert, asset, identity, TI, and query results first; let the LLM explain and contextualize the score.
- **Detection and rule context lookup**: include detection name, query logic, ATT&CK mapping, known false positives, tuning notes, and owner metadata as advisory context.
- **Approval-gated AWS actions**: draft containment or remediation actions such as tagging, ticket creation, Security Hub finding updates, or EventBridge/SOAR handoff, but require explicit approval before any state change.
- **Policy gates for generated queries and actions**: enforce allowed data sources, denied commands, time bounds, row caps, cost caps, allowed AWS APIs, and approval requirements in code.
- **Analyst feedback loop**: capture dispositions, corrections, false-positive notes, and final outcomes for future retrieval, reporting, and evaluation.
- **Quality and hallucination checks**: validate that LLM outputs only cite direct alert evidence, approved enrichment, or advisory context, and mark unsupported facts as `unknown`.
- **Observability and audit trail**: record prompt versions, model IDs, policy decisions, tool calls, enrichment status, costs, latency, and approval metadata without logging secrets.
- **Cost and quota controls**: cap Bedrock tokens, Athena scanned bytes, enrichment calls, Lambda duration, retry counts, and concurrent investigations.
- **Batch replay and evaluation harness**: replay historical notables through the AWS workflow to compare baseline vs enhanced analysis quality before enabling new capabilities in production.
- **Degraded-mode handling**: explicitly report when Bedrock, Splunk, RAG, TI, Athena, or ServiceNow is unavailable, timed out, denied by policy, or skipped by configuration.

## Leveraging VirusTotal (concise pattern)

- **Placement**: same as on-prem—after deterministic IOC extraction; **default-off** flag; run before the Bedrock prompt is assembled (or as a bounded Step Functions branch if orchestration splits enrichment from analysis).
- **Adapter**: outbound HTTPS from Lambda (or a small VPC-attached sidecar if required); **Secrets Manager / SSM** for the API key; **timeouts**, **bounded concurrency**, **retries with backoff**, and normalized **`enrichment`** payload for the model (not raw vendor dumps unless policy allows).
- **Caching**: DynamoDB or S3-backed cache keyed by observable + TTL to control cost and VT quotas across high-volume ingest.
- **Prompt contract**: `direct_evidence` vs `enrichment` separation; VT-only facts must trace to returned API fields; include **skipped / failed / rate_limited** in structured output when VT cannot run.
- **Governance**: respect org rules on **what may be sent to third parties**; avoid shipping full notable blobs to VT—only **explicit observables** policy allows.

Best next increment after parity: **AWS-native security context enrichment + account/asset lookup**. After that, add **Security Lake / Athena read-only investigation** with strict policy and cost gates.
