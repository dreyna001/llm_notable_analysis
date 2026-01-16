## MITRE ATT&CK–Driven LLM Analysis (Notable Pipeline)

### How we anchor the LLM to MITRE ATT&CK
- Load the official ATT&CK v17.1 ID list (`enterprise_attack_v17.1_ids.json`) and build a validator that separates parent techniques and sub-techniques; only IDs from this list are allowed.
- Inject the **full allowed ID list** into the prompt (`get_valid_ttps_for_prompt`) and **drop any LLM outputs** whose `ttp_id` is not in the list.
- Force ATT&CK-aligned outputs via a strict JSON schema (keys: `ttp_analysis`, `attack_chain`, `ioc_extraction`, `evidence_vs_inference`, `containment_playbook`, `splunk_enrichment`).
- Require **exactly one previous and one next attack-chain step** with ATT&CK tactic IDs/URLs, plus tactic-span notes to keep reasoning grounded in ATT&CK tactics.

### Evidence discipline and scoring
- **Evidence-gate:** Only include a TTP if there is a direct data-component match in the alert; explanations must cite field=value evidence; lacking context forces lower confidence or parent technique selection.
- **Scoring rubric:** High ≥ 0.80 (direct), Medium 0.50–0.79 (suggestive), Low < 0.30 (needs corroboration). Uncertainty must be stated explicitly.
- **Tactic-span notes:** Each TTP explanation must state other tactics the technique commonly supports (prevents single-tactic anchoring).
- **Attack-chain constraint:** Exactly one “likely previous” and one “likely next” step (with rationale, what-to-check, uncertainty, and 3 investigation questions each).

### Prompt structure (key constraints)
- Analyst doctrine: evidence vs inference separation; containment focus (NIST 800-61); hunt across telemetry families.
- Allowed ATT&CK list: the validator-provided IDs are the only permissible `ttp_id` values.
- Output schema enforces:
  - **TTPs:** `ttp_id`, `ttp_name`, `confidence_score`, `explanation` (with quoted evidence), `tactic_span_note`, `evidence_fields`, `immediate_actions`, `remediation_recommendations` (with ATT&CK mitigations), `mitre_url`.
  - **Attack chain:** 1 previous + 1 next tactic, each with ATT&CK tactic IDs/URLs, why, what-to-check, uncertainty, and three investigation questions; kill-chain phase and tactic-span note.
  - **IOCs:** IPs, domains, users, hosts, file paths, processes, hashes, event IDs, URLs (empty arrays allowed).
  - **Correlation keys & time window suggestion.**
  - **Containment playbook:** immediate and short-term actions with ATT&CK mitigations (e.g., M1032, M1026, M1030).
  - **Splunk enrichment queries:** ATT&CK-aligned, time-bounded, and based only on alert evidence.
- ASCII-only rule (no emojis/Unicode) to keep outputs clean for downstream systems.

### Post-processing and validation
- Parse the model’s JSON; if parsing fails, return empty results and log the raw response.
- Map confidence fields to `score`, then **filter out invalid TTP IDs** with the validator.
- Retain the full model response for markdown reporting while using the validated TTP set for scoring.

### Runtime flow (ttp_analyzer.py)
1. Normalize alert → format into `[SUMMARY]`, `[RISK INDEX]`, `[RAW EVENT]`.
2. Build prompt with the allowed ATT&CK IDs and strict schema/rules.
3. Call Bedrock (Nova Pro) with retries.
4. Parse JSON, extract TTPs, enforce allowed IDs, and return validated TTPs + raw LLM response for reporting.

### Why this is ATT&CK-safe
- **Constrained vocabulary:** Only ATT&CK IDs from the shipped dataset are allowed.
- **Evidence-first:** Explanations must cite alert fields; weak context reduces confidence or forces parent techniques.
- **Tactic coverage:** Tactic-span notes and chain steps require explicit ATT&CK tactics/URLs.
- **Mitigation mapping:** Remediation references ATT&CK mitigations, keeping actions aligned to the framework.

### Keeping ATT&CK up to date
- We ship `enterprise_attack_v17.1_ids.json` to constrain the model; this file comes from the official MITRE ATT&CK data.
- To refresh, pull the current ATT&CK STIX data from the MITRE GitHub repo (e.g., `mitre-attack/attack-stix-data`), extract technique and sub-technique IDs, and regenerate the JSON ID list.
- The validator will then enforce the new allowed IDs automatically in prompts and post-processing.

