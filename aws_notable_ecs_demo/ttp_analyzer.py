#!/usr/bin/env python3
"""
TTP Analyzer module for AWS Lambda + Bedrock Nova Pro.
Ports the core logic from notable_analysis.py without modifying the original.
"""

import json
import time
import os
import logging
from typing import List, Dict, Any, Set, Optional
from pathlib import Path
import boto3
from botocore.exceptions import ClientError

# Configure logging
logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

# =============================================================================
# TOOL SCHEMA - Enforces structured JSON output via Bedrock tool calling
# =============================================================================

ANALYZE_NOTABLE_TOOL = {
    "toolSpec": {
        "name": "analyze_notable",
        "description": "Analyze a security alert and return structured TTP analysis",
        "inputSchema": {
            "json": {
                "type": "object",
                "properties": {
                    "ttp_analysis": {"type": "array", "items": {"type": "object"}},
                    "attack_chain": {"type": "object"},
                    "ioc_extraction": {"type": "object"},
                    "correlation_keys": {"type": "object"},
                    "evidence_vs_inference": {"type": "object"},
                    "containment_playbook": {"type": "object"},
                    "splunk_enrichment": {"type": "array", "items": {"type": "object"}},
                    "tactic_framing": {"type": "object"},
                    "benign_explanations": {"type": "array", "items": {"type": "object"}},
                    "competing_hypotheses": {"type": "array", "items": {"type": "object"}},
                    "context_enrichment": {"type": "object"}
                },
                "required": ["ttp_analysis", "attack_chain", "ioc_extraction",
                             "correlation_keys", "evidence_vs_inference",
                             "containment_playbook", "splunk_enrichment",
                             "tactic_framing", "benign_explanations",
                             "competing_hypotheses", "context_enrichment"]
            }
        }
    }
}

# =============================================================================
# PROMPT SECTIONS - Modular prompt components for maintainability
# =============================================================================

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
Use the analyze_notable tool to return your analysis. The tool expects the following schema:

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
- All fields and keys must match the schema exactly.
"""


class TTPValidator:
    """Validator for MITRE ATT&CK TTP IDs using local data.
    
    This class loads and validates MITRE ATT&CK technique IDs from a local
    JSON file containing pre-extracted IDs from the MITRE ATT&CK framework.
    """
    
    def __init__(self, ids_file_path: Path):
        """Initialize with cached valid TTPs from local file.
        
        Args:
            ids_file_path: Path to the JSON file containing valid TTP IDs.
        """
        self._valid_subtechniques: Set[str] = set()
        self._valid_parent_techniques: Set[str] = set()
        self._load_valid_ttps(ids_file_path)
    
    def _load_valid_ttps(self, ids_file_path: Path):
        """Load valid technique IDs from pre-extracted MITRE ATT&CK IDs file.
        
        Args:
            ids_file_path: Path to the JSON file containing valid TTP IDs.
            
        Raises:
            ValueError: If no TTPs are loaded from the file.
            IOError: If the file cannot be read.
            json.JSONDecodeError: If the file contains invalid JSON.
        """
        try:
            with open(ids_file_path, 'r') as f:
                ttp_ids = json.load(f)
            
            # Separate parent techniques from sub-techniques
            for ttp_id in ttp_ids:
                if "." in ttp_id:
                    self._valid_subtechniques.add(ttp_id)
                else:
                    self._valid_parent_techniques.add(ttp_id)
            
            total_ttps = len(self._valid_subtechniques) + len(self._valid_parent_techniques)
            logger.info(f"Loaded {len(self._valid_subtechniques)} valid sub-techniques and {len(self._valid_parent_techniques)} parent techniques (total: {total_ttps})")
            
            if total_ttps == 0:
                raise ValueError("No TTPs loaded from pre-extracted IDs file.")
                
        except (IOError, json.JSONDecodeError) as e:
            logger.error(f"Error reading pre-extracted IDs file {ids_file_path}: {e}")
            raise
    
    def is_valid_ttp(self, ttp_id: str) -> bool:
        """Check if TTP ID is valid.
        
        Args:
            ttp_id: The MITRE ATT&CK technique ID to validate.
            
        Returns:
            True if the TTP ID is valid, False otherwise.
        """
        return ttp_id in self._valid_subtechniques or ttp_id in self._valid_parent_techniques
    
    def get_valid_ttps_for_prompt(self) -> str:
        """Get formatted list of valid TTPs for inclusion in prompt.
        
        Returns:
            Comma-separated string of all valid TTP IDs.
        """
        all_ttps = sorted(list(self._valid_subtechniques)) + sorted(list(self._valid_parent_techniques))
        return ", ".join(all_ttps)
    
    def filter_valid_ttps(self, scored_ttps: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """Filter out invalid TTPs and return only valid ones.
        
        Args:
            scored_ttps: List of TTP dictionaries with 'ttp_id' keys.
            
        Returns:
            List of valid TTPs with invalid ones removed.
        """
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
        """Get total count of loaded TTPs.
        
        Returns:
            Total number of valid TTPs (sub-techniques + parent techniques).
        """
        return len(self._valid_subtechniques) + len(self._valid_parent_techniques)


class BedrockAnalyzer:
    """LLM-based TTP analyzer using Bedrock Nova Pro.
    
    This class coordinates TTP analysis by formatting alerts, calling the Bedrock
    LLM API, and validating returned TTPs against the MITRE ATT&CK framework.
    """
    
    def __init__(self, model_id: str = "amazon.nova-pro-v1:0"):
        """Initialize the analyzer with Bedrock client.
        
        Args:
            model_id: The Bedrock model ID to use (default: amazon.nova-pro-v1:0).
        """
        self.bedrock_client = boto3.client('bedrock-runtime')
        self.model_id = model_id
        
        # Initialize validator
        ids_file = Path(__file__).parent / "enterprise_attack_v17.1_ids.json"
        self.validator = TTPValidator(ids_file)
        
        # Store last response for markdown generation
        self.last_llm_response = None
        # Store raw content for debugging
        self.last_raw_content = None

    def _build_prompt(self, alert_text: str, alert_time: Optional[str], valid_ttps_list: str) -> str:
        """Assemble the full prompt from modular sections.
        
        Args:
            alert_text: Formatted alert text to analyze.
            alert_time: Optional ISO timestamp of the alert.
            valid_ttps_list: Comma-separated list of valid TTP IDs.
            
        Returns:
            Complete prompt string for LLM.
        """
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
        """Format alert data into a structured text block.
        
        Args:
            summary: Alert summary text.
            risk_index: Dictionary containing risk score, source product, and threat category.
            raw_log: Dictionary of raw log fields.
            
        Returns:
            Formatted string with [SUMMARY], [RISK INDEX], and [RAW EVENT] sections.
        """
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
    
    def analyze_ttp(self, alert_text: str, alert_time: Optional[str] = None) -> List[Dict[str, Any]]:
        """Use LLM to analyze the alert and identify relevant MITRE ATT&CK TTPs.
        
        This method constructs a detailed prompt with analyst doctrine, sends it to
        Bedrock Nova Pro using forced tool calling, parses the structured response,
        and filters out invalid TTPs.
        
        Args:
            alert_text: Formatted alert text to analyze.
            alert_time: Optional ISO timestamp of the alert for enrichment queries.
            
        Returns:
            List of valid TTP dictionaries with scores, explanations, and metadata.
            Returns empty list if analysis fails or no valid TTPs are found.
        """
        logger.info("Starting TTP analysis")
        start_time = time.time()
        
        # Get valid TTPs for the prompt
        valid_ttps_list = self.validator.get_valid_ttps_for_prompt()
        total_ttps = self.validator.get_ttp_count()
        logger.info(f"Loaded {total_ttps} valid TTPs for prompt")
        
        # Build prompt using modular sections
        prompt = self._build_prompt(alert_text, alert_time, valid_ttps_list)
        
        # Input validation
        if not alert_text or not alert_text.strip():
            logger.error("Alert text is empty or whitespace only")
            return []
        
        try:
            logger.info("Making Bedrock API call...")
            api_start_time = time.time()
            
            # Call Bedrock with retry logic
            max_retries = 3
            retry_delay = 5
            
            for attempt in range(max_retries):
                try:
                    logger.info(f"API call attempt {attempt + 1}/{max_retries}")
                    
                    response = self.bedrock_client.converse(
                        modelId=self.model_id,
                        messages=[
                            {
                                "role": "user",
                                "content": [{"text": prompt}]
                            }
                        ],
                        toolConfig={
                            "tools": [ANALYZE_NOTABLE_TOOL],
                            "toolChoice": {"tool": {"name": "analyze_notable"}}
                        },
                        inferenceConfig={
                            # maxTokens is the model's maximum number of tokens to generate (output budget),
                            # not the input prompt size. Cap hard at 8192 to prevent runaway cost / invalid values.
                            "maxTokens": max(256, min(int(os.environ.get("MAX_OUTPUT_TOKENS", "8192")), 8192)),
                            "temperature": 0.7,
                            "topP": 0.95
                        }
                    )
                    
                    api_end_time = time.time()
                    logger.info(f"API call completed in {api_end_time - api_start_time:.2f} seconds")
                    break
                    
                except ClientError as api_error:
                    logger.warning(f"API call attempt {attempt + 1} failed: {str(api_error)}")
                    if attempt < max_retries - 1:
                        logger.info(f"Retrying in {retry_delay} seconds...")
                        time.sleep(retry_delay)
                        retry_delay *= 2
                    else:
                        logger.error(f"All {max_retries} API call attempts failed")
                        raise
            
            # Parse the response - prefer toolUse block
            logger.info("Parsing LLM response")
            content_blocks = response['output']['message']['content']
            
            result = None
            
            # Try toolUse block first (preferred path with forced tool choice)
            for block in content_blocks:
                if 'toolUse' in block:
                    tool_input = block['toolUse'].get('input', {})
                    if isinstance(tool_input, dict):
                        logger.info("Parsed response from toolUse block")
                        result = tool_input
                        break
            
            # Fallback: if no toolUse, check for text block (shouldn't happen with forced tool choice)
            if result is None:
                for block in content_blocks:
                    if 'text' in block:
                        raw_text = block['text']
                        logger.warning(f"No toolUse block found, falling back to text parsing")
                        self.last_raw_content = raw_text
                        self.last_llm_response = {"raw_error": raw_text}
                        return []
                
                # No toolUse or text block found
                logger.error("No toolUse or text block found in response")
                self.last_llm_response = {"raw_error": str(content_blocks)}
                return []
            
            logger.info(f"Parsed result type: {type(result)}")
            
            # Store the last LLM response for markdown generation
            self.last_llm_response = result
            
            # Extract TTPs from the structured response
            scored_ttps = []
            
            if not isinstance(result, dict):
                logger.error(f"Expected dict response, got {type(result)}")
                return []
            
            # Handle the structured response with ttp_analysis
            if "ttp_analysis" in result:
                logger.info("Processing structured response with ttp_analysis")
                if not isinstance(result["ttp_analysis"], list):
                    logger.error(f"ttp_analysis must be a list, got {type(result['ttp_analysis'])}")
                    return []
                
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
            
            # Filter out invalid TTPs
            logger.info("Filtering invalid TTPs")
            valid_ttps = self.validator.filter_valid_ttps(scored_ttps)
            logger.info(f"Final valid TTPs: {len(valid_ttps)}")
            
            total_time = time.time() - start_time
            logger.info(f"Total TTP analysis completed in {total_time:.2f} seconds")
            
            return valid_ttps
            
        except Exception as e:
            logger.error(f"Unexpected error calling LLM: {str(e)}")
            logger.error(f"Exception type: {type(e).__name__}")
            return []


def extract_score(ttp: Dict[str, Any]) -> float:
    """Extract score from TTP dict.
    
    Args:
        ttp: TTP dictionary containing score/confidence fields.
        
    Returns:
        Float score value, or 0.0 if no score field is found.
    """
    for key in ("score", "confidence_score", "confidence"):
        if key in ttp:
            return ttp[key]
    return 0.0
