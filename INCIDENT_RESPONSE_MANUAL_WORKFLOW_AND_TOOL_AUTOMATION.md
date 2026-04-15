# Incident Response Manual Workflow And Tool Automation

This document maps the manual incident response workflow, isolates the analysis portion, and estimates how much of that work the current tool and a more mature future version can automate.

## Scope

This document assumes the current platform boundary is:

- upstream systems already created a notable or alert
- the tool receives that notable through the current S3 or file-drop workflow
- the tool produces an analyst-ready markdown report
- the tool may also write the report back to Splunk as a comment

It does not assume the platform performs full incident command, containment, eradication, recovery, legal/compliance workflows, or other high-consequence response actions.

## Executive Summary

- `Current tool`: about `50-65%` of the analysis portion of incident response and about `15-25%` of the full incident response lifecycle
- `Fully mature tool` with `SOP-backed RAG`, `Splunk schema/data-dictionary RAG`, and `automated read-only SPL execution`: about `25-50%` of the full incident response lifecycle, with `30-45%` as the most defensible planning range
- Best current fit: `first-pass notable triage`, `TTP/IOC extraction`, `evidence vs inference separation`, and `draft report generation`
- Biggest remaining gaps: `deep multi-system investigation`, `response action orchestration`, and all post-analysis incident management work

## 1. Manual Incident Response Workflow

The table below describes a common manual workflow for enterprise incident response. Real organizations may rename or merge phases, but the responsibilities are broadly similar.

| Phase | Objective | Typical human work | Current tool coverage |
|---|---|---|---|
| Detection and intake | Identify suspicious activity and open a case or notable | Build detections, tune alerting, monitor queues, assign ownership, suppress noise, route by severity | `None` |
| Triage and validation | Decide whether the alert deserves investigation | Read alert, inspect fields, check obvious false positives, set urgency, compare against prior cases | `Partial` |
| Initial analysis | Turn raw alert data into an initial technical understanding | Extract facts, identify IOCs, map ATT&CK, separate evidence from inference, form a first verdict | `Strong` |
| Deep investigation and scoping | Determine what happened, how far it spread, and what remains unknown | Pivot across SIEM, EDR, identity, email, cloud, proxy, endpoint, and case history to define blast radius | `Limited` |
| Escalation and coordination | Engage the right responders and decision-makers | Notify teams, assign tasks, request approvals, manage timelines, update the case system | `None` |
| Containment | Stop ongoing harm or limit spread | Disable accounts, isolate endpoints, revoke tokens, block domains or IPs, pause risky services | `None` |
| Eradication | Remove adversary footholds and root cause | Delete persistence, remove malware, rotate credentials, patch exploited systems, close the access path | `None` |
| Recovery | Restore systems and validate safe return to service | Bring systems back online, verify health, monitor for reinfection, confirm business recovery | `None` |
| Reporting and communications | Communicate status and impact | Produce case summaries, executive updates, legal/compliance inputs, customer or regulator support | `Minimal` |
| Lessons learned and improvement | Improve future response quality | Run retrospectives, fix process gaps, improve detections, update runbooks, assign remediation owners | `None` |

## 2. Analysis Workflow And Current Coverage

The analysis portion is narrower than the full incident lifecycle. It is the work of interpreting a specific alert or case and deciding what it likely means.

### Analysis Sub-Workflow

1. Receive and normalize the alert or notable.
2. Identify the direct facts present in the alert payload.
3. Separate direct evidence from analyst inference.
4. Extract useful observables such as identities, hosts, IPs, domains, hashes, file paths, processes, or event IDs.
5. Map likely ATT&CK techniques and judge confidence.
6. Form an initial verdict such as likely true positive, likely benign, likely false positive, or unknown.
7. Generate competing hypotheses and note evidence gaps.
8. Propose next pivots or investigative steps.
9. Produce an analyst-readable summary or case note.
10. Revise the assessment as new evidence arrives from other systems.

### What The Current Tool Automates

Based on current repository behavior, the tool automates this bounded workflow:

1. Accept a notable from the current upstream handoff path.
2. Normalize JSON or text alert content.
3. Run structured LLM analysis.
4. Extract IOCs and ATT&CK techniques.
5. Separate evidence from inference.
6. Produce alert reconciliation and competing hypotheses.
7. Generate a markdown report.
8. Write the result to S3 or optionally back to Splunk notable comments.

Current outputs include:

- alert normalization from JSON or text
- first-pass verdict
- one-sentence summary
- decision drivers
- recommended actions
- ATT&CK technique suggestions with confidence
- IOC extraction
- evidence versus inference separation
- competing hypotheses
- suggested pivots
- analyst-ready markdown report

### Current Analysis Coverage Estimate

The estimates below are directional and intended for planning conversations, not formal labor accounting.

| Analysis area | Estimated automation by current tool | Notes |
|---|---|---|
| Initial alert reading and normalization | `80-90%` | The tool ingests and restructures the notable consistently |
| IOC extraction | `75-90%` | Strong for indicators present in the alert payload |
| ATT&CK mapping and confidence scoring | `75-90%` | Strong for first-pass mapping from the available alert data |
| Evidence vs inference separation | `70-85%` | Useful for disciplined first-pass analysis |
| Initial verdict and summary drafting | `70-85%` | Good for analyst-ready first-pass writeup |
| Suggested pivots and next steps | `50-70%` | Helpful guidance, but still human-reviewed |
| Deep cross-system investigation | `20-40%` | Limited because the tool does not broadly execute pivots across tools and environments |
| Ongoing case refinement as new evidence arrives | `20-40%` | Requires human-led iterative investigation and judgment |

Current headline estimate:

- `Analysis portion of incident response`: `50-65%` automated
- `Full incident response lifecycle`: `15-25%` automated

### What Remains Primarily Manual In Analysis

Even within the narrower analysis slice, several important activities still remain primarily human-driven:

- `Validating whether the alert fits the broader case or campaign context`
  An investigator still has to decide whether a notable is part of a larger story, such as a known campaign, repeat attacker behavior, a phishing wave, a change window, a vulnerability disclosure, or an already-open case. That usually requires awareness of recent incidents, open tickets, threat reporting, and maintenance activity that do not exist inside the alert payload itself.

- `Deciding which competing hypothesis is most plausible after considering business, environmental, and historical context`
  The tool can generate competing hypotheses, but it does not fully understand which explanation best fits the organization's environment. Human analysts weigh things like whether a host is a domain controller, whether an account is service-related, whether a script is part of a known admin workflow, whether a cloud action is normal for that team, and whether similar alerts were previously closed as benign or malicious.

- `Performing deep pivots across SIEM, EDR, identity, cloud, email, proxy, endpoint, and case-management systems`
  Real investigation usually requires pulling new evidence from many places, not just interpreting the original notable. Analysts pivot into log search tools, endpoint telemetry, identity activity, cloud audit logs, email traces, proxy records, ticket history, and prior case notes to test hypotheses and fill evidence gaps.

- `Resolving conflicting or ambiguous evidence across multiple telemetry sources`
  Different systems often disagree. One data source may suggest interactive user activity while another shows automated service behavior; one timestamp may appear malicious until timezone or ingestion lag is considered; one hostname or user name may be normalized differently across tools. Resolving those conflicts requires a human to compare source quality, timing, fidelity, and known data-quality quirks before deciding what to trust.

- `Determining blast radius across users, hosts, accounts, workloads, or time windows`
  Blast-radius analysis asks how far the behavior spread and who or what was affected. That normally requires enumerating related users, devices, workloads, cloud resources, identities, mailboxes, and historical events over a broader time window than the initial alert.

- `Refining conclusions as new evidence arrives during an active investigation`
  Incident analysis is iterative. An alert may look suspicious at first, then shift toward benign after EDR evidence arrives, then become high-confidence malicious after identity or cloud evidence confirms follow-on activity. Human analysts keep updating the working theory as new facts arrive.

- `Judging escalation priority, business impact, and confidence when the available evidence is incomplete`
  Escalation decisions are rarely based on technical indicators alone. Analysts also weigh asset criticality, data sensitivity, user role, adversary intent, operational timing, regulatory exposure, and the cost of being wrong.

- `Choosing which recommended pivots are worth pursuing versus which are likely noise`
  A list of plausible pivots is not the same as an efficient investigation plan. Analysts still decide which pivots are highest value based on likelihood, cost, urgency, and local telemetry quality.

- `Incorporating organization-specific environment knowledge that is not present in the notable payload`
  Organizations have local knowledge that strongly affects analysis: asset criticality, naming conventions, service account patterns, expected admin tools, maintenance windows, lab networks, sanctioned automation, and recurring false-positive signatures. That knowledge often lives in people, runbooks, CMDBs, ticket history, or unwritten team memory, not in the alert itself.

- `Turning first-pass analysis into a defensible investigator conclusion for case progression`
  The tool can generate a solid first-pass writeup, but a human still has to decide whether that writeup is strong enough to move the case forward. That means checking whether the evidence supports the conclusion, whether caveats are stated clearly, whether alternative explanations were adequately considered, and whether the next recommended action is justified.

In short, the tool automates much of `first-pass alert interpretation`, but humans still do most of the `iterative investigative reasoning`.

## 3. What Remains Manual Outside Analysis

These broader incident response responsibilities remain mostly outside the current tool boundary:

- detection engineering and monitoring ownership
- evidence preservation and chain of custody
- containment decisions and execution
- eradication work
- recovery planning and validation
- cross-team coordination
- executive, legal, and compliance communication
- post-incident lessons learned and process improvement

Best characterization:

`The tool is an analyst co-pilot for first-pass notable triage and structured alert analysis, not a full incident response automation platform.`

## 4. Mature-State Automation Estimate

If the platform expands beyond the current notable-analysis workflow and adds:

- `SOP-backed RAG` for environment-specific investigation guidance
- `Splunk schema and data-dictionary RAG` for index-aware and field-aware SPL generation
- `Automated read-only SPL generation and execution` to test or disprove hypotheses
- substantial automation of the manual analysis tasks listed in Section 2

then the estimated percentage of the `overall incident response workflow` automated would likely rise to:

- `Conservative range`: `25-35%`
- `Aggressive but still reasonable range`: `40-50%`
- `Most defensible planning range`: `30-45%`

### Why The Percentage Rises

Those additions move the platform beyond alert summarization and into bounded investigative work. In practical terms, they automate more of:

- first-pass triage
- hypothesis generation
- hypothesis testing through actual Splunk queries
- Splunk-based evidence collection
- iterative case refinement within available telemetry
- blast-radius estimation where Splunk has the needed evidence
- escalation support grounded in local SOPs

### Why There Is Still A Ceiling

Even with those upgrades, a large part of full incident response would still remain outside the automated boundary:

- containment
- eradication
- recovery
- evidence preservation and forensics
- cross-team coordination
- legal, compliance, and executive communications
- post-incident remediation and lessons learned
- detection engineering ownership

### What Drives The Range

The range depends heavily on how much of the organization's real investigation work is answerable from Splunk and adjacent knowledge sources:

- environments where many cases are `Splunk-centric` will tend toward the higher end
- environments where key evidence lives in `EDR`, `identity`, `cloud`, `email`, or other tools without equivalent automation will stay closer to the lower end
- organizations with strong SOPs, a usable data dictionary, and stable field conventions are better candidates for the higher end

## 5. Mature-State Coverage By Incident Response Tier

For a fully mature version of the platform that includes `SOP-backed RAG`, `Splunk schema/field RAG`, `automated read-only SPL generation and execution`, and stronger iterative analysis support, the estimated coverage by responder tier is:

| Tier | What that tier mostly does | Estimated mature-tool coverage |
|---|---|---|
| `Tier 1` | Alert triage, validation, enrichment, first-pass analysis, and escalation recommendation | `75-90%` |
| `Tier 2` | Deeper investigation, correlation, scoping, hypothesis testing, and case refinement | `40-65%` |
| `Tier 3 / IR lead / specialist` | Advanced investigation, incident leadership, high-impact judgment, and response orchestration | `10-25%` |

If the comparison is narrowed to `analysis work` within each tier, the estimated coverage is somewhat higher:

- `Tier 1 analysis work`: `85-95%`
- `Tier 2 analysis work`: `50-75%`
- `Tier 3 analytical contribution`: `15-35%`

Why coverage differs by tier:

- `Tier 1` is the best fit because much of that work is SOP-driven, alert-centric, and compatible with structured retrieval and Splunk-backed hypothesis testing
- `Tier 2` benefits substantially from automated SPL execution and iterative reasoning, but still drops when evidence lives outside Splunk or requires more open-ended investigator judgment
- `Tier 3` remains lightly covered because that role includes high-consequence judgment, incident leadership, risk decisions, and cross-team coordination that go well beyond technical analysis

## 6. Repo-Specific Basis For This Mapping

This document's current-tool section is based on the workflow implemented in:

- `s3_notable_pipeline/README.md`
- `s3_notable_pipeline/lambda_handler.py`
- `s3_notable_pipeline/ttp_analyzer.py`
- `s3_notable_pipeline/markdown_generator.py`
- `llm_notable_analysis_onprem_systemd/README.md`

Those components show that the implemented boundary is a notable-in, report-out workflow with optional Splunk writeback, rather than a full incident management or response-action system.
