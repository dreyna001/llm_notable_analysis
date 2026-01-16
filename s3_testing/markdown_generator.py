
"""Markdown report generator for TTP analysis results.

This module generates markdown-formatted reports from TTP analysis results,
mirroring the output format from notable_analysis.py.
"""

from typing import Dict, Any, List


def generate_markdown_report(
    alert_text: str,
    llm_response: Dict[str, Any],
    scored_ttps: List[Dict[str, Any]]
) -> str:
    """Generate a markdown report from analysis results.
    
    Includes sections for IOCs, evidence vs inference, scored TTPs,
    competing hypotheses, and context enrichment.
    
    Args:
        alert_text: The original formatted alert text.
        llm_response: Full structured response from the LLM containing all analysis sections.
        scored_ttps: List of validated TTP dictionaries with scores and metadata.
        
    Returns:
        Markdown-formatted string containing the complete analysis report.
    """
    lines = []
    
    # IOC Extraction
    if "ioc_extraction" in llm_response:
        iocs = llm_response["ioc_extraction"]
        lines.append("### Indicators of Compromise (IOCs)\n\n")
        if iocs.get('ip_addresses'):
            lines.append(f"**IP Addresses:** {', '.join(iocs['ip_addresses'])}\n")
        if iocs.get('domains'):
            lines.append(f"**Domains:** {', '.join(iocs['domains'])}\n")
        if iocs.get('user_accounts'):
            lines.append(f"**User Accounts:** {', '.join(iocs['user_accounts'])}\n")
        if iocs.get('hostnames'):
            lines.append(f"**Hostnames:** {', '.join(iocs['hostnames'])}\n")
        if iocs.get('process_names'):
            lines.append(f"**Processes:** {', '.join(iocs['process_names'])}\n")
        if iocs.get('file_paths'):
            lines.append(f"**File Paths:** {', '.join(iocs['file_paths'])}\n")
        if iocs.get('file_hashes'):
            lines.append(f"**File Hashes:** {', '.join(iocs['file_hashes'])}\n")
        if iocs.get('event_ids'):
            lines.append(f"**Event IDs:** {', '.join(iocs['event_ids'])}\n")
        if iocs.get('urls'):
            lines.append(f"**URLs:** {', '.join(iocs['urls'])}\n")
        lines.append("\n")
    
    # Evidence vs Inference
    if "evidence_vs_inference" in llm_response:
        evi = llm_response["evidence_vs_inference"]
        lines.append("### Evidence vs Inference\n\n")
        if evi.get('evidence'):
            lines.append("**Evidence (Facts):**\n")
            for item in evi['evidence']:
                lines.append(f"- {item}\n")
            lines.append("\n")
        if evi.get('inferences'):
            lines.append("**Inferences (Hypotheses):**\n")
            for item in evi['inferences']:
                lines.append(f"- {item}\n")
            lines.append("\n")
    
    # Scored TTPs
    lines.append("### Scored TTPs\n\n")
    if scored_ttps:
        # Ensure all TTPs have scores
        for ttp in scored_ttps:
            if 'score' not in ttp:
                ttp['score'] = 0.0
        
        # Sort by score descending
        sorted_ttps = sorted(scored_ttps, key=lambda x: x['score'], reverse=True)
        
        # Group by confidence level
        high_conf = [t for t in sorted_ttps if t['score'] >= 0.80]
        med_conf = [t for t in sorted_ttps if 0.50 <= t['score'] < 0.80]
        low_conf = [t for t in sorted_ttps if t['score'] < 0.50]
        
        if high_conf:
            lines.append("#### High Confidence (≥0.80)\n\n")
            for ttp in high_conf:
                lines.append(f"**{ttp['ttp_id']}** - {ttp.get('ttp_name', 'N/A')}: **{ttp['score']:.3f}**\n")
                lines.append(f"  - **Explanation:** {ttp['explanation']}\n")
                if ttp.get('evidence_fields'):
                    lines.append(f"  - **Evidence Fields:** {', '.join(ttp['evidence_fields'])}\n")
                lines.append("\n")
        
        if med_conf:
            lines.append("#### Medium Confidence (0.50-0.79)\n\n")
            for ttp in med_conf:
                lines.append(f"**{ttp['ttp_id']}** - {ttp.get('ttp_name', 'N/A')}: **{ttp['score']:.3f}**\n")
                lines.append(f"  - **Explanation:** {ttp['explanation']}\n")
                if ttp.get('evidence_fields'):
                    lines.append(f"  - **Evidence Fields:** {', '.join(ttp['evidence_fields'])}\n")
                lines.append("\n")
        
        if low_conf:
            lines.append("#### Low Confidence (<0.50)\n\n")
            for ttp in low_conf:
                lines.append(f"**{ttp['ttp_id']}** - {ttp.get('ttp_name', 'N/A')}: **{ttp['score']:.3f}**\n")
                lines.append(f"  - **Explanation:** {ttp['explanation']}\n")
                if ttp.get('evidence_fields'):
                    lines.append(f"  - **Evidence Fields:** {', '.join(ttp['evidence_fields'])}\n")
                lines.append("\n")
    else:
        lines.append("No TTPs scored\n\n")
    
    # Competing Hypotheses (new section)
    if "competing_hypotheses" in llm_response:
        ch = llm_response["competing_hypotheses"]
        lines.append("### Competing Hypotheses & Pivots\n\n")
        for i, hyp in enumerate(ch, 1):
            hyp_type = hyp.get('hypothesis_type', 'unknown').capitalize()
            lines.append(f"**Hypothesis {i} ({hyp_type}):** {hyp.get('hypothesis', 'N/A')}\n")
            if hyp.get('evidence_support'):
                lines.append(f"  - **Evidence support:** {', '.join(hyp['evidence_support'])}\n")
            if hyp.get('evidence_gaps'):
                lines.append(f"  - **Evidence gaps:** {', '.join(hyp['evidence_gaps'])}\n")
            if hyp.get('best_pivots'):
                lines.append("  - **Best pivots:**\n")
                for pivot in hyp['best_pivots']:
                    if isinstance(pivot, dict):
                        lines.append(f"    - {pivot.get('log_source', 'N/A')}: {pivot.get('key_fields', 'N/A')}\n")
                    else:
                        lines.append(f"    - {pivot}\n")
            lines.append("\n")
    
    return "".join(lines)

