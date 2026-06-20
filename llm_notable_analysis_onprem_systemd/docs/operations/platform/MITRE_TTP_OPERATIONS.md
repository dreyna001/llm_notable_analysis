# MITRE ATT&CK And TTP Operations

This guide helps customers understand and tune the local MITRE ATT&CK TTP ID
validation data used by the on-prem analyzer.

## What This Controls

The analyzer validates generated ATT&CK technique identifiers against a local
JSON allowlist. Invalid IDs are removed from `ttp_analysis` before reports are
written; the service does not rewrite or substitute IDs.

Implementation: `onprem_service/ttp_validator.py` (`TTPValidator`), loaded at
startup from `config.MITRE_IDS_PATH` and applied in `local_llm_client.py` after
LLM output is parsed.

Bundled file (shipped in the package):

- Source tree: `src/llm_notable_analysis_onprem_systemd/onprem_service/enterprise_attack_v17.1_ids.json`
- Default runtime resolution: same directory as `onprem_service/config.py`
  (no env override required when the package layout is intact)

Typical deployed path (see `config.env.example`):

- `/opt/notable-analyzer/src/llm_notable_analysis_onprem_systemd/onprem_service/enterprise_attack_v17.1_ids.json`

## Bundled Data

| Item | Value |
|------|-------|
| ATT&CK release | Enterprise v17.1 |
| Technique IDs | 679 total (211 parent, 468 sub-technique) |
| ID format | `T####` or `T####.###` |
| JSON shape | Flat array of strings, e.g. `["T1001", "T1003.001", ...]` |

The validator splits IDs on `.` to track parent techniques and sub-techniques
separately; only exact matches pass.

## Recommended Starting Posture

- Use the bundled ATT&CK v17.1 ID file from the installed package.
- Change `MITRE_IDS_PATH` only when the customer has an approved ATT&CK data
  refresh process.
- Treat ATT&CK data updates as report-contract validation events.

## Customer Decisions

### Which ATT&CK version should be used?

**Setting:** `MITRE_IDS_PATH`

- **Default:** `Path(__file__).parent / "enterprise_attack_v17.1_ids.json"` in
  `config.py` (overridden by the `MITRE_IDS_PATH` environment variable).
- **Example deployed value:** see `config.env.example`.
- If the customer requires a newer ATT&CK release, generate and stage a
  compatible JSON file (same flat-array schema) before changing config.
- Keep the selected version documented for analyst review and repeatability.

### How should invalid TTP output be handled operationally?

After LLM parsing, `filter_valid_ttps()` keeps only entries whose `ttp_id` is
in the allowlist. Filtered IDs are logged at WARNING; startup logs the loaded
count at INFO.

Operators should review reports where expected mappings are missing. Missing
mappings may indicate:

- the alert lacks enough evidence for a specific technique
- the model produced an unsupported ID
- the local MITRE data is stale relative to analyst expectations

Do not loosen validation by editing code for a single customer; update the data
file through an approved refresh process instead.

**Startup behavior:** if the IDs file is missing, unreadable, empty, or invalid
JSON, `TTPValidator` initialization fails and the analyzer exits before
processing notables.

## Config Quick Reference

| Area | Primary variables |
|------|-------------------|
| ATT&CK ID data | `MITRE_IDS_PATH` |

## Refresh Workflow

There is no on-prem extract script in this package. To regenerate from official
MITRE data, adapt `s3_notable_pipeline/scripts/extract_ttp_ids.py` (update the
MITRE spreadsheet URL for the target release and point `output_path` at your
staged file), or follow your approved offline ATT&CK export process.

After staging a new file:

1. Copy the JSON to the host (or update the package).
2. Set `MITRE_IDS_PATH` to the new path if the filename or location changed.
3. Restart the analyzer service and confirm startup logs show a non-zero TTP
   count.
4. Rerun tests and representative report checks before promotion.

```bash
cd llm_notable_analysis_onprem_systemd
python -m pytest tests/onprem_service/test_integration_mocks.py -k filter_invalid_ttps -v
python -m pytest tests/onprem_service/test_local_llm_client_contract.py -k scored_ttps -v
```

For air-gapped refresh steps, see
[`../deployment/AIRGAPPED_DEPLOYMENT.md`](../deployment/AIRGAPPED_DEPLOYMENT.md).

## Validation And Rollout

1. Confirm `MITRE_IDS_PATH` exists on the deployed host and is readable by the
   service account.
2. Restart the service and confirm startup logs report loaded TTP counts.
3. Process representative notables with known ATT&CK mappings.
4. Confirm JSON and markdown reports include only valid technique IDs.
5. If updating ATT&CK data, rerun the pytest slice above and one end-to-end
   notable before promotion.

## Related Docs

- [`LLM_INFERENCE_OPERATIONS.md`](LLM_INFERENCE_OPERATIONS.md)
- [`../deployment/AIRGAPPED_DEPLOYMENT.md`](../deployment/AIRGAPPED_DEPLOYMENT.md)
- [`../../delivery_package/EXECUTIVE_ONPREM_WORKFLOW.md`](../../delivery_package/EXECUTIVE_ONPREM_WORKFLOW.md)
- [`../../../config.env.example`](../../../config.env.example) (`MITRE_IDS_PATH`)
