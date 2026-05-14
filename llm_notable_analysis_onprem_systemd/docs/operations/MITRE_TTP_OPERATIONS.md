# MITRE ATT&CK And TTP Operations

This guide helps customers understand and tune the local MITRE ATT&CK TTP ID
validation data used by the analyzer.

## What This Controls

The analyzer validates generated ATT&CK technique identifiers against a local
JSON file. This keeps model output from introducing unsupported or malformed TTP
IDs into reports.

## Recommended Starting Posture

- Use the bundled ATT&CK ID JSON file from the installed package.
- Change `MITRE_IDS_PATH` only when the customer has an approved ATT&CK data
  refresh process.
- Treat ATT&CK data updates as report-contract validation events.

## Customer Decisions

### Which ATT&CK version should be used?

**Setting:** `MITRE_IDS_PATH`

- The default points at the packaged extracted ID file.
- If the customer requires a newer ATT&CK release, generate and stage a
  compatible JSON file before changing config.
- Keep the selected version documented for analyst review and repeatability.

### How should invalid TTP output be handled operationally?

The runtime validates and filters generated TTP IDs; operators should review
reports where expected mappings are missing. Missing mappings may indicate:

- the alert lacks enough evidence for a specific technique
- the model produced an unsupported ID
- the local MITRE data is stale relative to analyst expectations

Do not loosen validation by editing code for a single customer; update the data
file through an approved refresh process instead.

## Config Quick Reference

| Area | Primary variables |
|------|-------------------|
| ATT&CK ID data | `MITRE_IDS_PATH` |

## Validation And Rollout

1. Confirm `MITRE_IDS_PATH` exists on the deployed host.
2. Process representative notables with known ATT&CK mappings.
3. Confirm reports include only valid technique IDs.
4. If updating ATT&CK data, rerun unit tests and representative report checks
   before promotion.

## Related Docs

- [`LLM_INFERENCE_OPERATIONS.md`](LLM_INFERENCE_OPERATIONS.md)
- [`../delivery_package/EXECUTIVE_ONPREM_WORKFLOW.md`](../delivery_package/EXECUTIVE_ONPREM_WORKFLOW.md)

