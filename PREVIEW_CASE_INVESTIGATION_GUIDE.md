# Preview case investigation guide

Use this guide when exercising the **analyst portal preview UI** with stored
synthetic cases (`case-1` through `case-5`). Preview ships pre-generated
analyzer output; only the **chatbot** calls a live LLM (Bedrock, OpenAI, or
stub).

For one-time preview setup (venv, Bedrock config, starting servers), see
[`llm_notable_analysis_onprem_systemd/docs/operations/analyst_portal/ANALYST_PORTAL_PREVIEW.md`](llm_notable_analysis_onprem_systemd/docs/operations/analyst_portal/ANALYST_PORTAL_PREVIEW.md).

**Knowledge Base demo:** follow
[How to demo Knowledge Base on alert 5 (case-5)](#how-to-demo-knowledge-base-on-alert-5-case-5) below.

## Preview scenario map

| Case | Alert type | Preview quality |
|------|------------|-----------------|
| 1 | Malware Beaconing | Full stored analysis bundle |
| 2 | Impossible Travel | Full stored analysis bundle |
| 3 | Suspicious PowerShell | Full stored analysis bundle |
| 4 | Privilege Escalation Attempt | Full stored analysis bundle |
| 5 | Suspicious RDP Lateral Movement | Full stored analysis bundle — **use for Knowledge Base demo** |

Cases 6-55 are list-pagination fillers only (no full analysis panels).

---

## How to demo Knowledge Base on alert 5 (case-5)

This walkthrough shows **case archive grounding plus Knowledge Base advisory
context** in chat. Case-5 is one of the five high-quality stored alerts; its
destination host `db-prod-01.corp.local` appears in the preview HVA registry,
so case facts and KB docs reinforce each other.

**Demo posture:** preview uses **committed fixture KB docs** in this repo, not
Amazon Bedrock Knowledge Base or S3 Vectors. You do not need to provision AWS KB
infrastructure for this demo. Use Bedrock or OpenAI in `config.portal-preview.env`
for chat **synthesis only**. AWS production KB setup (S3 Vectors +
`amazon.titan-embed-text-v2:0`) is documented in
[`s3_notable_pipeline/docs/operations/rag/KNOWLEDGE_BASE_OPERATIONS.md`](s3_notable_pipeline/docs/operations/rag/KNOWLEDGE_BASE_OPERATIONS.md).

### What you are showing

1. **Case evidence** — stored alert and analyzer output for case-5 (RDP lateral
   movement).
2. **Knowledge Base** — committed SOC docs (SOPs, network map, HVA list) injected
   into chat when your question matches advisory topics (or when case-aware KB
   retrieval is enabled; see
   [`CASE_AWARE_KB_RETRIEVAL_PLAN.md`](llm_notable_analysis_onprem_systemd/docs/planning/CASE_AWARE_KB_RETRIEVAL_PLAN.md)).
3. **Combined synthesis** — the chatbot answers using both lanes (same production
   chat path; preview uses keyword-matched fixtures instead of Postgres RAG or
   Bedrock KB retrieval).

KB fixtures:
`llm_notable_analysis_onprem_systemd/data/preview_scenarios/knowledge_base/`

| Document | Purpose |
|----------|---------|
| `sop-host-isolation.md` | Emergency host containment |
| `sop-tier2-escalation.md` | When and how to escalate to Tier 2 |
| `corp-network-architecture.md` | Synthetic VLAN / segment reference |
| `hva-registry.md` | High Value Asset list and SOC handling rules |

### Prerequisites

- Repo cloned; dev venv bootstrapped (see ANALYST_PORTAL_PREVIEW.md).
- `llm_notable_analysis_onprem_systemd/config.portal-preview.env` created with
  **Bedrock or OpenAI** configured for chat synthesis (stub chat does not produce
  realistic KB-grounded answers).
- **No AWS Knowledge Base setup required** for preview — fixture docs under
  `data/preview_scenarios/knowledge_base/` are sufficient.
- If using Bedrock for synthesis: `aws sso login --profile <your-profile>` completed.

### Step-by-step

1. **Activate the venv** from the repo root.

2. **Terminal 1 — start the preview API:**

   ```powershell
   .\scripts\dev_portal_preview.ps1
   ```

   Confirm startup shows `Chat synthesis: Bedrock (...)` or `OpenAI (...)` — not
   `stub (...)`. Also confirm `Pipeline-backed analyzer cases: case-1 .. case-5`.

3. **Terminal 2 — start the UI:**

   ```powershell
   .\scripts\dev_portal_ui.ps1
   ```

4. **Open the browser** at **http://127.0.0.1:5173** (use `127.0.0.1`, not
   `localhost`, if Vite is bound to loopback only).

5. **Open case-5:** navigate to **http://127.0.0.1:5173/cases/case-5** (or pick
   *Suspicious RDP Lateral Movement* from the case list).

6. **Orient on the case page** before chatting. You should see full analysis
   panels (not a filler stub). Key alert fields to note:
   - **Search name:** Suspicious RDP Lateral Movement
   - **Source:** `jump-01.corp.local` / `corp\svc-backup`
   - **Destination:** **`db-prod-01.corp.local`** (listed as an HVA in the KB)
   - **Context:** six failed logons in 15 minutes; service account not approved
     on destination

7. **Open case chat** on the case-5 page. Ensure you are in **selected-case**
   mode (chat scoped to this case, not a global/cross-case mode).

8. **Ask the demo questions** below (start with the quick demo, then optional
   deeper phases).

9. **Check the answer** blends:
   - **Case evidence** — hosts, users, RDP, failed logons from the alert/analysis.
   - **KB advisory** — HVA registry entries, Tier 2 steps, network segments, isolation SOP.
   - Ask the assistant to label claims as **case evidence**, **KB advisory**, or
     **inference** if you want an explicit split (question 14 or the master prompt).

10. **Optional follow-up** — ask a second question in the same session (multi-turn
    chat is enabled in preview) to show escalation then containment, for example
    question 4 then question 10.

### Quick demo (copy these in order)

Paste into selected-case chat on `/cases/case-5`:

1. `Is db-prod-01.corp.local a High Value Asset in our registry? What owner team and SOC handling rules apply?`

2. `Should this case be escalated to Tier 2? Cite the alert facts and our escalation SOP criteria.`

3. `What network segment is db-prod-01 in, and is RDP from jump-01 to the database tier an approved path for corp\svc-backup?`

4. `Given this alert and our HVA registry, what is the recommended immediate path: escalate, isolate source, isolate destination, or hunt first? Separate case evidence from KB advisory.`

**Single-turn alternative** — one message instead of four:

> On case-5, explain whether `db-prod-01.corp.local` is an HVA, whether Tier 2 escalation is required, whether the jump-to-database RDP path is expected per our network reference, and what containment steps apply. Label each claim as case evidence, KB advisory, or inference. End with recommended next actions.

### What a good answer looks like

- Names **`db-prod-01.corp.local`** as an HVA with owner **DBA-Production** (from KB).
- References alert facts: **`corp\svc-backup`**, **`jump-01`**, failed logons, suspicious RDP.
- Cites Tier 2 escalation criteria (risk/HVA/lateral movement) and concrete steps (queue, paging).
- Mentions database tier VLAN **10.30.8.0/24** and that cross-tier RDP is high severity (network KB).
- Does **not** claim Splunk queries were run or tickets were created (chat is advisory only).

### If something fails

| Symptom | Fix |
|---------|-----|
| Chat says LLM gateway down / unavailable | Restart preview API; confirm `config.portal-preview.env` has Bedrock or OpenAI set and startup log is not `stub` |
| 403 on chat POST | Browse via **http://127.0.0.1:5173**; restart both preview API and Vite |
| Answer ignores KB / only uses case text | Restart preview API after pulling case-aware KB changes. On case-5, generic summaries should retrieve HVA context via `db-prod-01.corp.local` in the enriched KB query. If not, ask an explicit HVA/escalation/network question. |
| Case-5 page looks empty or minimal | Wrong case — use **case-5**, not case-6+ (fillers only) |

### Extended question bank (optional)

Use these for a longer session after the quick demo.

#### Phase 1 — HVA and registry grounding

1. Is `db-prod-01.corp.local` a High Value Asset in our registry? What owner team and data classification apply?
2. What SOC handling rules apply when an HVA is the destination of suspicious RDP?
3. Does the HVA registry mention any special containment restrictions for database-tier assets?

#### Phase 2 — Escalation SOP

4. Should this case be escalated to Tier 2? Cite both the alert facts and the escalation SOP criteria.
5. What are the step-by-step Tier 2 escalation actions (queue, paging, documentation)?
6. What priority and case metadata are required when an HVA is involved?

#### Phase 3 — Network architecture context

7. What VLAN or segment is `db-prod-01` in, and is RDP from `jump-01` an approved path for `corp\svc-backup`?
8. Is workstation-to-database-tier RDP expected in our network reference? What does the jump-path guidance say?
9. Does crossing from jump tier to database tier change severity handling?

#### Phase 4 — Containment SOP

10. What is our SOP to isolate a compromised host? When should we use EDR network isolate vs an emergency network block?
11. For an HVA database server, what containment steps require approval before isolation or power-off?
12. What evidence preservation steps must happen before reimaging or reboot?

#### Phase 5 — Combined case + KB synthesis

13. Given this alert and our HVA registry, what is the recommended immediate path: escalate, isolate source, isolate destination, or hunt first?
14. Separate what comes from **this case's alert/analysis** vs what comes from **Knowledge Base advisory** docs.
15. Draft a short escalation handoff note for Tier 2 using case facts plus SOP requirements.

---

## Case 1: Malware Beaconing

**Before you start (case chat generally):**

- Open **http://127.0.0.1:5173** (Vite UI), not the raw API port.
- Use **selected-case chat** so answers stay grounded in that case's stored
  analysis and alert fields.
- Ask the assistant to label answers as **Evidence**, **Inference**, or
  **Query (not executed)** when testing disposition workflow.

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

## Adapting this guide to cases 2-4

Use the same phase structure for other preview cases (except case-5, which has
the dedicated Knowledge Base section above):

1. Orient (proven vs inferred, decision drivers, gaps).
2. Test the top benign hypothesis from stored `competing_hypotheses`.
3. Corroborate the leading adversary hypothesis.
4. Request Splunk, Elasticsearch, and CrowdStrike pivots keyed to that case's IOCs and host/user fields.
5. Close with disposition criteria and a ticket note.

Pull IOCs and hypothesis text from the case detail page or from
`data/preview_scenarios/bundles/case-N.json`.
