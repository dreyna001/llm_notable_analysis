"""Generate markdown reports for TTP analysis results.

This module mirrors the report structure used in `s3_testing/markdown_generator.py`.
"""

from typing import Dict, Any, List


def generate_markdown_report(
    alert_text: str,
    llm_response: Dict[str, Any],
    scored_ttps: List[Dict[str, Any]],
) -> str:
    """Generate a markdown report from analysis results.

    Sections:
    - Alert reconciliation
    - Competing hypotheses & pivots
    - Evidence vs inference
    - IOC extraction
    - Scored TTPs (grouped by confidence)
    """
    lines: List[str] = []

    # Alert Reconciliation (direct disposition guidance)
    if "alert_reconciliation" in llm_response:
        ar = llm_response["alert_reconciliation"]
        lines.append("### Alert Reconciliation\n\n")
        verdict = ar.get("verdict", "N/A")
        confidence = ar.get("confidence", "N/A")
        summary = ar.get("one_sentence_summary", "N/A")
        lines.append(f"**Verdict:** {verdict}\n")
        lines.append(f"**Confidence:** {confidence}\n")
        lines.append(f"**Summary:** {summary}\n\n")

        if ar.get("decision_drivers"):
            lines.append("**Decision drivers:**\n")
            for item in ar["decision_drivers"]:
                lines.append(f"- {item}\n")
            lines.append("\n")

        if ar.get("recommended_actions"):
            lines.append("**Recommended actions:**\n")
            for item in ar["recommended_actions"]:
                lines.append(f"- {item}\n")
            lines.append("\n")

    # Competing Hypotheses & Pivots
    if "competing_hypotheses" in llm_response:
        ch = llm_response["competing_hypotheses"]
        lines.append("### Competing Hypotheses & Pivots\n\n")
        for i, hyp in enumerate(ch, 1):
            hyp_type = hyp.get("hypothesis_type", "unknown").capitalize()
            lines.append(
                f"**Hypothesis {i} ({hyp_type}):** {hyp.get('hypothesis', 'N/A')}\n"
            )
            if hyp.get("evidence_support"):
                lines.append(
                    f"  - **Evidence support:** {', '.join(hyp['evidence_support'])}\n"
                )
            if hyp.get("evidence_gaps"):
                lines.append(
                    f"  - **Evidence gaps:** {', '.join(hyp['evidence_gaps'])}\n"
                )
            if hyp.get("best_pivots"):
                lines.append("  - **Best pivots:**\n")
                for pivot in hyp["best_pivots"]:
                    if isinstance(pivot, dict):
                        lines.append(
                            f"    - {pivot.get('log_source', 'N/A')}: {pivot.get('key_fields', 'N/A')}\n"
                        )
                    else:
                        lines.append(f"    - {pivot}\n")
            lines.append("\n")

    # Evidence vs Inference
    if "evidence_vs_inference" in llm_response:
        evi = llm_response["evidence_vs_inference"]
        lines.append("### Evidence vs Inference\n\n")
        if evi.get("evidence"):
            lines.append("**Evidence (Facts):**\n")
            for item in evi["evidence"]:
                lines.append(f"- {item}\n")
            lines.append("\n")
        if evi.get("inferences"):
            lines.append("**Inferences (Hypotheses):**\n")
            for item in evi["inferences"]:
                lines.append(f"- {item}\n")
            lines.append("\n")

    # IOC Extraction
    if "ioc_extraction" in llm_response:
        iocs = llm_response["ioc_extraction"]
        lines.append("### Indicators of Compromise (IOCs)\n\n")
        if iocs.get("ip_addresses"):
            lines.append(f"**IP Addresses:** {', '.join(iocs['ip_addresses'])}\n")
        if iocs.get("domains"):
            lines.append(f"**Domains:** {', '.join(iocs['domains'])}\n")
        if iocs.get("user_accounts"):
            lines.append(f"**User Accounts:** {', '.join(iocs['user_accounts'])}\n")
        if iocs.get("hostnames"):
            lines.append(f"**Hostnames:** {', '.join(iocs['hostnames'])}\n")
        if iocs.get("process_names"):
            lines.append(f"**Processes:** {', '.join(iocs['process_names'])}\n")
        if iocs.get("file_paths"):
            lines.append(f"**File Paths:** {', '.join(iocs['file_paths'])}\n")
        if iocs.get("file_hashes"):
            lines.append(f"**File Hashes:** {', '.join(iocs['file_hashes'])}\n")
        if iocs.get("event_ids"):
            lines.append(f"**Event IDs:** {', '.join(iocs['event_ids'])}\n")
        if iocs.get("urls"):
            lines.append(f"**URLs:** {', '.join(iocs['urls'])}\n")
        lines.append("\n")

    # Scored TTPs
    lines.append("### Scored TTPs\n\n")
    if scored_ttps:
        for ttp in scored_ttps:
            if "score" not in ttp:
                ttp["score"] = 0.0

        sorted_ttps = sorted(scored_ttps, key=lambda x: x["score"], reverse=True)
        high_conf = [t for t in sorted_ttps if t["score"] >= 0.80]
        med_conf = [t for t in sorted_ttps if 0.50 <= t["score"] < 0.80]
        low_conf = [t for t in sorted_ttps if t["score"] < 0.50]

        if high_conf:
            lines.append("#### High Confidence (>=0.80)\n\n")
            for ttp in high_conf:
                lines.append(
                    f"**{ttp['ttp_id']}** - {ttp.get('ttp_name', 'N/A')}: **{ttp['score']:.3f}**\n"
                )
                lines.append(f"  - **Explanation:** {ttp.get('explanation', 'N/A')}\n")
                if ttp.get("evidence_fields"):
                    lines.append(
                        f"  - **Evidence Fields:** {', '.join(ttp['evidence_fields'])}\n"
                    )
                lines.append("\n")

        if med_conf:
            lines.append("#### Medium Confidence (0.50-0.79)\n\n")
            for ttp in med_conf:
                lines.append(
                    f"**{ttp['ttp_id']}** - {ttp.get('ttp_name', 'N/A')}: **{ttp['score']:.3f}**\n"
                )
                lines.append(f"  - **Explanation:** {ttp.get('explanation', 'N/A')}\n")
                if ttp.get("evidence_fields"):
                    lines.append(
                        f"  - **Evidence Fields:** {', '.join(ttp['evidence_fields'])}\n"
                    )
                lines.append("\n")

        if low_conf:
            lines.append("#### Low Confidence (<0.50)\n\n")
            for ttp in low_conf:
                lines.append(
                    f"**{ttp['ttp_id']}** - {ttp.get('ttp_name', 'N/A')}: **{ttp['score']:.3f}**\n"
                )
                lines.append(f"  - **Explanation:** {ttp.get('explanation', 'N/A')}\n")
                if ttp.get("evidence_fields"):
                    lines.append(
                        f"  - **Evidence Fields:** {', '.join(ttp['evidence_fields'])}\n"
                    )
                lines.append("\n")
    else:
        lines.append("No TTPs scored\n\n")

    return "".join(lines)
