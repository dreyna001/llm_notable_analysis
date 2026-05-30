"""Generate markdown reports for TTP analysis results."""

from typing import Any, Dict, List


def _render_hypothesis_query_block(hyp: Dict[str, Any]) -> list[str]:
    """Render optional investigation query fields for one hypothesis."""

    query = str(hyp.get("primary_spl_query", "")).strip()
    if not query:
        return []
    lines: list[str] = [
        "  - **Primary SPL query:**\n",
        "    ```spl\n",
        f"    {query}\n",
        "    ```\n",
    ]
    for label, key in (
        ("Query strategy", "query_strategy"),
        ("Why this query", "why_this_query"),
        ("Supports if", "supports_if"),
        ("Weakens if", "weakens_if"),
    ):
        value = str(hyp.get(key, "")).strip()
        if value:
            lines.append(f"  - **{label}:** {value}\n")
    refs = hyp.get("primary_spl_query_grounding_refs")
    if isinstance(refs, list) and refs:
        lines.append("  - **SPL grounding refs:**\n")
        for ref in refs:
            if isinstance(ref, dict):
                source = ref.get("source_file", "unknown_source")
                section = ref.get("section_path", "root")
                lines.append(f"    - {source} :: {section}\n")
    return lines


def _render_query_results_section(llm_response: Dict[str, Any]) -> list[str]:
    section = llm_response.get("query_result_section")
    if not isinstance(section, dict):
        return []
    queries = section.get("queries", [])
    if not isinstance(queries, list) or not queries:
        return []
    lines = ["### Query Results\n\n"]
    summary = section.get("summary", {})
    if isinstance(summary, dict):
        lines.append(
            "**Summary:** "
            f"attempted={summary.get('attempted', 0)}, "
            f"executed={summary.get('executed', 0)}, "
            f"denied={summary.get('denied', 0)}, "
            f"failed={summary.get('failed', 0)}, "
            f"skipped={summary.get('skipped', 0)}\n\n"
        )
    for item in queries:
        if not isinstance(item, dict):
            continue
        idx = item.get("hypothesis_index")
        lines.append(f"**Hypothesis {idx}:** {item.get('status', 'unknown')}\n")
        lines.append(f"- **Query:** `{item.get('query', '')}`\n")
        lines.append(f"- **Result count:** {item.get('result_count', 0)}\n")
        if item.get("search_reference"):
            lines.append(f"- **Reference:** {item.get('search_reference')}\n")
        if item.get("message"):
            lines.append(f"- **Message:** {item.get('message')}\n")
        rows = item.get("sample_rows")
        if isinstance(rows, list) and rows:
            lines.append("- **Sample rows:**\n")
            for row in rows[:3]:
                lines.append(f"  - `{row}`\n")
        lines.append("\n")
    return lines


def _render_query_result_interpretation_section(llm_response: Dict[str, Any]) -> list[str]:
    items = llm_response.get("query_result_interpretation")
    if not isinstance(items, list) or not items:
        return []
    lines = ["### Query Result Interpretation\n\n"]
    for item in items:
        if not isinstance(item, dict):
            continue
        lines.append(f"**Hypothesis {item.get('hypothesis_index')}:** {item.get('assessment', 'unknown')}\n")
        lines.append(f"- **Confidence delta:** {item.get('confidence_delta', 'unknown')}\n")
        if item.get("rationale"):
            lines.append(f"- **Rationale:** {item.get('rationale')}\n")
        refs = item.get("source_query_refs")
        if isinstance(refs, list) and refs:
            lines.append(f"- **Source query refs:** {', '.join(str(ref) for ref in refs)}\n")
        observations = item.get("key_observations")
        if isinstance(observations, list) and observations:
            lines.append("- **Key observations:**\n")
            for observation in observations:
                lines.append(f"  - {observation}\n")
        gaps = item.get("remaining_gaps")
        if isinstance(gaps, list) and gaps:
            lines.append("- **Remaining gaps:**\n")
            for gap in gaps:
                lines.append(f"  - {gap}\n")
        lines.append("\n")
    return lines


def _render_servicenow_section(llm_response: Dict[str, Any]) -> list[str]:
    section = llm_response.get("servicenow_section")
    if not isinstance(section, dict):
        return []
    lines = ["### ServiceNow\n\n"]
    draft = section.get("draft", {})
    if isinstance(draft, dict):
        lines.append(f"**Draft:** {draft.get('status', 'unknown')}\n")
        if draft.get("message"):
            lines.append(f"- {draft.get('message')}\n")
        payload = draft.get("incident_payload")
        if isinstance(payload, dict):
            lines.append(f"- **Short description:** {payload.get('short_description', '')}\n")
            lines.append(f"- **Assignment group:** {payload.get('assignment_group', '')}\n")
    create = section.get("create", {})
    if isinstance(create, dict):
        lines.append(f"\n**Create:** {create.get('status', 'unknown')}\n")
        if create.get("number"):
            lines.append(f"- **Number:** {create.get('number')}\n")
        if create.get("sys_id"):
            lines.append(f"- **sys_id:** {create.get('sys_id')}\n")
        if create.get("message"):
            lines.append(f"- {create.get('message')}\n")
    lines.append("\n")
    return lines


def generate_markdown_report(
    alert_text: str,
    llm_response: Dict[str, Any],
    scored_ttps: List[Dict[str, Any]],
) -> str:
    """Generate a markdown report from analysis results."""
    lines: List[str] = []

    if llm_response.get("poc_unstructured_output"):
        reason = str(llm_response.get("poc_fallback_reason", "unknown"))
        raw = llm_response.get("raw_response") or ""
        lines.append("## PoC: raw model output\n\n")
        lines.append(
            "Structured JSON validation did not succeed. The block below preserves the "
            "model text for analyst review (proof-of-concept).\n\n"
        )
        lines.append(f"**Fallback reason:** {reason}\n\n")
        safe = raw.replace("~~~", "~\\~~\\~~")
        lines.append("~~~text\n")
        lines.append(safe)
        if safe and not safe.endswith("\n"):
            lines.append("\n")
        lines.append("~~~\n\n")
        lines.append("---\n\n")

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
            lines.extend(_render_hypothesis_query_block(hyp))
            if hyp.get("query_result_summary"):
                lines.append(f"  - **Query result:** {hyp.get('query_result_summary')}\n")
            if hyp.get("query_result_reference"):
                lines.append(f"  - **Query result reference:** {hyp.get('query_result_reference')}\n")
            lines.append("\n")

    lines.extend(_render_query_results_section(llm_response))
    lines.extend(_render_query_result_interpretation_section(llm_response))
    lines.extend(_render_servicenow_section(llm_response))

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

