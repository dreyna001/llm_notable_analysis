#!/usr/bin/env python3
# python3.12.8
"""
LLM-based TTP mapping inference.
Uses LLM to analyze security logs and map them to MITRE ATT&CK TTPs.
"""

import os
import json
import requests
import time
import argparse
from typing import List, Tuple, Dict, Any, Set
from openai import OpenAI
from pathlib import Path
from datetime import datetime
import logging
from dotenv import load_dotenv

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

load_dotenv()

# Validate required environment variables
api_key = os.getenv("OPENAI_API_KEY")
if not api_key:
    raise ValueError(
        "OPENAI_API_KEY environment variable is not set. "
        "Please set it in your .env file or environment variables."
    )

# MITRE ATT&CK data file - use Path(__file__).parent for relative paths
SCRIPT_DIR = Path(__file__).parent
ATTACK_DATA_FILE = SCRIPT_DIR / "enterprise_attack_v17.1_ids.json"  # Pre-extracted technique IDs
ATTACK_URL = "https://raw.githubusercontent.com/mitre/cti/master/enterprise-attack/enterprise-attack.json"

def download_attack_data() -> bool:
    """Download MITRE ATT&CK data if pre-extracted IDs file doesn't exist locally."""
    mitre_data_file = SCRIPT_DIR / "mitre_attack_data.json"
    if mitre_data_file.exists():
        logger.info(f"Using existing MITRE ATT&CK data: {mitre_data_file}")
        return True
    
    logger.info(f"Downloading MITRE ATT&CK data from {ATTACK_URL}...")
    try:
        response = requests.get(ATTACK_URL, timeout=60)
        response.raise_for_status()
        
        with open(mitre_data_file, 'w') as f:
            json.dump(response.json(), f, indent=2)
        
        logger.info(f"Downloaded and saved to {mitre_data_file}")
        return True
    except requests.exceptions.RequestException as e:
        logger.error(f"Failed to download MITRE ATT&CK data: {e}")
        logger.error("Script will continue offline, but TTP validation may be limited.")
        return False
    except IOError as e:
        logger.error(f"Failed to write MITRE ATT&CK data file: {e}")
        return False

class TTPValidator:
    """Simple validator for MITRE ATT&CK TTP IDs using local data."""
    
    def __init__(self):
        """Initialize with cached valid TTPs from local file."""
        self._valid_subtechniques: Set[str] = set()
        self._valid_parent_techniques: Set[str] = set()
        self._load_valid_ttps()
    
    def _load_valid_ttps(self):
        """Load valid technique IDs from pre-extracted MITRE ATT&CK IDs file."""
        # Check if we have the pre-extracted IDs file
        if ATTACK_DATA_FILE.exists():
            try:
                with open(ATTACK_DATA_FILE, 'r') as f:
                    ttp_ids = json.load(f)
                
                # Separate parent techniques from sub-techniques
                for ttp_id in ttp_ids:
                    if "." in ttp_id:
                        # Sub-technique
                        self._valid_subtechniques.add(ttp_id)
                    else:
                        # Parent technique
                        self._valid_parent_techniques.add(ttp_id)
                
                total_ttps = len(self._valid_subtechniques) + len(self._valid_parent_techniques)
                logger.info(f"Loaded {len(self._valid_subtechniques)} valid sub-techniques and {len(self._valid_parent_techniques)} parent techniques from pre-extracted IDs (total: {total_ttps})")
                
                # Health check: fail if zero TTPs loaded
                if total_ttps == 0:
                    raise ValueError("No TTPs loaded from pre-extracted IDs file. File may be empty or corrupted.")
                
                return
            except (IOError, json.JSONDecodeError) as e:
                logger.error(f"Error reading pre-extracted IDs file {ATTACK_DATA_FILE}: {e}")
            except ValueError:
                raise  # Re-raise health check failures
            except Exception as e:
                logger.error(f"Unexpected error reading pre-extracted IDs file: {e}")
        
        # Fallback: try to download and parse full data
        logger.warning("Pre-extracted IDs file not found, falling back to full MITRE ATT&CK data download...")
        mitre_data_file = SCRIPT_DIR / "mitre_attack_data.json"
        if not download_attack_data():
            raise ValueError("Unable to load MITRE ATT&CK data. No validation will occur. Please ensure enterprise_attack_v17.1_ids.json exists or network connectivity is available.")
        
        try:
            with open(mitre_data_file, 'r') as f:
                attack_data = json.load(f)
        except IOError as e:
            logger.error(f"Error reading MITRE ATT&CK data file {mitre_data_file}: {e}")
            raise
        except json.JSONDecodeError as e:
            logger.error(f"Invalid JSON in MITRE ATT&CK data file: {e}")
            raise
        
        # Parse MITRE ATT&CK JSON structure
        for obj in attack_data.get("objects", []):
            if obj.get("type") == "attack-pattern":
                external_refs = obj.get("external_references", [])
                if external_refs:
                    ttp_id = external_refs[0].get("external_id", "")
                    if ttp_id:
                        if "." in ttp_id:
                            # Sub-technique
                            self._valid_subtechniques.add(ttp_id)
                        else:
                            # Parent technique
                            self._valid_parent_techniques.add(ttp_id)
        
        total_ttps = len(self._valid_subtechniques) + len(self._valid_parent_techniques)
        logger.info(f"Loaded {len(self._valid_subtechniques)} valid sub-techniques and {len(self._valid_parent_techniques)} parent techniques from full dataset (total: {total_ttps})")
        
        # Health check: fail if zero TTPs loaded
        if total_ttps == 0:
            raise ValueError("No TTPs loaded from MITRE ATT&CK data. Validation cannot proceed.")
    
    def is_valid_ttp(self, ttp_id: str) -> bool:
        """Check if TTP ID is valid (sub-technique or parent technique)."""
        return ttp_id in self._valid_subtechniques or ttp_id in self._valid_parent_techniques
    
    def get_valid_ttps_for_prompt(self) -> str:
        """Get formatted list of valid TTPs for inclusion in prompt."""
        all_ttps = sorted(list(self._valid_subtechniques)) + sorted(list(self._valid_parent_techniques)) # not sure if its worth sorting this or no
        return ", ".join(all_ttps)
    
    def filter_valid_ttps(self, scored_ttps: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """Filter out invalid TTPs and return only valid ones."""
        valid_ttps = []
        invalid_ttps = []
        
        for ttp in scored_ttps:
            ttp_id = ttp["ttp_id"]
            if self.is_valid_ttp(ttp_id):
                valid_ttps.append(ttp)
            else:
                invalid_ttps.append(ttp_id)
        
        if invalid_ttps:
            logger.warning(f"Filtered out invalid TTPs: {invalid_ttps}")
        
        return valid_ttps
    
    def get_ttp_count(self) -> int:
        """Get total count of loaded TTPs."""
        return len(self._valid_subtechniques) + len(self._valid_parent_techniques)

# =============================================================================
# PROMPT SECTIONS - Modular prompt components for maintainability
# =============================================================================

SYSTEM_PROMPT = "You are a cybersecurity expert specializing in MITRE ATT&CK TTP analysis."

ANALYST_DOCTRINE = """
ANALYST DOCTRINE (apply to every case)
- MITRE ATT&CK is many-to-many: a single technique may support several tactics. Always state (a) the tactic you're assigning in this alert AND (b) other plausible tactics this technique commonly serves (tactic-span note). Base on MITRE ATT&CK v17.
- FACT vs. INFERENCE: List literal, direct alert evidence first (field=value from the alert), then inferences and assumptions separately (with uncertainty).
- IOC labeling hygiene: Do not list core OS/generic binaries as IOCs without explicit malicious context. Instead, list as "system_components_observed" if present in the alert.
- STATELESS ANALYSIS: Reasoning must rely only on observable fields in this notable. If a required fact is not present, state "unknown" and list what would disambiguate.
"""

EVIDENCE_GATE = """
EVIDENCE-GATE: Only include a technique (TTP) if:
A. There is a direct data-component match in the alert (quote it).
B. Your explanation cites the matching field/value.
C. No inference or external context is necessary.
D. If evidence correctness depends on context not in the log (e.g., domain internal/external, IP a DC), drop to the parent technique or reduce confidence by >=0.20 and state the missing context in your explanation.
"""

SCORING_RUBRIC = """
Scoring Rubric:
- high >= 0.80 = direct, unambiguous
- med 0.50-0.79 = strongly suggestive; one element missing
- low < 0.30 = plausible but needs corroboration
"""

TACTIC_FRAMING = """
TACTIC FRAMING (Notable-First)
Given this notable ONLY (stateless), do:
- List the ATT&CK technique(s) implicated.
- Provide a "Primary Tactic (most plausible)" and "Secondary Tactic(s) (possible)" based on the observable semantics of the event(s), not on assumed environment.

Rules:
- Do not label a tactic as "Primary" unless the notable contains direct supporting evidence for that tactic.
- If multiple tactics fit, keep "tactic span" but explicitly state what additional fields/logs would disambiguate primary vs secondary.
- If required context is missing, state "unknown" and list what would disambiguate.

Output in tactic_framing key:
- primary_tactic: object with tactic_id, tactic_name, justification (1-2 sentences referencing fields in the notable)
- secondary_tactics: list of objects with tactic_id, tactic_name, why_plausible (1 sentence each)
- disambiguation_checklist: list of 3-5 specific questions/fields/log sources to confirm primary vs secondary
"""

BENIGN_EXPLANATIONS = """
BENIGN EXPLANATIONS (Legitimate Activity Hypotheses)
Provide 3-5 plausible legitimate explanations for this notable.

For each hypothesis include:
- hypothesis: string (the benign explanation)
- expect_if_true: list of 1-2 concrete indicators we would expect to see if this is legitimate
- argue_against: string (1 concrete indicator that would argue against this being legitimate)
- best_validation: string (the single best query/log source to validate it quickly)

Keep it concise and do not assume extra telemetry unless you name it explicitly.
"""

CAUSAL_HUMILITY = """
CAUSAL HUMILITY + PIVOT STRATEGY (Stateless)
Do not assume a single root cause from one notable. Use this reasoning procedure:

1) Generate 3-5 competing hypotheses for how the observable could occur.
   - Include at least 1 benign hypothesis.
   - Include at least 2 distinct adversary hypotheses (different initial vectors).

2) For each hypothesis:
   - hypothesis_type: "benign" or "adversary"
   - hypothesis: string description
   - evidence_support: list of field=value pairs from the notable that support it
   - evidence_gaps: list of critical evidence that is missing
   - best_pivots: list of 1-2 pivots (each with log_source and key_fields)

3) Pivot selection rules (use what is available; do not invent telemetry):
   - If network origin matters: pivot to VPN/jump host/PAM session logs and firewall allow logs.
   - If identity is in question: pivot to IdP sign-in logs (if federated/hybrid) and AD authentication trails.
   - If local compromise is suspected: pivot to endpoint telemetry (Sysmon/EDR) and process/access signals.
   - If only Windows Security logs exist, state limitations explicitly and downgrade confidence.
"""

CONTEXT_ENRICHMENT = """
CONTEXT ENRICHMENT + BASELINE-FIRST (Reasoning Rule)
When a notable includes any network-origin fields (e.g., IpAddress/src_ip/dest_ip), do:

A) Enrichment (only if the field exists):
- geo: iplocation on the IP
- ownership: ASN/org lookup for the IP
- internal_vs_external: check against internal CIDR ranges
- known_egress: check against known VPN/proxy/jump egress lists
- reputation: only if a reputation source is available; otherwise state "not available"

B) Baseline (avoid one-off conclusions):
- Propose baseline queries that answer:
  - How common is this actor->target interaction in the last N days?
  - What source IP ranges are typical for this user/host/app?
  - Is the timing/volume unusual relative to baseline?
- Prefer per-entity baselines (user, host, source IP range) over global counts.

C) Output requirements:
- State the enriched context explicitly OR state "not available" for each.
- Use baseline results (or absence of baseline data) to set confidence.
- If baseline cannot be run, downgrade confidence and label as "needs baseline validation".
- List any limitations in the limitations field.
"""

MITIGATION_RULES = """
MITIGATIONS (Containment + Hardening only)
When proposing mitigations, do NOT list generic best practices. Use this procedure:

1) Identify the likely ATT&CK technique(s) implicated by the evidence.

2) Propose mitigations in TWO tiers only (max 5 total, ranked by risk reduction):
   - Containment (hours): actions that reduce immediate risk
   - Hardening (days/weeks): controls that reduce recurrence

3) For each mitigation, include:
   - rationale: which evidence/inference it addresses (cite fields/observables)
   - preconditions: environment dependencies inferred from notable, or "unknown" if not determinable
   - tradeoffs: operational impact or failure modes
   - confidence_effect: what would increase/decrease confidence that this mitigation is the right priority

4) Ensure mitigations match the scenario:
   - Only include controls relevant to the technique and feasible under inferred conditions
   - Avoid suggesting disruptive actions (e.g., "isolate DC") without a narrower, safer alternative
   - Cite ATT&CK mitigations by ID where relevant (e.g., M1032, M1026, M1030)
"""

PROCEDURE = """
PROCEDURE:
1. **Think silently**: classify activity -> tactics -> candidate techniques.
2. Self-check against the tactic checklist.
3. Decode/deobfuscate common encodings (Base64, hex, URL-encoded, gzip) if found.
4. Use sub-techniques when specific variant is confirmed (e.g., T1059.001 for PowerShell).
5. Default to parent techniques when sub-technique cannot be precisely assigned.
6. Apply Tactic Framing, Benign Explanations, Causal Humility, and Context Enrichment reasoning.
"""

OUTPUT_SCHEMA = """
OUTPUT FORMAT: Return a single valid JSON object with these top-level keys:
- `ttp_analysis`
- `attack_chain`
- `ioc_extraction`
- `correlation_keys`
- `evidence_vs_inference`
- `containment_playbook`
- `splunk_enrichment`
- `tactic_framing`
- `benign_explanations`
- `competing_hypotheses`
- `context_enrichment`

SCHEMA:
- ttp_analysis: list of objects, each with:
    - ttp_id: string (MITRE ATT&CK ID, e.g. "T1059.001")
    - ttp_name: string (official technique name)
    - confidence_score: float (0.0-1.0)
    - explanation: string (A brief explanation of why this TTP was inferred, using quoted evidence from the alert. End with "Uncertainty: [brief statement]" acknowledging what is inferred vs. direct evidence, and any missing context like geo/VPN metadata, edge telemetry, etc.)
    - tactic_span_note: string (One sentence naming other ATT&CK tactics this technique commonly supports and why they may apply here)
    - evidence_fields: list of strings (Specific alert field=value pairs that directly support this TTP)
    - immediate_actions: string (Urgent remediation steps if this TTP is confirmed)
    - remediation_recommendations: string (Specific defensive measures citing MITRE mitigations by ID)
    - mitre_url: mitre version permalink url for the technique

- attack_chain: object with:
    - likely_previous_steps: list of EXACTLY 1 object with:
        - tactic_id: string (MITRE ATT&CK Tactic ID)
        - tactic_name: string (official tactic name)
        - mitre_url: string (tactic MITRE version permalink URL)
        - why_this_step: string (One concise sentence explaining the hypothesis - cite alert field=value pairs)
        - what_to_check: string (One concise sentence listing specific artifacts, event IDs, or data sources to investigate)
        - uncertainty_alternatives: string (One concise sentence describing what is uncertain or alternative explanations)
        - investigation_tree: object with exactly 3 questions (Q1, Q2, Q3), each containing question: string
    - likely_next_steps: list of EXACTLY 1 object (same structure as likely_previous_steps)
    - kill_chain_phase: string (must match MITRE phase name)
    - tactic_span_note: string (One-line note naming other ATT&CK tactics the top technique supports)

- ioc_extraction: object with:
    - ip_addresses: list of strings
    - domains: list of strings
    - user_accounts: list of strings
    - hostnames: list of strings
    - file_paths: list of strings
    - process_names: list of strings
    - file_hashes: list of strings
    - event_ids: list of strings
    - urls: list of strings

- correlation_keys: object with:
    - primary_indicators: list of strings
    - search_terms: list of strings
    - time_window_suggested: string

- evidence_vs_inference: object with:
    - evidence: list of strings (Literal field=value facts from the alert)
    - inferences: list of strings (Hypotheses with noted uncertainties)

- containment_playbook: object with:
    - immediate: list of strings (2-4 concrete containment actions within hours)
    - short_term: list of strings (2-4 hardening actions within 24-48h)
    - references: list of strings (ATT&CK Mitigations by ID)

- splunk_enrichment: list of 1-4 objects, each with:
    - phase: "previous" or "next"
    - supports_tactic: string
    - purpose: string
    - query: string (Splunk SPL using only observable data; index/sourcetype as PLACEHOLDER)
    - confidence_boost_rule: string
    - confidence_reduce_rule: string

- tactic_framing: object with:
    - primary_tactic: object with tactic_id, tactic_name, justification
    - secondary_tactics: list of objects with tactic_id, tactic_name, why_plausible
    - disambiguation_checklist: list of 3-5 strings (questions/fields/log sources to confirm)

- benign_explanations: list of 3-5 objects, each with:
    - hypothesis: string (the benign explanation)
    - expect_if_true: list of 1-2 strings (indicators expected if legitimate)
    - argue_against: string (indicator arguing against legitimacy)
    - best_validation: string (best query/log source to validate)

- competing_hypotheses: list of 3-5 objects, each with:
    - hypothesis_type: "benign" or "adversary"
    - hypothesis: string
    - evidence_support: list of strings (field=value pairs supporting this)
    - evidence_gaps: list of strings (critical missing evidence)
    - best_pivots: list of objects with log_source and key_fields

- context_enrichment: object with:
    - enrichment_steps: list of objects, each with field, enrichment_type, result_or_status
    - baseline_queries: list of objects, each with purpose and query
    - limitations: string (what cannot be concluded from provided data)
"""

RULES = """
RULES:
- CRITICAL: NO EMOJIS OR UNICODE SYMBOLS; Use only plain ASCII text characters.
- ATTACK CHAIN: ALWAYS include EXACTLY 1 previous step and EXACTLY 1 next step as hypotheses.
- TIME WINDOWS: If ALERT_TIME is provided, previous queries use earliest=-24h@h latest=ALERT_TIME, next queries use earliest=ALERT_TIME latest=+24h@h. If not provided, use relative time.
- EVIDENCE VS INFERENCE: Populate "evidence" with only direct field=value facts. Populate "inferences" with hypotheses and note uncertainties.
- CONTAINMENT: Keep to 3-6 bullets total. Cite ATT&CK mitigations by ID.
- HUNT FAMILIES: Provide 3-4 enrichment queries covering applicable telemetry families.
- All enrichment queries must use only evidence present in the alert; index/sourcetype as PLACEHOLDER.
- TTP EXPLANATIONS: Always end with "Uncertainty: [brief statement]".
- IOC EXTRACTION: Extract ALL IOCs; leave arrays empty [] if not found. Do not label core OS components as IOCs without malicious context.
- STATELESS: If context is missing (e.g., IP ownership, VPN status), state "unknown" and list what would disambiguate.
- Do not return markdown, comments, or extra prose.
- Output only the raw JSON object.
- All fields and keys must match exactly.
"""


class LLMNotableAnalysis:
    def __init__(self):
        """Initialize the LLM notable analysis engine."""
        # API key validated at module level, but double-check
        if not api_key:
            raise ValueError("OPENAI_API_KEY not set (this should have been caught at startup)")
        self.client = OpenAI(api_key=api_key)
        self.validator = TTPValidator()  # Initialize validator

    def _build_prompt(self, alert_text: str, alert_time: str, valid_ttps_list: str) -> str:
        """Assemble the full prompt from modular sections."""
        alert_time_str = f"\n**ALERT_TIME:** {alert_time}\n" if alert_time else ""
        
        return f"""You are a cybersecurity expert mapping MITRE ATT&CK techniques from a single alert.
{alert_time_str}
---

{ANALYST_DOCTRINE}

{EVIDENCE_GATE}

{SCORING_RUBRIC}

{TACTIC_FRAMING}

{BENIGN_EXPLANATIONS}

{CAUSAL_HUMILITY}

{CONTEXT_ENRICHMENT}

{MITIGATION_RULES}

{PROCEDURE}

Use only the ATT&CK techniques from this allowed list:
{valid_ttps_list}

SECURITY ALERT INPUT:
{alert_text}

---

{OUTPUT_SCHEMA}

---

{RULES}
"""

    def format_alert_input(self, summary: str, risk_index: Dict[str, Any], raw_log: Dict[str, Any]) -> str:
        """Format alert data into a structured text block."""
        risk_text = "\n".join([
            f"Risk Score: {risk_index.get('risk_score', 'N/A')}",
            f"Source Product: {risk_index.get('source_product', 'N/A')}",
            f"Threat Category: {risk_index.get('threat_category', 'N/A')}",
        ])
        raw_text = " ".join(f"{k}={v}" for k, v in raw_log.items())
        return f"""[SUMMARY]
{summary or 'N/A'}

[RISK INDEX]
{risk_text}

[RAW EVENT]
{raw_text}"""

    def analyze_ttp(self, alert_text: str, alert_time: str = None) -> List[Dict[str, Any]]:
        """
        Use LLM to analyze the alert and identify relevant MITRE ATT&CK TTPs.
        Returns list of (ttp_id, confidence_score) pairs with invalid TTPs filtered out.
        """
        logger.info("Starting TTP analysis")
        start_time = time.time()
        
        # Get valid TTPs for the prompt
        logger.info("Loading valid TTPs for prompt")
        valid_ttps_list = self.validator.get_valid_ttps_for_prompt()
        # Use existing count method instead of inefficient split()
        total_ttps = self.validator.get_ttp_count()
        logger.info(f"Loaded {total_ttps} valid TTPs for prompt")
        
        logger.info("Constructing prompt")
        prompt = self._build_prompt(alert_text, alert_time, valid_ttps_list)

        logger.info(f"Prompt length: {len(prompt)} characters")
        logger.info(f"Alert text length: {len(alert_text)} characters")
        
        # Input validation: ensure alert_text is not empty
        if not alert_text or not alert_text.strip():
            logger.error("Alert text is empty or whitespace only. Skipping analysis.")
            return []
        
        try:
            logger.info("Making OpenAI API call...")
            api_start_time = time.time()
            
            # Call LLM with retry logic
            max_retries = 3
            retry_delay = 5  # seconds
            
            for attempt in range(max_retries):
                try:
                    logger.info(f"API call attempt {attempt + 1}/{max_retries}")
                    
                    # Call LLM
                    response = self.client.chat.completions.create(
                        model="gpt-5-chat-latest", # o3-2025-04-16
                        messages=[
                            {"role": "system", "content": "You are a cybersecurity expert specializing in MITRE ATT&CK TTP analysis."},
                            {"role": "user", "content": prompt}
                        ],
                        temperature=1,
                        response_format={"type": "json_object"},
                        timeout=180  # 60 second timeout
                    )
                    
                    api_end_time = time.time()
                    logger.info(f"API call completed in {api_end_time - api_start_time:.2f} seconds")
                    break  # Success, exit retry loop
                    
                except (requests.exceptions.RequestException, 
                        requests.exceptions.Timeout,
                        requests.exceptions.ConnectionError) as api_error:
                    logger.warning(f"API call attempt {attempt + 1} failed (network error): {str(api_error)}")
                    if attempt < max_retries - 1:
                        logger.info(f"Retrying in {retry_delay} seconds...")
                        time.sleep(retry_delay)
                        retry_delay *= 2  # Exponential backoff
                    else:
                        logger.error(f"All {max_retries} API call attempts failed")
                        raise
                except Exception as api_error:
                    # Catch other OpenAI API errors (authentication, rate limits, etc.)
                    error_type = type(api_error).__name__
                    logger.warning(f"API call attempt {attempt + 1} failed ({error_type}): {str(api_error)}")
                    if attempt < max_retries - 1:
                        logger.info(f"Retrying in {retry_delay} seconds...")
                        time.sleep(retry_delay)
                        retry_delay *= 2  # Exponential backoff
                    else:
                        logger.error(f"All {max_retries} API call attempts failed")
                        raise
            
            # Parse the response
            logger.info("Parsing LLM response")
            content = response.choices[0].message.content
            logger.info(f"Raw LLM response length: {len(content)} characters")
            
            parse_start_time = time.time()
            try:
                result = json.loads(content)
            except json.JSONDecodeError as e:
                logger.error(f"Failed to parse JSON response: {e}")
                logger.error(f"Response content (first 500 chars): {content[:500]}")
                return []  # Return empty list, don't retry
            
            parse_end_time = time.time()
            logger.info(f"JSON parsing completed in {parse_end_time - parse_start_time:.2f} seconds")
            logger.info(f"Parsed JSON result type: {type(result)}")
            
            # Log the raw JSON structure for debugging
            logger.info("Raw LLM JSON Response Structure:")
            logger.info(json.dumps(result, indent=2))
            
            # Also save to a file for inspection
            debug_json_file = SCRIPT_DIR / f"llm_raw_response_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
            with open(debug_json_file, 'w', encoding='utf-8') as debug_f:
                json.dump(result, debug_f, indent=2)
            logger.info(f"Raw JSON response saved to: {debug_json_file}")

            # Store the last LLM response for output enrichment
            self.last_llm_response = result
            
            # Extract TTPs from the new structured response
            scored_ttps = []
            
            # Response validation: ensure result is a dict with required structure
            if not isinstance(result, dict):
                logger.error(f"Expected dict response, got {type(result)}")
                return []
            
            # Handle the new structure with ttp_analysis, attack_chain, splunk_enrichment
            if "ttp_analysis" in result:
                logger.info(f"Processing new structured response with ttp_analysis")
                if not isinstance(result["ttp_analysis"], list):
                    logger.error(f"ttp_analysis must be a list, got {type(result['ttp_analysis'])}")
                    return []
                
                # Validate each TTP item has required fields
                scored_ttps = []
                for i, item in enumerate(result["ttp_analysis"]):
                    if not isinstance(item, dict):
                        logger.warning(f"Skipping invalid TTP item at index {i}: not a dict")
                        continue
                    if "ttp_id" not in item:
                        logger.warning(f"Skipping invalid TTP item at index {i}: missing ttp_id")
                        continue
                    
                    scored_ttps.append({
                        "ttp_id": item["ttp_id"],
                        "ttp_name": item.get("ttp_name", ""),
                        "score": float(item.get("confidence_score", item.get("score", item.get("confidence", 0)))),
                        "explanation": item.get("explanation", ""),
                        "tactic_span_note": item.get("tactic_span_note", ""),
                        "evidence_fields": item.get("evidence_fields", []),
                        "immediate_actions": item.get("immediate_actions", ""),
                        "remediation_recommendations": item.get("remediation_recommendations", ""),
                        "mitre_url": item.get("mitre_url", "")
                    })
                logger.info(f"Extracted {len(scored_ttps)} TTPs from ttp_analysis")
            
            # Fallback to old format handling for backward compatibility
            elif isinstance(result, dict):
                # Handle single TTP response
                if "ttp_id" in result:
                    score_val = None
                    for k in ("score", "confidence_score", "confidence"):
                        if k in result:
                            score_val = float(result[k])
                            break
                    if score_val is not None:
                        scored_ttps = [{
                            "ttp_id": result["ttp_id"],
                            "ttp_name": result.get("ttp_name", ""),
                            "score": score_val,
                            "explanation": result.get("explanation", ""),
                            "mitre_url": result.get("mitre_url", "")
                        }]
                
                # Handle response with array of TTPs
                for key in ["response", "result", "results", "ttps", "analysis"]:
                    if key in result and isinstance(result[key], list):
                        logger.info(f"About to process {len(result[key])} TTP items from key '{key}'")
                        if result[key]:
                            logger.info(f"First item: {result[key][0]}")
                            logger.info(f"First item keys: {list(result[key][0].keys())}")
                        scored_ttps = [
                            {
                                "ttp_id": item["ttp_id"],
                                "ttp_name": item.get("ttp_name", ""),
                                "score": float(item.get("score", item.get("confidence_score", item.get("confidence", 0)))),
                                "explanation": item.get("explanation", ""),
                                "mitre_url": item.get("mitre_url", "")
                            }
                            for item in result[key]
                        ]
                        break
            elif isinstance(result, list):
                scored_ttps = [
                    {
                        "ttp_id": item["ttp_id"],
                        "ttp_name": item.get("ttp_name", ""),
                        "score": float(item.get("score", item.get("confidence_score", item.get("confidence", 0)))),
                        "explanation": item.get("explanation", ""),
                        "mitre_url": item.get("mitre_url", "")
                    }
                    for item in result
                ]
            
            # Filter out invalid TTPs (safety net)
            logger.info("Filtering invalid TTPs")
            valid_ttps = self.validator.filter_valid_ttps(scored_ttps)
            logger.info(f"Final valid TTPs: {len(valid_ttps)}")
            
            total_time = time.time() - start_time
            logger.info(f"Total TTP analysis completed in {total_time:.2f} seconds")
            
            return valid_ttps
            
        except (requests.exceptions.RequestException, 
                requests.exceptions.Timeout,
                requests.exceptions.ConnectionError) as e:
            logger.error(f"Network error during API call: {str(e)}")
            return []
        except ValueError as e:
            logger.error(f"Validation error: {str(e)}")
            return []
        except json.JSONDecodeError as e:
            logger.error(f"JSON parsing error: {str(e)}")
            return []
        except Exception as e:
            logger.error(f"Unexpected error calling LLM: {str(e)}")
            logger.error(f"Exception type: {type(e).__name__}")
            import traceback
            logger.error(f"Full traceback: {traceback.format_exc()}")
            return []

def main():
    logger.info("Starting LLM TTP Analysis Tool")
    start_time = time.time()
    
    # Parse command line arguments
    parser = argparse.ArgumentParser(description='LLM TTP Analysis Tool')
    parser.add_argument('-n', '--num_cases', type=int, default=None, help='Number of test cases to run (default: all cases)')
    parser.add_argument('--start_case', type=int, default=0,
                       help='Starting test case index (default: 0)')
    args = parser.parse_args()
    
    logger.info(f"Arguments: num_cases={args.num_cases}, start_case={args.start_case}")
    
    # Example usage
    logger.info("Initializing LLMNotableAnalysis")
    analyzer = LLMNotableAnalysis()
    
    # Create output file with timestamp
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    output_file = SCRIPT_DIR / f"llm_notable_analysis_{timestamp}.md"
    logger.info(f"Output file: {output_file}")
    
    # Import synthetic test cases from external file
    from synthetic_logs import get_test_cases
    logger.info("Loading test cases")
    try:
        test_cases = get_test_cases()
    except Exception as e:
        logger.error(f"Failed to load test cases: {e}")
        raise
    
    if not test_cases:
        logger.error("No test cases loaded. Exiting.")
        return
    
    start = args.start_case
    end = start + args.num_cases if args.num_cases is not None else None
    selected_cases = test_cases[start:end]
    
    if not selected_cases:
        logger.error(f"No test cases selected (start: {start}, num_cases: {args.num_cases})")
        return
    
    # Process each test case and write to file
    logger.info(f"Processing {len(selected_cases)} test cases")
    with open(output_file, 'w', encoding='utf-8') as f:
        for i, case in enumerate(selected_cases):
            case_start_time = time.time()
            
            # Input validation: check required fields
            try:
                case_name = case.get("name", f"Case {i+1}")
                if not isinstance(case.get("alert"), dict):
                    logger.error(f"Test case {i+1}: 'alert' is missing or not a dict. Skipping.")
                    continue
                
                alert_dict = case["alert"]
                required_fields = ["summary", "risk_index", "raw_log"]
                missing_fields = [field for field in required_fields if field not in alert_dict]
                if missing_fields:
                    logger.error(f"Test case {i+1} ({case_name}): Missing required fields: {missing_fields}. Skipping.")
                    continue
                
                logger.info(f"Processing test case {i+1}/{len(selected_cases)}: {case_name}")
            except (KeyError, TypeError) as e:
                logger.error(f"Test case {i+1}: Invalid structure: {e}. Skipping.")
                continue
            
            f.write(f"\n## Test Case: {case_name}\n\n")
            
            # Format alert text
            logger.info("Formatting alert input")
            try:
                alert_text = analyzer.format_alert_input(
                    alert_dict["summary"],
                    alert_dict["risk_index"],
                    alert_dict["raw_log"]
                )
            except Exception as e:
                logger.error(f"Test case {i+1}: Failed to format alert input: {e}. Skipping.")
                continue
            logger.info(f"Alert text formatted, length: {len(alert_text)} characters")
            
            # Extract alert time from raw_log if available
            alert_time = alert_dict["raw_log"].get("timestamp") if isinstance(alert_dict.get("raw_log"), dict) else None
            
            # Analyze TTPs
            logger.info("Starting TTP analysis for this case")
            scored_ttps = analyzer.analyze_ttp(alert_text, alert_time=alert_time)
            logger.info(f"TTP analysis completed, found {len(scored_ttps)} TTPs")
            
            case_end_time = time.time()
            logger.info(f"Test case {i+1} completed in {case_end_time - case_start_time:.2f} seconds")
            
            # Write results to file
            f.write("### Alert Text\n\n")
            f.write(alert_text + "\n\n")
            
            # Write IOC Extraction if available
            if hasattr(analyzer, 'last_llm_response') and analyzer.last_llm_response:
                response = analyzer.last_llm_response
                if "ioc_extraction" in response:
                    iocs = response["ioc_extraction"]
                    f.write("### Indicators of Compromise (IOCs)\n\n")
                    if iocs.get('ip_addresses'):
                        f.write(f"**IP Addresses:** {', '.join(iocs['ip_addresses'])}\n")
                    if iocs.get('domains'):
                        f.write(f"**Domains:** {', '.join(iocs['domains'])}\n")
                    if iocs.get('user_accounts'):
                        f.write(f"**User Accounts:** {', '.join(iocs['user_accounts'])}\n")
                    if iocs.get('hostnames'):
                        f.write(f"**Hostnames:** {', '.join(iocs['hostnames'])}\n")
                    if iocs.get('process_names'):
                        f.write(f"**Processes:** {', '.join(iocs['process_names'])}\n")
                    if iocs.get('file_paths'):
                        f.write(f"**File Paths:** {', '.join(iocs['file_paths'])}\n")
                    if iocs.get('file_hashes'):
                        f.write(f"**File Hashes:** {', '.join(iocs['file_hashes'])}\n")
                    if iocs.get('event_ids'):
                        f.write(f"**Event IDs:** {', '.join(iocs['event_ids'])}\n")
                    if iocs.get('urls'):
                        f.write(f"**URLs:** {', '.join(iocs['urls'])}\n")
                    f.write("\n")
                
                # Write Correlation Keys
                if "correlation_keys" in response:
                    corr_keys = response["correlation_keys"]
                    f.write("### Correlation Keys\n\n")
                    if corr_keys.get('primary_indicators'):
                        f.write(f"**Primary Indicators:** {', '.join(corr_keys['primary_indicators'])}\n")
                    if corr_keys.get('search_terms'):
                        f.write(f"**Search Terms:** {', '.join(corr_keys['search_terms'])}\n")
                    if corr_keys.get('time_window_suggested'):
                        f.write(f"**Suggested Time Window:** {corr_keys['time_window_suggested']}\n")
                    f.write("\n")
                
                # Write Evidence vs Inference
                if "evidence_vs_inference" in response:
                    evi = response["evidence_vs_inference"]
                    f.write("### Evidence vs Inference\n\n")
                    if evi.get('evidence'):
                        f.write("**Evidence (Facts):**\n")
                        for item in evi['evidence']:
                            f.write(f"- {item}\n")
                        f.write("\n")
                    if evi.get('inferences'):
                        f.write("**Inferences (Hypotheses):**\n")
                        for item in evi['inferences']:
                            f.write(f"- {item}\n")
                        f.write("\n")
                
                # Write Containment Playbook
                if "containment_playbook" in response:
                    playbook = response["containment_playbook"]
                    f.write("### Containment Playbook\n\n")
                    if playbook.get('immediate'):
                        f.write("**Immediate Actions (within hours):**\n")
                        for action in playbook['immediate']:
                            f.write(f"- {action}\n")
                        f.write("\n")
                    if playbook.get('short_term'):
                        f.write("**Short-term Actions (24-48h):**\n")
                        for action in playbook['short_term']:
                            f.write(f"- {action}\n")
                        f.write("\n")
                    if playbook.get('references'):
                        f.write("**References (ATT&CK Mitigations):**\n")
                        for ref in playbook['references']:
                            f.write(f"- {ref}\n")
                        f.write("\n")
            
            # Group TTPs by confidence and display
            f.write("### Scored TTPs\n\n")
            if scored_ttps:
                for ttp in scored_ttps:
                    ttp["score"] = extract_score(ttp)
                
                # Sort by score descending
                sorted_ttps = sorted(scored_ttps, key=lambda x: x["score"], reverse=True)
                
                # Group by confidence level
                high_conf = [t for t in sorted_ttps if t["score"] >= 0.80]
                med_conf = [t for t in sorted_ttps if 0.50 <= t["score"] < 0.80]
                low_conf = [t for t in sorted_ttps if t["score"] < 0.50]
                
                if high_conf:
                    f.write("#### High Confidence (≥0.80)\n\n")
                    for ttp in high_conf:
                        f.write(f"**{ttp['ttp_id']}** - {ttp.get('ttp_name', 'N/A')}: **{ttp['score']:.3f}**\n")
                        f.write(f"  - **Explanation:** {ttp['explanation']}\n")
                        if ttp.get('tactic_span_note'):
                            f.write(f"  - **Tactic Span:** {ttp['tactic_span_note']}\n")
                        if ttp.get('evidence_fields'):
                            f.write(f"  - **Evidence Fields:** {', '.join(ttp['evidence_fields'])}\n")
                        if ttp.get('immediate_actions'):
                            f.write(f"  - **Immediate Actions:** {ttp['immediate_actions']}\n")
                        if ttp.get('remediation_recommendations'):
                            f.write(f"  - **Remediation:** {ttp['remediation_recommendations']}\n")
                        if ttp.get('mitre_url'):
                            f.write(f"  - **MITRE URL:** {ttp['mitre_url']}\n")
                        f.write("\n")
                
                if med_conf:
                    f.write("#### Medium Confidence (0.50-0.79)\n\n")
                    for ttp in med_conf:
                        f.write(f"**{ttp['ttp_id']}** - {ttp.get('ttp_name', 'N/A')}: **{ttp['score']:.3f}**\n")
                        f.write(f"  - **Explanation:** {ttp['explanation']}\n")
                        if ttp.get('tactic_span_note'):
                            f.write(f"  - **Tactic Span:** {ttp['tactic_span_note']}\n")
                        if ttp.get('evidence_fields'):
                            f.write(f"  - **Evidence Fields:** {', '.join(ttp['evidence_fields'])}\n")
                        if ttp.get('immediate_actions'):
                            f.write(f"  - **Immediate Actions:** {ttp['immediate_actions']}\n")
                        if ttp.get('remediation_recommendations'):
                            f.write(f"  - **Remediation:** {ttp['remediation_recommendations']}\n")
                        if ttp.get('mitre_url'):
                            f.write(f"  - **MITRE URL:** {ttp['mitre_url']}\n")
                        f.write("\n")
                
                if low_conf:
                    f.write("#### Low Confidence (<0.50)\n\n")
                    for ttp in low_conf:
                        f.write(f"**{ttp['ttp_id']}** - {ttp.get('ttp_name', 'N/A')}: **{ttp['score']:.3f}**\n")
                        f.write(f"  - **Explanation:** {ttp['explanation']}\n")
                        if ttp.get('tactic_span_note'):
                            f.write(f"  - **Tactic Span:** {ttp['tactic_span_note']}\n")
                        if ttp.get('evidence_fields'):
                            f.write(f"  - **Evidence Fields:** {', '.join(ttp['evidence_fields'])}\n")
                        if ttp.get('immediate_actions'):
                            f.write(f"  - **Immediate Actions:** {ttp['immediate_actions']}\n")
                        if ttp.get('remediation_recommendations'):
                            f.write(f"  - **Remediation:** {ttp['remediation_recommendations']}\n")
                        if ttp.get('mitre_url'):
                            f.write(f"  - **MITRE URL:** {ttp['mitre_url']}\n")
                        f.write("\n")
            else:
                f.write("No TTPs scored\n\n")

            # Write additional analysis sections if present in the new structured response
            if hasattr(analyzer, 'last_llm_response') and analyzer.last_llm_response:
                response = analyzer.last_llm_response
                
                # Write Attack Chain information
                if "attack_chain" in response:
                    f.write("### Attack Chain Analysis\n\n")
                    attack_chain = response["attack_chain"]
                    
                    if "likely_previous_steps" in attack_chain and attack_chain["likely_previous_steps"]:
                        step = attack_chain["likely_previous_steps"][0]  # Only first step
                        if isinstance(step, dict):
                            f.write(f"**Likely Previous Step:** {step.get('tactic_name', 'N/A')} ({step.get('tactic_id', 'N/A')})\n\n")
                            if step.get('mitre_url'):
                                f.write(f"MITRE URL: {step['mitre_url']}\n\n")
                            
                            # Streamlined 3-line format
                            if step.get('why_this_step'):
                                f.write(f"**Why:** {step['why_this_step']}\n\n")
                            elif any(step.get(k) for k in ['temporal_context', 'prerequisites', 'attack_patterns']):
                                # Fallback: construct from old format if new format not available
                                why_parts = []
                                if step.get('temporal_context'):
                                    why_parts.append(step['temporal_context'])
                                elif step.get('prerequisites'):
                                    why_parts.append(step['prerequisites'])
                                if why_parts:
                                    f.write(f"**Why:** {why_parts[0]}\n\n")
                            
                            if step.get('what_to_check'):
                                f.write(f"**Check:** {step['what_to_check']}\n\n")
                            elif step.get('analyst_actions'):
                                f.write(f"**Check:** {step['analyst_actions']}\n\n")
                            
                            if step.get('uncertainty_alternatives'):
                                f.write(f"**Uncertainty:** {step['uncertainty_alternatives']}\n\n")
                            elif step.get('uncertainty_factors'):
                                f.write(f"**Uncertainty:** {step['uncertainty_factors']}\n\n")
                            
                            # Investigation tree (questions only)
                            if step.get('investigation_tree'):
                                f.write("**Investigation Questions:**\n\n")
                                inv_tree = step['investigation_tree']
                                if isinstance(inv_tree, dict):
                                    for question_id, tree in inv_tree.items():
                                        if isinstance(tree, dict):
                                            f.write(f"- {question_id}: {tree.get('question', 'N/A')}\n")
                                        else:
                                            f.write(f"- {question_id}: {tree}\n")
                                f.write("\n")
                    
                    if "likely_next_steps" in attack_chain and attack_chain["likely_next_steps"]:
                        step = attack_chain["likely_next_steps"][0]  # Only first step
                        if isinstance(step, dict):
                            f.write(f"**Likely Next Step:** {step.get('tactic_name', 'N/A')} ({step.get('tactic_id', 'N/A')})\n\n")
                            if step.get('mitre_url'):
                                f.write(f"MITRE URL: {step['mitre_url']}\n\n")
                            
                            # Streamlined 3-line format
                            if step.get('why_this_step'):
                                f.write(f"**Why:** {step['why_this_step']}\n\n")
                            elif any(step.get(k) for k in ['temporal_context', 'prerequisites', 'attack_patterns']):
                                # Fallback: construct from old format if new format not available
                                why_parts = []
                                if step.get('temporal_context'):
                                    why_parts.append(step['temporal_context'])
                                elif step.get('prerequisites'):
                                    why_parts.append(step['prerequisites'])
                                if why_parts:
                                    f.write(f"**Why:** {why_parts[0]}\n\n")
                            
                            if step.get('what_to_check'):
                                f.write(f"**Check:** {step['what_to_check']}\n\n")
                            elif step.get('analyst_actions'):
                                f.write(f"**Check:** {step['analyst_actions']}\n\n")
                            
                            if step.get('uncertainty_alternatives'):
                                f.write(f"**Uncertainty:** {step['uncertainty_alternatives']}\n\n")
                            elif step.get('uncertainty_factors'):
                                f.write(f"**Uncertainty:** {step['uncertainty_factors']}\n\n")
                            
                            # Investigation tree (questions only)
                            if step.get('investigation_tree'):
                                f.write("**Investigation Questions:**\n\n")
                                inv_tree = step['investigation_tree']
                                if isinstance(inv_tree, dict):
                                    for question_id, tree in inv_tree.items():
                                        if isinstance(tree, dict):
                                            f.write(f"- {question_id}: {tree.get('question', 'N/A')}\n")
                                        else:
                                            f.write(f"- {question_id}: {tree}\n")
                                f.write("\n")
                    
                    if "kill_chain_phase" in attack_chain:
                        f.write(f"**Kill Chain Phase:** {attack_chain['kill_chain_phase']}\n\n")
                    if "tactic_span_note" in attack_chain:
                        f.write(f"**Tactic Span Note:** {attack_chain['tactic_span_note']}\n\n")
                
                # Write Splunk enrichment queries
                splunk_key = None
                for k in ['splunk_enrichment', 'splunk_queries']:
                    if k in response:
                        splunk_key = k
                        break
                if splunk_key:
                    f.write("### Splunk Enrichment Queries\n\n")
                    for q in response[splunk_key]:
                        f.write(f"**Phase:** {q.get('phase', 'N/A')}\n")
                        f.write(f"**Supports Tactic:** {q.get('supports_tactic', 'N/A')}\n")
                        f.write(f"**Purpose:** {q.get('purpose', 'N/A')}\n")
                        f.write(f"**Query:** {q.get('query', 'N/A')}\n")
                        f.write(f"  - **Confidence Boost Rule:** {q.get('confidence_boost_rule', 'N/A')}\n")
                        f.write(f"  - **Confidence Reduce Rule:** {q.get('confidence_reduce_rule', 'N/A')}\n\n")
                
                # Write Tactic Framing (new section)
                if "tactic_framing" in response:
                    tf = response["tactic_framing"]
                    f.write("### Tactic Framing\n\n")
                    if tf.get('primary_tactic'):
                        pt = tf['primary_tactic']
                        f.write(f"**Primary Tactic:** {pt.get('tactic_name', 'N/A')} ({pt.get('tactic_id', 'N/A')})\n")
                        if pt.get('justification'):
                            f.write(f"  - **Justification:** {pt['justification']}\n")
                        f.write("\n")
                    if tf.get('secondary_tactics'):
                        f.write("**Secondary Tactics:**\n")
                        for st in tf['secondary_tactics']:
                            f.write(f"- {st.get('tactic_name', 'N/A')} ({st.get('tactic_id', 'N/A')}): {st.get('why_plausible', 'N/A')}\n")
                        f.write("\n")
                    if tf.get('disambiguation_checklist'):
                        f.write("**Disambiguation Checklist:**\n")
                        for item in tf['disambiguation_checklist']:
                            f.write(f"- {item}\n")
                        f.write("\n")
                
                # Write Benign Explanations (new section)
                if "benign_explanations" in response:
                    be = response["benign_explanations"]
                    f.write("### Benign Explanations (Legitimate Activity Hypotheses)\n\n")
                    for i, hyp in enumerate(be, 1):
                        f.write(f"**Hypothesis {i}:** {hyp.get('hypothesis', 'N/A')}\n")
                        if hyp.get('expect_if_true'):
                            f.write(f"  - **Expect if true:** {', '.join(hyp['expect_if_true'])}\n")
                        if hyp.get('argue_against'):
                            f.write(f"  - **Argues against:** {hyp['argue_against']}\n")
                        if hyp.get('best_validation'):
                            f.write(f"  - **Best validation:** {hyp['best_validation']}\n")
                        f.write("\n")
                
                # Write Competing Hypotheses (new section)
                if "competing_hypotheses" in response:
                    ch = response["competing_hypotheses"]
                    f.write("### Competing Hypotheses & Pivots\n\n")
                    for i, hyp in enumerate(ch, 1):
                        hyp_type = hyp.get('hypothesis_type', 'unknown').capitalize()
                        f.write(f"**Hypothesis {i} ({hyp_type}):** {hyp.get('hypothesis', 'N/A')}\n")
                        if hyp.get('evidence_support'):
                            f.write(f"  - **Evidence support:** {', '.join(hyp['evidence_support'])}\n")
                        if hyp.get('evidence_gaps'):
                            f.write(f"  - **Evidence gaps:** {', '.join(hyp['evidence_gaps'])}\n")
                        if hyp.get('best_pivots'):
                            f.write("  - **Best pivots:**\n")
                            for pivot in hyp['best_pivots']:
                                if isinstance(pivot, dict):
                                    f.write(f"    - {pivot.get('log_source', 'N/A')}: {pivot.get('key_fields', 'N/A')}\n")
                                else:
                                    f.write(f"    - {pivot}\n")
                        f.write("\n")
                
                # Write Context Enrichment (new section)
                if "context_enrichment" in response:
                    ce = response["context_enrichment"]
                    f.write("### Context Enrichment & Baseline\n\n")
                    if ce.get('enrichment_steps'):
                        f.write("**Enrichment Steps:**\n")
                        for step in ce['enrichment_steps']:
                            if isinstance(step, dict):
                                f.write(f"- {step.get('field', 'N/A')} ({step.get('enrichment_type', 'N/A')}): {step.get('result_or_status', 'N/A')}\n")
                            else:
                                f.write(f"- {step}\n")
                        f.write("\n")
                    if ce.get('baseline_queries'):
                        f.write("**Baseline Queries:**\n")
                        for bq in ce['baseline_queries']:
                            if isinstance(bq, dict):
                                f.write(f"- **Purpose:** {bq.get('purpose', 'N/A')}\n")
                                f.write(f"  - **Query:** {bq.get('query', 'N/A')}\n")
                            else:
                                f.write(f"- {bq}\n")
                        f.write("\n")
                    if ce.get('limitations'):
                        f.write(f"**Limitations:** {ce['limitations']}\n\n")


    total_time = time.time() - start_time
    logger.info(f"All test cases completed. Total execution time: {total_time:.2f} seconds")
    logger.info(f"Results saved to: {output_file}")

def extract_score(ttp):
    for key in ("score", "confidence_score", "confidence"):
        if key in ttp:
            return ttp[key]
    logger.warning(f"No score/confidence field found in TTP: {ttp}")
    return 0

if __name__ == "__main__":
    main()
