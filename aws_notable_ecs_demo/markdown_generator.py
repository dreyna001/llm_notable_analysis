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
    
    Mirrors the format from notable_analysis.py output files, including sections
    for alert text, IOCs, correlation keys, evidence vs inference, containment
    playbook, scored TTPs, attack chain analysis, and Splunk enrichment queries.
    
    Args:
        alert_text: The original formatted alert text.
        llm_response: Full structured response from the LLM containing all analysis sections.
        scored_ttps: List of validated TTP dictionaries with scores and metadata.
        
    Returns:
        Markdown-formatted string containing the complete analysis report.
    """
    lines = []
    
    # Alert Text section
    lines.append("## Alert Text\n")
    lines.append(alert_text + "\n\n")
    
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
    
    # Correlation Keys
    if "correlation_keys" in llm_response:
        corr_keys = llm_response["correlation_keys"]
        lines.append("### Correlation Keys\n\n")
        if corr_keys.get('primary_indicators'):
            lines.append(f"**Primary Indicators:** {', '.join(corr_keys['primary_indicators'])}\n")
        if corr_keys.get('search_terms'):
            lines.append(f"**Search Terms:** {', '.join(corr_keys['search_terms'])}\n")
        if corr_keys.get('time_window_suggested'):
            lines.append(f"**Suggested Time Window:** {corr_keys['time_window_suggested']}\n")
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
    
    # Containment Playbook
    if "containment_playbook" in llm_response:
        playbook = llm_response["containment_playbook"]
        lines.append("### Containment Playbook\n\n")
        if playbook.get('immediate'):
            lines.append("**Immediate Actions (within hours):**\n")
            for action in playbook['immediate']:
                lines.append(f"- {action}\n")
            lines.append("\n")
        if playbook.get('short_term'):
            lines.append("**Short-term Actions (24-48h):**\n")
            for action in playbook['short_term']:
                lines.append(f"- {action}\n")
            lines.append("\n")
        if playbook.get('references'):
            lines.append("**References (ATT&CK Mitigations):**\n")
            for ref in playbook['references']:
                lines.append(f"- {ref}\n")
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
                if ttp.get('tactic_span_note'):
                    lines.append(f"  - **Tactic Span:** {ttp['tactic_span_note']}\n")
                if ttp.get('evidence_fields'):
                    lines.append(f"  - **Evidence Fields:** {', '.join(ttp['evidence_fields'])}\n")
                if ttp.get('immediate_actions'):
                    lines.append(f"  - **Immediate Actions:** {ttp['immediate_actions']}\n")
                if ttp.get('remediation_recommendations'):
                    lines.append(f"  - **Remediation:** {ttp['remediation_recommendations']}\n")
                if ttp.get('mitre_url'):
                    lines.append(f"  - **MITRE URL:** {ttp['mitre_url']}\n")
                lines.append("\n")
        
        if med_conf:
            lines.append("#### Medium Confidence (0.50-0.79)\n\n")
            for ttp in med_conf:
                lines.append(f"**{ttp['ttp_id']}** - {ttp.get('ttp_name', 'N/A')}: **{ttp['score']:.3f}**\n")
                lines.append(f"  - **Explanation:** {ttp['explanation']}\n")
                if ttp.get('tactic_span_note'):
                    lines.append(f"  - **Tactic Span:** {ttp['tactic_span_note']}\n")
                if ttp.get('evidence_fields'):
                    lines.append(f"  - **Evidence Fields:** {', '.join(ttp['evidence_fields'])}\n")
                if ttp.get('immediate_actions'):
                    lines.append(f"  - **Immediate Actions:** {ttp['immediate_actions']}\n")
                if ttp.get('remediation_recommendations'):
                    lines.append(f"  - **Remediation:** {ttp['remediation_recommendations']}\n")
                if ttp.get('mitre_url'):
                    lines.append(f"  - **MITRE URL:** {ttp['mitre_url']}\n")
                lines.append("\n")
        
        if low_conf:
            lines.append("#### Low Confidence (<0.50)\n\n")
            for ttp in low_conf:
                lines.append(f"**{ttp['ttp_id']}** - {ttp.get('ttp_name', 'N/A')}: **{ttp['score']:.3f}**\n")
                lines.append(f"  - **Explanation:** {ttp['explanation']}\n")
                if ttp.get('tactic_span_note'):
                    lines.append(f"  - **Tactic Span:** {ttp['tactic_span_note']}\n")
                if ttp.get('evidence_fields'):
                    lines.append(f"  - **Evidence Fields:** {', '.join(ttp['evidence_fields'])}\n")
                if ttp.get('immediate_actions'):
                    lines.append(f"  - **Immediate Actions:** {ttp['immediate_actions']}\n")
                if ttp.get('remediation_recommendations'):
                    lines.append(f"  - **Remediation:** {ttp['remediation_recommendations']}\n")
                if ttp.get('mitre_url'):
                    lines.append(f"  - **MITRE URL:** {ttp['mitre_url']}\n")
                lines.append("\n")
    else:
        lines.append("No TTPs scored\n\n")
    
    # Attack Chain Analysis
    if "attack_chain" in llm_response:
        lines.append("### Attack Chain Analysis\n\n")
        attack_chain = llm_response["attack_chain"]
        
        if "likely_previous_steps" in attack_chain and attack_chain["likely_previous_steps"]:
            step = attack_chain["likely_previous_steps"][0]
            if isinstance(step, dict):
                lines.append(f"**Likely Previous Step:** {step.get('tactic_name', 'N/A')} ({step.get('tactic_id', 'N/A')})\n\n")
                if step.get('mitre_url'):
                    lines.append(f"MITRE URL: {step['mitre_url']}\n\n")
                
                if step.get('why_this_step'):
                    lines.append(f"**Why:** {step['why_this_step']}\n\n")
                
                if step.get('what_to_check'):
                    lines.append(f"**Check:** {step['what_to_check']}\n\n")
                
                if step.get('uncertainty_alternatives'):
                    lines.append(f"**Uncertainty:** {step['uncertainty_alternatives']}\n\n")
                
                if step.get('investigation_tree'):
                    lines.append("**Investigation Questions:**\n\n")
                    inv_tree = step['investigation_tree']
                    if isinstance(inv_tree, dict):
                        for question_id, tree in inv_tree.items():
                            if isinstance(tree, dict):
                                lines.append(f"- {question_id}: {tree.get('question', 'N/A')}\n")
                            else:
                                lines.append(f"- {question_id}: {tree}\n")
                    lines.append("\n")
        
        if "likely_next_steps" in attack_chain and attack_chain["likely_next_steps"]:
            step = attack_chain["likely_next_steps"][0]
            if isinstance(step, dict):
                lines.append(f"**Likely Next Step:** {step.get('tactic_name', 'N/A')} ({step.get('tactic_id', 'N/A')})\n\n")
                if step.get('mitre_url'):
                    lines.append(f"MITRE URL: {step['mitre_url']}\n\n")
                
                if step.get('why_this_step'):
                    lines.append(f"**Why:** {step['why_this_step']}\n\n")
                
                if step.get('what_to_check'):
                    lines.append(f"**Check:** {step['what_to_check']}\n\n")
                
                if step.get('uncertainty_alternatives'):
                    lines.append(f"**Uncertainty:** {step['uncertainty_alternatives']}\n\n")
                
                if step.get('investigation_tree'):
                    lines.append("**Investigation Questions:**\n\n")
                    inv_tree = step['investigation_tree']
                    if isinstance(inv_tree, dict):
                        for question_id, tree in inv_tree.items():
                            if isinstance(tree, dict):
                                lines.append(f"- {question_id}: {tree.get('question', 'N/A')}\n")
                            else:
                                lines.append(f"- {question_id}: {tree}\n")
                    lines.append("\n")
        
        if "kill_chain_phase" in attack_chain:
            lines.append(f"**Kill Chain Phase:** {attack_chain['kill_chain_phase']}\n\n")
        if "tactic_span_note" in attack_chain:
            lines.append(f"**Tactic Span Note:** {attack_chain['tactic_span_note']}\n\n")
    
    # Splunk Enrichment Queries
    splunk_key = None
    for k in ['splunk_enrichment', 'splunk_queries']:
        if k in llm_response:
            splunk_key = k
            break
    if splunk_key:
        lines.append("### Splunk Enrichment Queries\n\n")
        for q in llm_response[splunk_key]:
            lines.append(f"**Phase:** {q.get('phase', 'N/A')}\n")
            lines.append(f"**Supports Tactic:** {q.get('supports_tactic', 'N/A')}\n")
            lines.append(f"**Purpose:** {q.get('purpose', 'N/A')}\n")
            lines.append(f"**Query:** {q.get('query', 'N/A')}\n")
            lines.append(f"  - **Confidence Boost Rule:** {q.get('confidence_boost_rule', 'N/A')}\n")
            lines.append(f"  - **Confidence Reduce Rule:** {q.get('confidence_reduce_rule', 'N/A')}\n\n")
    
    return "".join(lines)

