#!/usr/bin/env python3
"""
TTP Analyzer module for AWS Lambda + Bedrock Nova Pro.
Ports the core logic from notable_analysis.py without modifying the original.
"""

import json
import time
import logging
from typing import List, Dict, Any, Set, Optional
from pathlib import Path
import boto3
from botocore.exceptions import ClientError

# Configure logging
logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

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
        Bedrock Nova Pro, parses the structured JSON response, and filters out invalid TTPs.
        
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
        
        alert_time_str = f"\n        **ALERT_TIME:** {alert_time}\n        " if alert_time else ""
        prompt = f"""You are a cybersecurity expert mapping MITRE ATT&CK techniques from a single alert.

{alert_time_str}
        ---

        ANALYST DOCTRINE (apply to every case)
        - MITRE ATT&CK is many-to-many: a single technique may support several tactics. Always state (a) the tactic you're assigning in this alert AND (b) other plausible tactics this technique commonly serves (tactic-span note). Base on MITRE ATT&CK v17.
        - FACT vs. INFERENCE: List literal, direct alert evidence first (field=value from the alert), then inferences and assumptions separately (with uncertainty).
        - Containment Focus: Provide a minimal 3-step containment playbook (containment, eradication, recovery) aligned with NIST 800-61 and mapped to relevant ATT&CK mitigations.
        - Hunt by Telemetry Family: When proposing enrichment, include at least one check from each applicable telemetry family:
            * Authentication (failures/successes, privilege use)
            * Directory/Identity changes (object modifications)
            * Lateral movement (remote services, shares, tasks)
            * Persistence/Privilege (new users/groups, scheduled tasks)
            * Kerberos/Ticketing (KDC/pre-auth anomalies)
        - IOC labeling hygiene: Do not list core OS/generic binaries as IOCs without explicit malicious context. Instead, list as "system_components_observed" if present in the alert.

        EVIDENCE-GATE: Only include a technique (TTP) if: 
        A. There is a direct data-component match in the alert (quote it).
        B. Your explanation cites the matching field/value.
        C. No inference or external context is necessary.
        D. If evidence correctness depends on context not in the log (e.g., domain internal/external, IP a DC), drop to the parent technique or reduce confidence by ≥0.20 and state the missing context in your explanation.

        Scoring Rubric: 
        - high ≥ 0.80 = direct, unambiguous
        - med 0.50-0.79 = strongly suggestive; one element missing
        - low < 0.30 = plausible but needs corroboration

        MITIGATIONS & DETECTIONS:
        - Prefer ATT&CK mitigations that materially reduce technique feasibility (e.g., M1032 MFA, M1026 PAM, M1030 segmentation).
        - If uncertain between sub-technique and parent, select the parent and state why; use the sub-technique only with explicit evidence. 

        PROCEDURE:
        1. **Think silently**: classify activity -> tactics -> candidate techniques.
        2. Self-check against the tactic checklist.
        3. Decode/deobfuscate common encodings (Base64, hex, URL-encoded, gzip) if found.
        4. Use sub-techniques when specific variant is confirmed (e.g., T1059.001 for PowerShell).
        5. Default to parent techniques when sub-technique cannot be precisely assigned.
        6. Use only the ATT&CK techniques from this allowed list:
        {valid_ttps_list}

        SECURITY ALERT INPUT:
        {alert_text}

        ---

        OUTPUT FORMAT: Return ONLY a single valid JSON object. Do not include markdown code fences or any text outside the JSON. Start your response with an opening brace and end with a closing brace . The JSON object must have these top-level keys:
        - `ttp_analysis`
        - `attack_chain`
        - `ioc_extraction`
        - `correlation_keys`
        - `evidence_vs_inference`
        - `containment_playbook`
        - `splunk_enrichment`

        SCHEMA:
        - ttp_analysis: list of objects, each with:
            - ttp_id: string (MITRE ATT&CK ID, e.g. "T1059.001")
            - ttp_name: string (official technique name)
            - confidence_score: float (0.0–1.0)
            - explanation: string (A brief explanation of why this TTP was inferred, using quoted evidence from the alert. End with "Uncertainty: [brief statement]" acknowledging what is inferred vs. direct evidence, and any missing context like geo/VPN metadata, edge telemetry, etc.)
            - tactic_span_note: string (One sentence naming other ATT&CK tactics this technique commonly supports and why they may apply here, e.g. "This technique also commonly supports Persistence (TA0003) and Privilege Escalation (TA0004) when used to maintain access or elevate privileges")
            - evidence_fields: list of strings (Specific alert field=value pairs that directly support this TTP, e.g. ["event_id=4624", "user=DOMAIN\\\\admin", "ip_address=203.0.113.45"])
            - immediate_actions: string (Urgent remediation steps if this TTP is confirmed, e.g. "Disable affected user account, reset credentials, isolate affected system")
            - remediation_recommendations: string (Specific defensive measures to prevent or detect this technique, citing MITRE mitigations by ID where relevant, e.g. M1032, M1026, M1030)
            - mitre_url: mitre version permalink url for the technique (e.g."https://attack.mitre.org/versions/v17/techniques/T1059/001/")

        - attack_chain: object with:
            - likely_previous_steps: list of EXACTLY 1 object (ALWAYS include exactly 1 previous step as a hypothesis), with:
                - tactic_id: string (MITRE ATT&CK Tactic ID, e.g. "TA0006")
                - tactic_name: string (official tactic name)
                - mitre_url: string (tactic mitre url - MITRE version permalink URL, e.g. "https://attack.mitre.org/versions/v17/tactics/TA0006/")
                - why_this_step: string (One concise sentence explaining the hypothesis - cite alert field=value pairs that suggest this step)
                - what_to_check: string (One concise sentence listing specific artifacts, event IDs, or data sources to investigate next)
                - uncertainty_alternatives: string (One concise sentence describing what is uncertain, missing context, or alternative explanations)
                - investigation_tree: object with exactly 3 questions (Q1, Q2, Q3), each containing:
                    - question: string (the investigation question)
            - likely_next_steps: list of EXACTLY 1 object (ALWAYS include exactly 1 next step as a hypothesis), with:
                - tactic_id: string (MITRE ATT&CK Tactic ID, e.g. "TA0008")
                - tactic_name: string (official tactic name)
                - mitre_url: string (tactic mitre url - MITRE version permalink URL, e.g. "https://attack.mitre.org/versions/v17/tactics/TA0008/")
                - why_this_step: string (One concise sentence explaining the hypothesis - cite alert field=value pairs that suggest this step)
                - what_to_check: string (One concise sentence listing specific artifacts, event IDs, or data sources to investigate next)
                - uncertainty_alternatives: string (One concise sentence describing what is uncertain, missing context, or alternative explanations)
                - investigation_tree: object with exactly 3 questions (Q1, Q2, Q3), each containing:
                    - question: string (the investigation question)
            - kill_chain_phase: string (must match MITRE phase name; The most appropriate cyber kill chain phase; based on the identified technique(s) and their ATT&CK tactic assignments.)
            - tactic_span_note: string (One-line note naming other ATT&CK tactics that the top technique commonly supports, with rationale, and why you selected the current kill_chain_phase for this alert)

        - ioc_extraction: object with:
            - ip_addresses: list of strings (All IP addresses found in the alert, e.g. ["203.0.113.45"])
            - domains: list of strings (All domain names found, e.g. ["malicious.example.com"])
            - user_accounts: list of strings (All user accounts found, e.g. ["DOMAIN\\\\admin"])
            - hostnames: list of strings (All hostnames/computers found, e.g. ["DC-01", "WORKSTATION-01"])
            - file_paths: list of strings (All file paths found, e.g. ["C:\\\\Windows\\\\System32\\\\lsass.exe"])
            - process_names: list of strings (All process names found, e.g. ["powershell.exe", "cmd.exe"])
            - file_hashes: list of strings (MD5, SHA1, or SHA256 hashes if present, e.g. ["a1b2c3d4..."])
            - event_ids: list of strings (Windows Event IDs if present, e.g. ["4624", "4625"])
            - urls: list of strings (URLs found in the alert)

        - correlation_keys: object with:
            - primary_indicators: list of strings (Most important fields for SIEM correlation, e.g. ["ip_address=203.0.113.45", "user=DOMAIN\\\\admin"])
            - search_terms: list of strings (Key terms for searching across logs, e.g. ["203.0.113.45", "DOMAIN\\\\admin", "DC-01"])
            - time_window_suggested: string (Suggested time window for correlation searches, e.g. "-24h to +24h")

        - evidence_vs_inference: object with:
            - evidence: list of strings (Literal field=value facts copied directly from the alert, e.g. ["event_id=4624", "user=DOMAIN\\\\admin", "ip_address=203.0.113.45"])
            - inferences: list of strings (Hypotheses, deductions, and assumptions with noted uncertainties, e.g. ["IP categorized as external by convention; alert lacks geo/VPN metadata", "Credentials assumed compromised; no direct evidence of theft method"])

        - containment_playbook: object with:
            - immediate: list of strings (2-4 concrete actions that can be executed within hours, e.g. ["Expire/kill active sessions for DOMAIN\\\\admin", "Rotate credentials for affected account", "Block IP 203.0.113.45 at firewall"])
            - short_term: list of strings (2-4 actions within 24-48h, e.g. ["Restrict egress from DC-01", "Review AD object modifications", "Preserve logs/artifacts for forensics"])
            - references: list of strings (ATT&CK Mitigations by ID where relevant, e.g. ["M1032 Multi-factor Authentication", "M1026 Privileged Account Management", "M1030 Network Segmentation"])

        - splunk_enrichment: list of 1-4 objects, each with:
            - phase: "previous" or "next" — which kill chain side this supports
            - supports_tactic: string — one tactic from `likely_previous_steps' or `likely_next_steps`
            - purpose: string — what evidence the query attempts to find
            - query: string — write a Splunk SPL query using only data observable in the alert. Use relative time windows: previous queries use earliest=-24h@h latest=ALERT_TIME, next queries use earliest=ALERT_TIME latest=+24h@h
            - confidence_boost_rule: string — what result pattern would increase confidence in the tactic
            - confidence_reduce_rule: string — what null or negative result would imply

        ---

        RULES:
        - CRITICAL: NO EMOJIS OR UNICODE SYMBOLS; Do NOT include any emojis, unicode symbols, or special characters anywhere in your JSON response. Use only plain ASCII text characters.
        - ATTACK CHAIN: ALWAYS include EXACTLY 1 previous step and EXACTLY 1 next step** - These are hypotheses based on typical attack patterns. Quote alert field=value pairs that suggest each step, but you may infer tactics without direct proof. Include uncertainty_alternatives to acknowledge what's unknown.
        - **ATTACK-CHAIN TACTIC-SPAN REQUIREMENT** - For the top technique you identify, add a one-line "tactic_span_note" naming other ATT&CK tactics that technique commonly supports (with rationale) and why you selected the current kill_chain_phase for this alert.
        - **TIME WINDOWS: Use ALERT_TIME for relative windows** - If ALERT_TIME is provided, previous queries use earliest=-24h@h latest=ALERT_TIME, next queries use earliest=ALERT_TIME latest=+24h@h. If not provided, use relative time (earliest=-24h@h, latest=+24h@h).
        - **EVIDENCE VS INFERENCE** - Populate "evidence" with only direct field=value facts from the alert. Populate "inferences" with hypotheses and note uncertainties (geo/VPN tagging absent, protocol unknown, etc.).
        - **CONTAINMENT PLAYBOOK RULES** - Keep to 3-6 bullets total (concise). Examples: expire/kill active sessions/tokens for affected identities; rotate credentials; restrict egress from involved hosts; block non-approved admin source paths; preserve logs/artifacts. Cite ATT&CK mitigations by ID where relevant (e.g., M1032 MFA, M1026 Privileged Account Management, M1030 Network Segmentation, M1018 User Account Management, M1027 Password Policies).
        - **HUNT FAMILIES COVERAGE** - Provide 3-4 enrichment queries total. When the alert involves Windows domain authentication or privileged accounts, ensure coverage across these families (as applicable to the alert's fields): (A) Authentication anomalies (e.g., prior failures around the same user/IP), (B) Directory/Identity changes (e.g., object changes or new users/groups - event IDs 5136, 4720, 4728, 4732), (C) Lateral-movement effects (e.g., remote service creation, share access, scheduled tasks), (D) Kerberos clues (e.g., pre-auth or ticket anomalies - event IDs 4769, 4776). Use only values present in the alert and generic event families; do not invent fields or indexes. Keep index/sourcetype as PLACEHOLDER unless provided by the alert.
        - All enrichment queries must be limited to evidence present in the alert (do not fabricate fields, indexes, or sourcetypes)
        - Index/sourcetype/source must be left as `PLACEHOLDER` unless clearly identifiable in alert
        - TTP EXPLANATIONS: Always end with "Uncertainty: [brief statement]" acknowledging what is inferred vs. direct evidence
        - TTP TACTIC SPAN NOTE: For each TTP, add "tactic_span_note" naming other ATT&CK tactics that technique commonly supports and why they may apply here (one sentence).
        - TTP EVIDENCE FIELDS: For each TTP, list all alert field=value pairs that directly support it (e.g. ["event_id=4624", "user=DOMAIN\\\\admin"])
        - TTP IMMEDIATE ACTIONS: Provide urgent remediation steps if this TTP is confirmed (e.g. "Disable user account, reset credentials, isolate system")
        - TTP REMEDIATION: Provide specific defensive measures based on MITRE mitigations for this technique, citing mitigation IDs (e.g., M1032, M1026, M1030)
        - IOC EXTRACTION: Extract ALL IOCs from the alert (IPs, domains, users, hosts, processes, file paths, hashes, event IDs, URLs) - leave arrays empty [] if not found. Do not label core OS components or generic system binaries as IOCs unless the alert contains explicit malicious context.
        - CORRELATION KEYS: Identify primary indicators and search terms most useful for SIEM correlation searches
        - Do not return markdown, comments, or extra prose
        - Output only the raw JSON object
        - All fields and keys must match exactly
        """
        
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
                        inferenceConfig={
                            "maxTokens": 2000,
                            "temperature": 1.0,
                            "topP": 0.9
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
            
            # Parse the response
            logger.info("Parsing LLM response")
            content = response['output']['message']['content'][0]['text']
            logger.info(f"Raw LLM response length: {len(content)} characters")
            
            # Store raw content for debugging
            self.last_raw_content = content
            
            try:
                result = json.loads(content)
            except json.JSONDecodeError as e:
                logger.error(f"Failed to parse JSON response: {e}")
                logger.error(f"Response content (first 500 chars): {content[:500]}")
                # Store the raw content as the response so UI can display it
                self.last_llm_response = {"raw_error": content}
                return []
            
            logger.info(f"Parsed JSON result type: {type(result)}")
            
            # Store the last LLM response for markdown generation
            self.last_llm_response = result
            
            # Extract TTPs from the structured response
            scored_ttps = []
            
            if not isinstance(result, dict):
                logger.error(f"Expected dict response, got {type(result)}")
                return []
            
            # Handle the structured response with ttp_analysis
            if "ttp_analysis" in result:
                logger.info(f"Processing structured response with ttp_analysis")
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

