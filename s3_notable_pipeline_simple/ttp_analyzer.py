#!/usr/bin/env python3
"""
Simplified TTP analyzer for Bedrock.

This version focuses on alert-local evidence and produces ONLY structured JSON:
- ttp_analysis
- ioc_extraction
- evidence_vs_inference
- limitations
- hypotheses (benign_explanations + competing_hypotheses)
"""

import json
import os
import re
import time
import logging
from typing import Any, Dict, List, Optional, Set, Tuple
from pathlib import Path

import boto3
from botocore.exceptions import ClientError

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

MITRE_V17_TECHNIQUE_URL_RE = re.compile(r"^https://attack\.mitre\.org/versions/v17/techniques/T\d{4}(?:/\d{3})?/?$")


SIMPLE_ANALYZE_TOOL = {
    "toolSpec": {
        "name": "analyze_notable_simple",
        "description": "Analyze a security alert and return a minimal structured analysis",
        "inputSchema": {
            "json": {
                "type": "object",
                "additionalProperties": False,
                "properties": {
                    "ttp_analysis": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "additionalProperties": False,
                            "properties": {
                                "ttp_id": {"type": "string"},
                                "ttp_name": {"type": "string"},
                                "confidence_score": {"type": "number"},
                                "explanation": {"type": "string"},
                                "evidence_fields": {"type": "array", "items": {"type": "string"}},
                                "mitre_url": {
                                    "type": "string",
                                    "pattern": r"^$|^https://attack\\.mitre\\.org/versions/v17/techniques/T\\d{4}(?:/\\d{3})?/?$",
                                },
                            },
                            "required": [
                                "ttp_id",
                                "ttp_name",
                                "confidence_score",
                                "explanation",
                                "evidence_fields",
                                "mitre_url",
                            ],
                        },
                    },
                    "ioc_extraction": {
                        "type": "object",
                        "additionalProperties": False,
                        "properties": {
                            "ip_addresses": {"type": "array", "items": {"type": "string"}},
                            "domains": {"type": "array", "items": {"type": "string"}},
                            "user_accounts": {"type": "array", "items": {"type": "string"}},
                            "hostnames": {"type": "array", "items": {"type": "string"}},
                            "file_paths": {"type": "array", "items": {"type": "string"}},
                            "process_names": {"type": "array", "items": {"type": "string"}},
                            "file_hashes": {"type": "array", "items": {"type": "string"}},
                            "event_ids": {"type": "array", "items": {"type": "string"}},
                            "urls": {"type": "array", "items": {"type": "string"}},
                        },
                        "required": [
                            "ip_addresses",
                            "domains",
                            "user_accounts",
                            "hostnames",
                            "file_paths",
                            "process_names",
                            "file_hashes",
                            "event_ids",
                            "urls",
                        ],
                    },
                    "evidence_vs_inference": {
                        "type": "object",
                        "additionalProperties": False,
                        "properties": {
                            "evidence": {"type": "array", "items": {"type": "string"}},
                            "inferences": {"type": "array", "items": {"type": "string"}},
                        },
                        "required": ["evidence", "inferences"],
                    },
                    "limitations": {"type": "string"},
                    "benign_explanations": {
                        "type": "array",
                        "minItems": 2,
                        "maxItems": 5,
                        "items": {
                            "type": "object",
                            "additionalProperties": False,
                            "properties": {
                                "hypothesis": {"type": "string"},
                                "why_plausible": {"type": "string"},
                                "best_validation": {"type": "string"},
                            },
                            "required": ["hypothesis", "why_plausible", "best_validation"],
                        },
                    },
                    "competing_hypotheses": {
                        "type": "array",
                        "minItems": 2,
                        "maxItems": 5,
                        "items": {
                            "type": "object",
                            "additionalProperties": False,
                            "properties": {
                                "hypothesis_type": {"type": "string", "enum": ["benign", "adversary"]},
                                "hypothesis": {"type": "string"},
                                "evidence_support": {"type": "array", "items": {"type": "string"}},
                                "evidence_gaps": {"type": "array", "items": {"type": "string"}},
                            },
                            "required": ["hypothesis_type", "hypothesis", "evidence_support", "evidence_gaps"],
                        },
                    },
                },
                "required": [
                    "ttp_analysis",
                    "ioc_extraction",
                    "evidence_vs_inference",
                    "limitations",
                    "benign_explanations",
                    "competing_hypotheses",
                ],
            }
        },
    }
}


SYSTEM_PROMPT = "You are a cybersecurity expert specializing in MITRE ATT&CK TTP analysis."

RULES = """
RULES:
- Output MUST be a single JSON object produced via the tool call. No markdown.
- Use only plain ASCII.
- Evidence must be literal field=value facts from the alert.
- Inferences must clearly state uncertainty and required missing context.
- URL POLICY:
  - mitre_url must be MITRE ATT&CK v17 permalink (https://attack.mitre.org/versions/v17/...) or empty string.
  - Never output example.com anywhere.
"""

OUTPUT_INSTRUCTIONS = """
Use the analyze_notable_simple tool to return ONLY this JSON object:
- ttp_analysis: 0-5 items max; include only techniques with direct evidence in the alert.
- ioc_extraction: arrays (empty [] if none found).
- evidence_vs_inference: evidence[] must be field=value facts; inferences[] are hypotheses.
- limitations: what cannot be concluded from the alert alone.
- benign_explanations: 2-5 plausible legitimate explanations.
- competing_hypotheses: 2-5 hypotheses (mix benign/adversary) with evidence_support and evidence_gaps.
"""


class TTPValidator:
    def __init__(self, ids_file_path: Path):
        self._valid_subtechniques: Set[str] = set()
        self._valid_parent_techniques: Set[str] = set()
        ids = json.loads(ids_file_path.read_text(encoding="utf-8"))
        for ttp_id in ids:
            if "." in ttp_id:
                self._valid_subtechniques.add(ttp_id)
            else:
                self._valid_parent_techniques.add(ttp_id)

    def is_valid_ttp(self, ttp_id: str) -> bool:
        return ttp_id in self._valid_subtechniques or ttp_id in self._valid_parent_techniques


def validate_simple_schema(result: Dict[str, Any]) -> Tuple[bool, Optional[str]]:
    required = {
        "ttp_analysis": list,
        "ioc_extraction": dict,
        "evidence_vs_inference": dict,
        "limitations": str,
        "benign_explanations": list,
        "competing_hypotheses": list,
    }
    for k, t in required.items():
        if k not in result:
            return False, f"Missing required key: {k}"
        if not isinstance(result[k], t):
            return False, f"Key '{k}' must be {t.__name__}"
    return True, None


def validate_simple_policies(result: Dict[str, Any]) -> Tuple[bool, Optional[str]]:
    def iter_strings(obj: Any) -> List[str]:
        out: List[str] = []
        if isinstance(obj, dict):
            for v in obj.values():
                out.extend(iter_strings(v))
        elif isinstance(obj, list):
            for v in obj:
                out.extend(iter_strings(v))
        elif isinstance(obj, str):
            out.append(obj)
        return out

    for s in iter_strings(result):
        if "example.com" in s.lower():
            return False, "Disallowed placeholder domain example.com"

    for item in result.get("ttp_analysis", []):
        if not isinstance(item, dict):
            continue
        url = (item.get("mitre_url") or "").strip()
        if url and not MITRE_V17_TECHNIQUE_URL_RE.match(url):
            return False, "Invalid mitre_url (must be MITRE v17 technique permalink or empty)"

    return True, None


class SimpleBedrockAnalyzer:
    def __init__(self, model_id: str = "amazon.nova-pro-v1:0"):
        self.bedrock_client = boto3.client("bedrock-runtime")
        self.model_id = model_id
        ids_file = Path(__file__).parent / "enterprise_attack_v17.1_ids.json"
        self.validator = TTPValidator(ids_file)

    def format_alert_input(self, summary: str, risk_index: Dict[str, Any], raw_log: Dict[str, Any]) -> str:
        risk_text = "\n".join(
            [
                f"Risk Score: {risk_index.get('risk_score', 'N/A')}",
                f"Source Product: {risk_index.get('source_product', 'N/A')}",
                f"Threat Category: {risk_index.get('threat_category', 'N/A')}",
            ]
        )
        raw_text = " ".join(f"{k}={v}" for k, v in raw_log.items())
        return f"""[SUMMARY]
{summary or 'N/A'}

[RISK INDEX]
{risk_text}

[RAW EVENT]
{raw_text}"""

    def _converse(self, prompt: str) -> Dict[str, Any]:
        default_max_tokens = 2048
        try:
            max_tokens = int(os.environ.get("MAX_OUTPUT_TOKENS", str(default_max_tokens)))
        except ValueError:
            max_tokens = default_max_tokens
        max_tokens = max(256, min(max_tokens, 8192))

        return self.bedrock_client.converse(
            modelId=self.model_id,
            messages=[{"role": "user", "content": [{"text": prompt}]}],
            toolConfig={
                "tools": [SIMPLE_ANALYZE_TOOL],
                "toolChoice": {"tool": {"name": "analyze_notable_simple"}},
            },
            inferenceConfig={
                "maxTokens": max_tokens,
                "temperature": 0.2,
                "topP": 0.95,
            },
        )

    def analyze(self, alert_text: str) -> Dict[str, Any]:
        start = time.time()
        prompt = f"""{SYSTEM_PROMPT}

{RULES}

SECURITY ALERT INPUT:
{alert_text}

{OUTPUT_INSTRUCTIONS}
"""
        response = self._converse(prompt)
        blocks = response["output"]["message"]["content"]

        tool_input: Optional[Dict[str, Any]] = None
        for b in blocks:
            if "toolUse" in b:
                tool_input = b["toolUse"].get("input", {})
                break

        if not isinstance(tool_input, dict):
            logger.error(f"No toolUse block. Content blocks: {[list(b.keys()) for b in blocks]}")
            raise RuntimeError("No toolUse block returned")

        # Log raw structure for debugging
        logger.info(f"tool_input keys: {list(tool_input.keys())}")
        logger.debug(f"tool_input (truncated): {json.dumps(tool_input, default=str)[:2000]}")

        ok, err = validate_simple_schema(tool_input)
        if not ok:
            logger.error(f"Schema validation failed. Got keys: {list(tool_input.keys())}")
            raise RuntimeError(f"Schema validation: {err}")

        ok, err = validate_simple_policies(tool_input)
        if not ok:
            raise RuntimeError(f"Content policy: {err}")

        # Filter invalid technique IDs
        filtered = []
        for ttp in tool_input.get("ttp_analysis", []):
            ttp_id = ttp.get("ttp_id")
            if isinstance(ttp_id, str) and self.validator.is_valid_ttp(ttp_id):
                filtered.append(ttp)
        tool_input["ttp_analysis"] = filtered

        tool_input["_meta"] = {"elapsed_seconds": round(time.time() - start, 2)}
        return tool_input

