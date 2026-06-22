# Preview scenario fixtures (cases 1-5)

Cases 1-5 in the analyst portal preview UI are backed by this directory.

## Related docs

- [`docs/operations/analyst_portal/ANALYST_PORTAL_PREVIEW.md`](../docs/operations/analyst_portal/ANALYST_PORTAL_PREVIEW.md)
- [`docs/operations/analyst_portal/ANALYST_PORTAL_CHAT_SECURITY.md`](../docs/operations/analyst_portal/ANALYST_PORTAL_CHAT_SECURITY.md)

Analyst investigation questions (case 1 and Knowledge Base demo on case 5):
[`PREVIEW_CASE_INVESTIGATION_GUIDE.md`](../../PREVIEW_CASE_INVESTIGATION_GUIDE.md)
(repo root)

## Layout

- `alerts/` — raw Splunk-style notable JSON (input only; no LLM output).
- `bundles/` — **stored analyzer output** (alert + analysis). Commit these after generation so preview starts instantly with no analyzer LLM calls.
- `knowledge_base/` — committed SOC advisory docs for preview chat KB grounding (keyword-matched; no Postgres RAG).

## Stored analysis (default)

Cases 1-5 ship with **committed bundles** authored to match the analyzer prompt schema
(`scripts/preview_stored_analysis.py`). Preview reads these directly; no analyzer LLM is required.

To refresh bundles after editing alerts or stored analysis:

```powershell
.\.venv\Scripts\python.exe llm_notable_analysis_onprem_systemd\scripts\write_preview_bundles.py
```

## Optional: live analyzer generation

From the repo root with analyzer LLM reachable (`LLM_API_URL`, e.g. LiteLLM/vLLM):

```powershell
.\.venv\Scripts\python.exe llm_notable_analysis_onprem_systemd\scripts\generate_preview_scenarios.py
```

This runs each alert through `LocalLLMClient.analyze_alert` and overwrites `bundles/case-*.json`.
Use `--overwrite` to replace existing files.

Commit `bundles/` so teammates get the same preview data without calling the analyzer.

## Preview runtime

Opening the portal **only reads** `bundles/`. Cases 1-5 do not call the analyzer LLM.

The only live LLM in preview is **chatbot** synthesis (Bedrock/OpenAI/stub via `config.portal-preview.env`).

## Scenario map

| Case | Alert type |
|------|------------|
| 1 | Malware Beaconing |
| 2 | Impossible Travel |
| 3 | Suspicious PowerShell |
| 4 | Privilege Escalation Attempt |
| 5 | Suspicious RDP Lateral Movement |

Cases 6-55 remain lightweight in-memory fillers in `preview_portal_ui.py`.
