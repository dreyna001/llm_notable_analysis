# Preview case investigation guide

Use this guide when exercising the **analyst portal preview UI** with stored
synthetic cases (`case-1` through `case-5`). Preview ships pre-generated
analyzer output; only the **chatbot** calls a live LLM (Bedrock, OpenAI, or
stub).

For preview setup, see
[`llm_notable_analysis_onprem_systemd/docs/operations/ANALYST_PORTAL_PREVIEW.md`](llm_notable_analysis_onprem_systemd/docs/operations/ANALYST_PORTAL_PREVIEW.md).

## Before you start

- Open **http://127.0.0.1:5173** (Vite UI), not the raw API port.
- Navigate to a case (for example `/cases/case-1`).
- Use **selected-case chat** so answers stay grounded in that case's stored
  analysis and alert fields.
- Ask the assistant to label answers as **Evidence**, **Inference**, or
  **Query (not executed)** when testing disposition workflow.

## Preview scenario map

| Case | Alert type |
|------|------------|
| 1 | Malware Beaconing |
| 2 | Impossible Travel |
| 3 | Suspicious PowerShell |
| 4 | Privilege Escalation Attempt |
| 5 | Suspicious RDP Lateral Movement |

Cases 6-55 are list-pagination fillers only.

---

## Case 1: Malware Beaconing

**Alert context:** `laptop-22.corp.local` (`corp\mrossi`) sent 1,440 HTTPS POST
requests every 60 seconds to `update-service-cloud.net` (domain age 3 days),
fixed 512-byte payloads, URI `/api/v1/session/a8f2c1`.

**Stored disposition:** `likely_malicious` (confidence 0.88).

### Phase 1 — Orient on the alert

1. Summarize this alert in plain language. What is proven vs inferred?
2. What are the top three decision drivers pointing to malicious vs benign?
3. Which competing hypothesis is strongest for benign, and what single fact would falsify it?
4. What evidence gaps must we close before we can disposition this?

### Phase 2 — Test benign paths first

5. Is `UpdateAgent/2.1` a known sanctioned updater on `laptop-22`? What would we check in inventory or CMDB?
6. Could this be a monitoring or health-check agent on a fixed 60-second interval? What would distinguish that from C2?
7. Could `corp\mrossi` have legitimate software using `update-service-cloud.net`? What user or host context is missing?

### Phase 3 — Corroborate malicious C2

8. Why does `domain_age_days=3` plus fixed 512-byte POSTs every 60 seconds favor C2 over normal updater traffic?
9. What process on `laptop-22` is most likely responsible for these connections?
10. Is there evidence of persistence, staging, or follow-on activity not shown in this alert?
11. Should we treat `203.0.113.77` and `update-service-cloud.net` as IOCs for fleet-wide hunting?

### Phase 4 — Splunk queries

12. Write Splunk SPL to find all hosts contacting `update-service-cloud.net` or `203.0.113.77` in the last 7 days. Include src, dest, uri, user_agent, bytes, and count.
13. Write SPL for fixed-interval POST beacons (60s cadence) from internal hosts to domains under 30 days old.
14. Write SPL to pivot from `laptop-22.corp.local` / `10.44.12.88` around the alert time for process creation, DNS, and proxy events tied to this domain.
15. Write SPL to see whether `uri_path=/api/v1/session/a8f2c1` appears elsewhere in the environment.

### Phase 5 — Elasticsearch queries

16. Write an Elasticsearch query (KQL or Lucene) for proxy/web events with `dest.domain:update-service-cloud.net` and `source.ip:10.44.12.88`.
17. Write a query to hunt the same URI path and user agent across all web/proxy indices for 7 days.
18. Write an aggregation-style ES query plan to detect repeating 512-byte POSTs on approximately 60-second intervals.

### Phase 6 — CrowdStrike queries

19. What CrowdStrike Falcon Investigate / LogScale queries would identify the process making HTTPS POSTs to `update-service-cloud.net` on `laptop-22`?
20. Write a CrowdStrike hunt for child processes of Office or browser apps spawning network clients to unknown young domains.
21. What Falcon triage steps and collections should we run on `laptop-22` before isolation?

### Phase 7 — Disposition and closure

22. Based on current evidence, what disposition do you recommend: true positive malicious, false positive benign, or inconclusive pending hunt?
23. What three hunt results would move this from `likely_malicious` to confirmed vs ruled out?
24. Draft a short disposition note for the ticket: finding, evidence, actions taken, residual risk.
25. What immediate containment actions are justified now vs after one more pivot?

### Single-turn master prompt

Use this when you want one structured pass instead of stepping through phases:

> Walk me from triage to disposition for this beaconing alert on `laptop-22`. For each step: state the question, what evidence we have, what's missing, and give one Splunk SPL query, one Elasticsearch query, and one CrowdStrike hunt query. End with recommended disposition and next actions.

---

## Adapting this guide to cases 2-5

Use the same phase structure for other preview cases:

1. Orient (proven vs inferred, decision drivers, gaps).
2. Test the top benign hypothesis from stored `competing_hypotheses`.
3. Corroborate the leading adversary hypothesis.
4. Request Splunk, Elasticsearch, and CrowdStrike pivots keyed to that case's IOCs and host/user fields.
5. Close with disposition criteria and a ticket note.

Pull IOCs and hypothesis text from the case detail page or from
`data/preview_scenarios/bundles/case-N.json`.
