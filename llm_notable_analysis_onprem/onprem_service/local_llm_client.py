"""Local LLM client for vLLM/OpenAI-compatible inference.

Replaces BedrockAnalyzer from the cloud pipeline with local HTTP calls
to vLLM server running gpt-oss-20b.
"""

import json
import logging
import time
from typing import List, Dict, Any, Optional
import requests

from .config import Config
from .ttp_validator import TTPValidator

logger = logging.getLogger(__name__)


class LocalLLMClient:
    """Client for local LLM inference via vLLM/OpenAI-compatible endpoint."""
    
    def __init__(self, config: Config, ttp_validator: TTPValidator):
        """Initialize the local LLM client.
        
        Args:
            config: Service configuration.
            ttp_validator: TTPValidator instance for filtering invalid TTPs.
        """
        self.config = config
        self.ttp_validator = ttp_validator
    
    def _build_prompt(self, alert_text: str, alert_time: Optional[str] = None) -> str:
        """Build the analysis prompt.
        
        Ported from s3_notable_pipeline/ttp_analyzer.py format_alert_input().
        
        Args:
            alert_text: The alert content to analyze.
            alert_time: Optional timestamp for time window references.
            
        Returns:
            Formatted prompt string.
        """
        valid_ttps_list = self.ttp_validator.get_valid_ttps_for_prompt()
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
        D. If evidence correctness depends on context not in the log (e.g., domain internal/external, IP a DC), drop to the parent technique or reduce confidence by >=0.20 and state the missing context in your explanation.

        Scoring Rubric: 
        - high >= 0.80 = direct, unambiguous
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

        OUTPUT FORMAT: Return ONLY a single valid JSON object. Do not include markdown code fences or any text outside the JSON. Start your response with an opening brace and end with a closing brace. The JSON object must have these top-level keys:
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
            - confidence_score: float (0.0-1.0)
            - explanation: string (A brief explanation of why this TTP was inferred, using quoted evidence from the alert. End with "Uncertainty: [brief statement]" acknowledging what is inferred vs. direct evidence, and any missing context like geo/VPN metadata, edge telemetry, etc.)
            - tactic_span_note: string (One sentence naming other ATT&CK tactics this technique commonly supports and why they may apply here)
            - evidence_fields: list of strings (Specific alert field=value pairs that directly support this TTP)
            - immediate_actions: string (Urgent remediation steps if this TTP is confirmed)
            - remediation_recommendations: string (Specific defensive measures to prevent or detect this technique, citing MITRE mitigations by ID)
            - mitre_url: mitre version permalink url for the technique

        - attack_chain: object with:
            - likely_previous_steps: list of EXACTLY 1 object (hypothesis), with:
                - tactic_id: string (MITRE ATT&CK Tactic ID)
                - tactic_name: string
                - mitre_url: string
                - why_this_step: string
                - what_to_check: string
                - uncertainty_alternatives: string
                - investigation_tree: object with exactly 3 questions (Q1, Q2, Q3)
            - likely_next_steps: list of EXACTLY 1 object (hypothesis), same structure
            - kill_chain_phase: string
            - tactic_span_note: string

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
            - evidence: list of strings
            - inferences: list of strings

        - containment_playbook: object with:
            - immediate: list of strings (2-4 concrete actions)
            - short_term: list of strings (2-4 actions within 24-48h)
            - references: list of strings (ATT&CK Mitigations by ID)

        - splunk_enrichment: list of 1-4 objects, each with:
            - phase: "previous" or "next"
            - supports_tactic: string
            - purpose: string
            - query: string (Splunk SPL query)
            - confidence_boost_rule: string
            - confidence_reduce_rule: string

        ---

        RULES:
        - CRITICAL: NO EMOJIS OR UNICODE SYMBOLS; use only plain ASCII text characters.
        - ATTACK CHAIN: ALWAYS include EXACTLY 1 previous step and EXACTLY 1 next step.
        - Do not return markdown, comments, or extra prose.
        - Output only the raw JSON object.
        - All fields and keys must match exactly.
        """
        return prompt
    
    def _parse_llm_response(self, response_text: str) -> Dict[str, Any]:
        """Parse LLM response text into structured JSON.
        
        Args:
            response_text: Raw text from LLM.
            
        Returns:
            Parsed JSON dict.
            
        Raises:
            json.JSONDecodeError: If response is not valid JSON.
        """
        # Strip markdown code fences if present
        text = response_text.strip()
        if text.startswith("```json"):
            text = text[7:]
        if text.startswith("```"):
            text = text[3:]
        if text.endswith("```"):
            text = text[:-3]
        text = text.strip()
        
        # Find the first { and last } to extract JSON
        start_idx = text.find("{")
        end_idx = text.rfind("}")
        if start_idx != -1 and end_idx != -1 and end_idx > start_idx:
            text = text[start_idx:end_idx + 1]
        
        return json.loads(text)
    
    def analyze_alert(
        self,
        alert_text: str,
        alert_time: Optional[str] = None
    ) -> Dict[str, Any]:
        """Analyze an alert and return structured TTP analysis.
        
        Args:
            alert_text: The alert content to analyze.
            alert_time: Optional timestamp for time window references.
            
        Returns:
            Dict containing:
                - ttp_analysis: List of scored, validated TTPs
                - attack_chain: Chain analysis
                - ioc_extraction: Extracted IOCs
                - correlation_keys: Correlation hints
                - evidence_vs_inference: Evidence breakdown
                - containment_playbook: Response actions
                - splunk_enrichment: Enrichment queries
                - raw_response: Original LLM response
                - metadata: Processing metadata
        """
        if not alert_text or not alert_text.strip():
            logger.error("Alert text is empty or whitespace only")
            return {"error": "Empty alert text", "ttp_analysis": []}
        
        prompt = self._build_prompt(alert_text, alert_time)
        
        # Build vLLM/OpenAI-compatible request
        request_body = {
            "model": self.config.LLM_MODEL_NAME,
            "prompt": prompt,
            "max_tokens": self.config.LLM_MAX_TOKENS,
            "temperature": 0.0
        }
        
        headers = {"Content-Type": "application/json"}
        if self.config.LLM_API_TOKEN:
            headers["Authorization"] = f"Bearer {self.config.LLM_API_TOKEN}"
        
        # Retry logic
        max_retries = 3
        retry_delay = 5
        
        for attempt in range(max_retries):
            try:
                logger.info(f"LLM API call attempt {attempt + 1}/{max_retries}")
                start_time = time.time()
                
                response = requests.post(
                    self.config.LLM_API_URL,
                    json=request_body,
                    headers=headers,
                    timeout=self.config.LLM_TIMEOUT
                )
                response.raise_for_status()
                
                elapsed = time.time() - start_time
                logger.info(f"LLM API call completed in {elapsed:.2f}s")
                
                response_json = response.json()
                
                # Extract text from OpenAI-compatible response
                if "choices" in response_json and len(response_json["choices"]) > 0:
                    # vLLM completions format
                    if "text" in response_json["choices"][0]:
                        llm_text = response_json["choices"][0]["text"]
                    # OpenAI chat format
                    elif "message" in response_json["choices"][0]:
                        llm_text = response_json["choices"][0]["message"]["content"]
                    else:
                        raise ValueError("Unexpected response format from LLM")
                else:
                    raise ValueError("No choices in LLM response")
                
                # Parse the response
                parsed = self._parse_llm_response(llm_text)
                
                # Validate and filter TTPs
                if "ttp_analysis" in parsed:
                    parsed["ttp_analysis"] = self.ttp_validator.filter_valid_ttps(
                        parsed["ttp_analysis"]
                    )
                
                # Add metadata
                parsed["metadata"] = {
                    "model": self.config.LLM_MODEL_NAME,
                    "inference_time_seconds": elapsed,
                    "prompt_length": len(prompt),
                    "attempt": attempt + 1
                }
                parsed["raw_response"] = llm_text
                
                return parsed
                
            except requests.exceptions.Timeout:
                logger.warning(f"LLM API timeout on attempt {attempt + 1}")
                if attempt < max_retries - 1:
                    time.sleep(retry_delay)
                    retry_delay *= 2
                else:
                    return {"error": "LLM API timeout after retries", "ttp_analysis": []}
                    
            except requests.exceptions.RequestException as e:
                logger.error(f"LLM API request error: {e}")
                if attempt < max_retries - 1:
                    time.sleep(retry_delay)
                    retry_delay *= 2
                else:
                    return {"error": f"LLM API error: {e}", "ttp_analysis": []}
                    
            except (json.JSONDecodeError, ValueError) as e:
                logger.error(f"LLM response parsing error: {e}")
                return {"error": f"Response parsing error: {e}", "ttp_analysis": []}
        
        return {"error": "Max retries exceeded", "ttp_analysis": []}

