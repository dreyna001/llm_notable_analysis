"""Freeform (non-JSON) LLM client for on-prem notable analysis.

This mode intentionally avoids strict structured outputs and instead asks the LLM
to respond with a small number of plain paragraphs. This is useful when models
intermittently violate JSON schemas/tool contracts.
"""

from __future__ import annotations

import logging
import time
from typing import Optional, Dict, Any, Tuple

import requests

from .config import Config

logger = logging.getLogger(__name__)


_FREEFORM_PROMPT_TEMPLATE = """You are a cybersecurity expert mapping likely MITRE ATT&CK techniques from a single alert.

OUTPUT FORMAT (freeform, no schema):
- Output MUST be 3 to 6 short paragraphs.
- No bullet lists, no headings, no JSON, no code fences.
- Use only plain ASCII text (no emojis or unicode symbols).

ANALYST DOCTRINE (condensed from the structured pipeline):
- MITRE ATT&CK is many-to-many. When you mention a technique ID, also state:
  (a) the tactic you think it serves in THIS alert, and (b) other plausible tactics it commonly serves (tactic-span note).
- FACT vs INFERENCE: clearly separate what is directly observed in the alert vs what you infer.
- STATELESS: rely only on observable fields in this alert. If a required fact is not present, say "unknown" and what would disambiguate.
- IOC hygiene: do not list generic OS/core binaries as IOCs unless the alert gives explicit malicious context.
- Never output "example.com" or "PLACEHOLDER".
- Do not include URLs unless they are explicitly present in the alert text.

EVIDENCE-GATE (TTP inclusion rule):
- Only include a technique ID if you can quote the exact field=value evidence from the alert.
- If correctness depends on missing context, either use the parent technique or downgrade confidence and name the missing context.

PROCEDURE:
- If you see encodings (Base64/hex/URL-encoded/gzip), decode/deobfuscate them.
- Use sub-techniques only when the specific variant is confirmed; otherwise use the parent technique.

CAUSAL HUMILITY + PIVOT STRATEGY:
- Include EXACTLY 6 competing hypotheses: 3 benign and 3 adversary (different initial vectors).
- For each hypothesis, include at least one "evidence_support" field=value and one "evidence_gap" (unknown), and 1-2 best pivots (log_source + key_fields).
- Since you cannot use bullet lists, write the 6 hypotheses as short sentences in one paragraph, clearly labeling each as benign/adversary.

PARAGRAPH REQUIREMENTS:
- Paragraph 1: what happened (quote the most important observed fields verbatim as field=value).
- Paragraph 2: evidence vs inference (explicitly label what is evidence vs inference).
- Paragraph 3: MITRE ATT&CK mapping in prose (include technique IDs inline only if evidence-gate is met; otherwise say unknown).
- Paragraph 4: the 6 competing hypotheses + pivots (as described above).
- Paragraph 5 (optional): immediate containment/triage recommendations appropriate to the uncertainty.
- Final sentence of the last paragraph MUST start with: "Uncertainty: " and be brief.

SECURITY ALERT INPUT:
{alert_text}
"""


class FreeformLLMClient:
    """Client for local LLM inference via vLLM/OpenAI-compatible endpoint (freeform output)."""

    def __init__(self, config: Config):
        """Initialize the freeform client.

        Args:
            config: Service configuration with local endpoint settings.
        """
        self.config = config

    def _call_llm(self, prompt_text: str) -> Tuple[str, float]:
        headers = {"Content-Type": "application/json"}
        if self.config.LLM_API_TOKEN:
            headers["Authorization"] = f"Bearer {self.config.LLM_API_TOKEN}"

        request_body: Dict[str, Any] = {
            "model": self.config.LLM_MODEL_NAME,
            "prompt": prompt_text,
            "max_tokens": self.config.LLM_MAX_TOKENS,
            "temperature": 0.1,
        }

        start_time = time.time()
        response = requests.post(
            self.config.LLM_API_URL,
            json=request_body,
            headers=headers,
            timeout=self.config.LLM_TIMEOUT,
        )
        response.raise_for_status()
        elapsed = time.time() - start_time

        response_json = response.json()
        if "choices" in response_json and response_json["choices"]:
            choice0 = response_json["choices"][0]
            if "text" in choice0:
                return choice0["text"], elapsed
            if "message" in choice0 and isinstance(choice0["message"], dict):
                return choice0["message"].get("content", ""), elapsed
        raise ValueError(
            "Unexpected response format from LLM (no choices[0].text/message.content)"
        )

    def analyze_alert_freeform(self, alert_text: str) -> Dict[str, Any]:
        """Analyze one alert and return a paragraph-style narrative response.

        Args:
            alert_text: Normalized alert content to analyze.

        Returns:
            A dictionary containing either `analysis_text` and metadata or an
            `error` field when retries are exhausted.
        """
        if not alert_text or not alert_text.strip():
            return {"error": "Empty alert text", "analysis_text": ""}

        prompt = _FREEFORM_PROMPT_TEMPLATE.format(alert_text=alert_text)

        # Transport retries only (keep bounded)
        max_retries = 3
        delay = 5
        last_err: Optional[str] = None

        for attempt in range(max_retries):
            try:
                logger.info(
                    f"LLM API call attempt {attempt + 1}/{max_retries} (freeform)"
                )
                text, elapsed = self._call_llm(prompt)
                return {
                    "analysis_text": (text or "").strip(),
                    "metadata": {
                        "model": self.config.LLM_MODEL_NAME,
                        "inference_time_seconds": elapsed,
                        "prompt_length": len(prompt),
                        "attempt": attempt + 1,
                    },
                }
            except requests.exceptions.Timeout:
                last_err = "LLM API timeout"
            except requests.exceptions.RequestException as e:
                last_err = f"LLM API error: {e}"
            except Exception as e:
                last_err = f"LLM client error: {e}"

            if attempt < max_retries - 1:
                time.sleep(delay)
                delay *= 2

        return {
            "error": f"Max retries exceeded ({last_err or 'unknown'})",
            "analysis_text": "",
        }
