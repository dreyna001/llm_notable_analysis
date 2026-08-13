# Customer demo Splunk notables (standalone)

Synthetic Splunk ES-style notable JSON for four customer investigation scenarios.
**Demo only** — not wired into preview cases, golden eval, or production deploy paths.

## Use

1. Copy one or more files from `alerts/` into your environment `incoming/` directory.
2. Wait for the pipeline to process each file (one notable per file).
3. Open the analyst portal case and use chat against the archived analysis.

Optional: load `knowledge_base/*.md` into your Bedrock KB or on-prem KB path if you want
chat grounding for hunting-query and triage questions.

## Scenarios

| File | Use case | Expected disposition |
|------|----------|----------------------|
| `uc01-malware-lifecycle-true-positive.json` | Malware lifecycle timeline | Malicious |
| `uc01-malware-lifecycle-false-positive.json` | Malware lifecycle timeline | Benign |
| `uc02-credential-harvesting-true-positive.json` | Credential harvesting and weaponization | Malicious |
| `uc02-credential-harvesting-false-positive.json` | Credential harvesting and weaponization | Benign |
| `uc03-lateral-movement-true-positive.json` | Lateral movement / PtH / Kerberoasting | Malicious |
| `uc03-lateral-movement-false-positive.json` | Lateral movement / PtH / Kerberoasting | Benign |
| `uc04-dlp-cloud-exfil-true-positive.json` | DLP / insider threat cloud upload | Malicious |
| `uc04-dlp-cloud-exfil-false-positive.json` | DLP / insider threat cloud upload | Benign |

Fictional org: `CORP\` users, `*.corp.local` hosts (same namespace as preview cases 1-5).

## Notes

- Each file is a single Splunk notable rollup with enough correlated fields for timeline,
  MITRE mapping, and hunting pivots. The analyzer ingests one file per run.
- False positives include change tickets, approved tooling, or business-context fields
  that should drive a benign reconciliation when the model follows alert facts.
