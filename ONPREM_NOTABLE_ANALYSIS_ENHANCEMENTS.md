# On-Prem Notable Analysis Enhancements

- **Threat intel enrichment adapters**: VirusTotal, AbuseIPDB, URLhaus, GreyNoise, MISP, OTX, internal TI feeds.
- **SIEM read-only query tool**: let the workflow generate bounded Splunk/Elastic queries, validate them, run them read-only, and feed results back into the LLM.
- **Asset/user context lookup**: enrich notables with CMDB, identity, criticality, owner, business unit, VIP/admin status.
- **Case history retrieval**: pull similar prior notables, analyst dispositions, and past remediation notes as advisory context.
- **Structured investigation planner**: LLM proposes next checks, but deterministic policy decides which tool calls are allowed.
- **Confidence/evidence separation**: force output into `direct_evidence`, `enrichment`, `inference`, `unknowns`, and `recommended_actions`.
- **Approval-gated writeback**: draft ServiceNow/Jira/SOAR updates, but require human approval before posting.
- **RAG for local runbooks**: use internal SOPs, Splunk field docs, escalation rules, and detection logic as grounding context.
- **Policy gates for actions**: allowlists, time bounds, query cost caps, read-only enforcement, and "no containment without approval."
- **Memory only where useful**: not open-ended agent memory, but bounded case history and durable audit trail of prompts, tool calls, and outputs.

## Leveraging VirusTotal (concise pattern)

- **Placement**: after deterministic IOC extraction from the notable (hashes, domains, IPs, URLs); optional **default-off** capability behind env/config.
- **Adapter**: thin HTTP client to VT’s lookup APIs; **timeouts**, **retries with backoff**, **rate-limit awareness**, and **response normalization** into a small structured `enrichment` object (scores, detection counts, verdicts, relevant metadata only).
- **Caching**: cache VT responses by observable + time window to protect quotas and make reruns stable.
- **Prompt contract**: pass notable facts as `direct_evidence`; pass VT output only under `enrichment` with explicit source label; forbid inventing VT facts in the LLM path.
- **Ops**: API key from host secrets (not repo); minimal structured logging (no raw tokens); explicit **skipped / failed / rate_limited** states in outputs when VT is unavailable or policy blocks submission.

Best next increment: **read-only enrichment + structured output contract**. After that, add **validated SIEM query execution**. That gives the most capability without jumping into risky autonomy.
