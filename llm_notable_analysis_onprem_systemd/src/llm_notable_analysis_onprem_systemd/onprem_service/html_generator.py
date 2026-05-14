"""Generate static HTML dashboard reports for notable analysis results."""

from __future__ import annotations

import json
import re
from datetime import datetime
from html import escape
from typing import Any, Dict, Iterable, List, Tuple


_IOC_FIELDS = (
    ("ip_addresses", "IP addresses"),
    ("domains", "Domains"),
    ("user_accounts", "User accounts"),
    ("hostnames", "Hostnames"),
    ("process_names", "Processes"),
    ("file_paths", "File paths"),
    ("file_hashes", "File hashes"),
    ("event_ids", "Event IDs"),
    ("urls", "URLs"),
)

_EVIDENCE_KEYS = (
    ("finding_type", "Finding type"),
    ("eventName", "API call"),
    ("event_name", "API call"),
    ("api_call", "API call"),
    ("eventSource", "Service"),
    ("event_source", "Service"),
    ("service", "Service"),
    ("errorCode", "Error code"),
    ("error_code", "Error code"),
    ("sourceIPAddress", "Source IP"),
    ("source_ip", "Source IP"),
    ("source_org", "Source org"),
    ("principal", "Principal"),
    ("principalName", "Principal"),
    ("principal_type", "Principal type"),
    ("instance_id", "Instance ID"),
    ("region", "Region"),
    ("account_id", "Account"),
    ("account", "Account"),
    ("first_seen", "First seen"),
    ("last_seen", "Last seen"),
)


def _html(value: Any) -> str:
    """Escape untrusted values before embedding them in HTML."""
    return escape(str(value if value is not None else ""), quote=True)


def _as_dict(value: Any) -> Dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _as_list(value: Any) -> List[Any]:
    return value if isinstance(value, list) else []


def _clean_text(value: Any, default: str = "unknown") -> str:
    text = str(value if value is not None else "").strip()
    return text or default


def _parse_alert(alert_text: str) -> Dict[str, Any]:
    try:
        parsed = json.loads(alert_text)
    except (TypeError, json.JSONDecodeError):
        return {}
    return parsed if isinstance(parsed, dict) else {}


def _first_value(data: Dict[str, Any], keys: Iterable[str], default: str = "") -> str:
    for key in keys:
        value = data.get(key)
        if isinstance(value, (str, int, float)) and str(value).strip():
            return str(value).strip()
    return default


def _list_items(items: Iterable[Any], *, empty: str = "No items available.") -> str:
    values = [str(item).strip() for item in items if str(item).strip()]
    if not values:
        return f'<p class="empty">{_html(empty)}</p>'
    return '<ul class="clean-list">' + "".join(f"<li>{_html(item)}</li>" for item in values) + "</ul>"


def _detail_grid(rows: Iterable[Tuple[str, Any]]) -> str:
    rendered = []
    for label, value in rows:
        rendered.append(
            '<div class="detail-row">'
            f'<span class="detail-label">{_html(label)}</span>'
            f'<span class="detail-value">{_html(_clean_text(value))}</span>'
            '</div>'
        )
    return '<div class="detail-grid">' + "".join(rendered) + "</div>"


def _score_value(item: Dict[str, Any]) -> float:
    raw = item.get("score", item.get("confidence_score", item.get("confidence", 0.0)))
    try:
        return float(raw)
    except (TypeError, ValueError):
        return 0.0


def _confidence_float(value: Any) -> float | None:
    text = _clean_text(value, "")
    if not text:
        return None
    match = re.search(r"(\d+(?:\.\d+)?)", text)
    if not match:
        return None
    number = float(match.group(1))
    if number > 1:
        number = number / 100.0
    return max(0.0, min(number, 1.0))


def _confidence_display(value: Any) -> Tuple[str, str, int]:
    confidence = _confidence_float(value)
    if confidence is None:
        text = _clean_text(value, "unknown")
        return text, text, 0
    return f"{round(confidence * 100)}%", f"{confidence:.2f}", round(confidence * 100)


def _date_value(value: str) -> datetime | None:
    text = value.strip().replace("Z", "+00:00")
    if not text:
        return None
    try:
        return datetime.fromisoformat(text)
    except ValueError:
        return None


def _window_metric(alert_data: Dict[str, Any]) -> Tuple[str, str]:
    first_seen = _first_value(alert_data, ("first_seen", "firstSeen", "createdAt", "start_time"))
    last_seen = _first_value(alert_data, ("last_seen", "lastSeen", "updatedAt", "end_time"))
    start = _date_value(first_seen)
    end = _date_value(last_seen)
    if start and end:
        days = max((end - start).days, 0)
        return f"{days}d", f"{first_seen} to {last_seen}"
    if first_seen or last_seen:
        return "known", " to ".join(item for item in (first_seen, last_seen) if item)
    return "unknown", "Not provided"


def _flatten_strings(value: Any) -> List[str]:
    if isinstance(value, dict):
        output: List[str] = []
        for child in value.values():
            output.extend(_flatten_strings(child))
        return output
    if isinstance(value, list):
        output = []
        for child in value:
            output.extend(_flatten_strings(child))
        return output
    if isinstance(value, (str, int, float)):
        text = str(value).strip()
        return [text] if text else []
    return []


def _count_matching_strings(value: Any, pattern: str) -> int:
    regex = re.compile(pattern)
    return len({item for item in _flatten_strings(value) if regex.search(item)})


def _metric(label: str, value: Any, subtext: str = "", *, danger: bool = False) -> str:
    style = ' style="font-size:16px;color:#f87171;margin-top:4px;"' if danger else ""
    sub = f'<div class="metric-sub">{_html(subtext)}</div>' if subtext else ""
    return (
        '<div class="metric">'
        f'<div class="metric-label">{_html(label)}</div>'
        f'<div class="metric-value"{style}>{_html(value)}</div>'
        f"{sub}</div>"
    )


def _tab_button(tab_id: str, label: str, *, active: bool = False) -> str:
    active_class = " active" if active else ""
    return (
        f'<button class="tab{active_class}" type="button" '
        f'data-tab="{tab_id}">{_html(label)}</button>'
    )


def _section(tab_id: str, body: str, *, active: bool = False) -> str:
    active_class = " active" if active else ""
    return f'<div id="{tab_id}" class="section{active_class}">{body}</div>'


def _severity_badge(alert_data: Dict[str, Any]) -> str:
    severity = _first_value(alert_data, ("severity", "risk_score", "score"), "UNKNOWN")
    return f'<span class="badge badge-red">{_html(severity)}</span>'


def _source_badge(alert_data: Dict[str, Any]) -> str:
    source = _first_value(alert_data, ("source", "product", "provider", "finding_source"), "")
    if not source:
        source = _first_value(alert_data, ("eventSource", "event_source", "service"), "Source unknown")
    return f'<span class="badge badge-blue">{_html(source)}</span>'


def _actions_from_response(response: Dict[str, Any]) -> List[str] | Dict[str, List[str]]:
    actions = response.get("actions")
    if isinstance(actions, dict):
        grouped: Dict[str, List[str]] = {}
        for key, value in actions.items():
            items = [str(item).strip() for item in _as_list(value) if str(item).strip()]
            if items:
                grouped[str(key).strip() or "actions"] = items
        if grouped:
            return grouped
    if isinstance(actions, list):
        items = [str(item).strip() for item in actions if str(item).strip()]
        if items:
            return items
    ar_actions = _as_list(_as_dict(response.get("alert_reconciliation")).get("recommended_actions"))
    return [str(item).strip() for item in ar_actions if str(item).strip()]


def _render_action_group(title: str, items: List[str], class_name: str) -> str:
    if not items:
        return ""
    dot_class = {
        "ag-immediate": "dot-red",
        "ag-short": "dot-amber",
        "ag-long": "dot-blue",
    }.get(class_name, "dot-blue")
    rows = "".join(
        '<div class="action-item">'
        f'<span class="action-dot {dot_class}"></span>'
        f'<span class="action-text">{_html(item)}</span>'
        '</div>'
        for item in items
    )
    return (
        '<div class="action-group">'
        f'<span class="action-group-title {class_name}">{_html(title)}</span>'
        f"{rows}</div>"
    )


def _render_actions(actions: List[str] | Dict[str, List[str]]) -> str:
    if isinstance(actions, dict):
        immediate = actions.get("immediate", []) + actions.get("Immediate", [])
        short = (
            actions.get("short_term", [])
            + actions.get("short-term", [])
            + actions.get("short", [])
            + actions.get("Short-term", [])
        )
        long = (
            actions.get("long_term", [])
            + actions.get("long-term", [])
            + actions.get("long", [])
            + actions.get("Long-term", [])
        )
        known = set(immediate + short + long)
        other = [item for group in actions.values() for item in group if item not in known]
        body = (
            _render_action_group("Immediate", immediate or other, "ag-immediate")
            + _render_action_group("Short-term", short, "ag-short")
            + _render_action_group("Long-term", long, "ag-long")
        )
    else:
        body = _render_action_group("Immediate", actions, "ag-immediate")
    return f'<div class="card">{body}</div>'


def _hypothesis_summary(response: Dict[str, Any]) -> str:
    hypotheses = [_as_dict(item) for item in _as_list(response.get("competing_hypotheses"))]
    benign = next((item for item in hypotheses if _clean_text(item.get("hypothesis_type"), "").lower() == "benign"), {})
    adversary = next((item for item in hypotheses if _clean_text(item.get("hypothesis_type"), "").lower() == "adversary"), {})
    if not benign and not adversary:
        return '<p class="empty">No hypothesis summary available.</p>'
    parts = []
    if benign:
        parts.append(
            '<div class="hyp ben">'
            f'<div class="hyp-title">{_html(_clean_text(benign.get("hypothesis")))}</div>'
            f'<div class="hyp-body">{_html("; ".join(str(item) for item in _as_list(benign.get("evidence_support"))) or "No supporting evidence listed.")}</div>'
            '</div>'
        )
    if adversary:
        parts.append(
            '<div class="hyp mal">'
            f'<div class="hyp-title">{_html(_clean_text(adversary.get("hypothesis")))}</div>'
            f'<div class="hyp-body">{_html("; ".join(str(item) for item in _as_list(adversary.get("evidence_support"))) or "No supporting evidence listed.")}</div>'
            '</div>'
        )
    return "".join(parts)


def _split_decision_drivers(response: Dict[str, Any]) -> Tuple[List[str], List[str]]:
    drivers = [str(item).strip() for item in _as_list(_as_dict(response.get("alert_reconciliation")).get("decision_drivers")) if str(item).strip()]
    malicious_words = ("malicious", "adversary", "suspicious", "exfil", "denied", "outside", "persistent", "credential")
    benign_words = ("benign", "authorized", "approved", "scanner", "known", "managed", "expected", "legitimate")
    malicious = [item for item in drivers if any(word in item.lower() for word in malicious_words)]
    benign = [item for item in drivers if any(word in item.lower() for word in benign_words)]
    if not malicious and not benign:
        midpoint = max(1, len(drivers) // 2)
        malicious = drivers[:midpoint]
        benign = drivers[midpoint:]
    return malicious, benign


def _render_verdict(response: Dict[str, Any]) -> str:
    ar = _as_dict(response.get("alert_reconciliation"))
    confidence_display, confidence_decimal, confidence_pct = _confidence_display(ar.get("confidence"))
    malicious, benign = _split_decision_drivers(response)
    return (
        '<div class="two-col">'
        '<div class="card">'
        '<div class="card-title">Confidence breakdown</div>'
        '<div class="conf-row">'
        '<span class="conf-label">Overall</span>'
        '<div class="bar-bg">'
        f'<div class="bar-fill" style="width:{confidence_pct}%;background:#fbbf24;"></div>'
        '</div>'
        f'<span class="conf-pct">{_html(confidence_decimal)}</span>'
        '</div>'
        f'<p class="summary-spaced">{_html(_clean_text(ar.get("one_sentence_summary"), "No summary provided."))}</p>'
        '</div>'
        '<div class="card">'
        '<div class="card-title">Hypothesis summary</div>'
        f'{_hypothesis_summary(response)}'
        '</div>'
        '</div>'
        '<div class="card">'
        '<div class="card-title">Decision drivers</div>'
        '<div class="driver-grid">'
        '<div class="driver-col mal"><h4>Toward malicious</h4>'
        f'{_list_items(malicious, empty="No malicious drivers listed.")}'
        '</div>'
        '<div class="driver-col ben"><h4>Toward benign</h4>'
        f'{_list_items(benign, empty="No benign drivers listed.")}'
        '</div>'
        '</div>'
        '</div>'
        f'<!-- confidence display: {_html(confidence_display)} -->'
    )


def _pivot_text(pivot: Any) -> str:
    if isinstance(pivot, dict):
        source = _clean_text(pivot.get("log_source"), "source")
        fields = pivot.get("key_fields", [])
        if isinstance(fields, list):
            fields_text = ", ".join(str(field) for field in fields)
        else:
            fields_text = str(fields)
        return f"{source}: {fields_text}"
    return str(pivot)


def _render_hypotheses(response: Dict[str, Any]) -> str:
    hypotheses = [_as_dict(item) for item in _as_list(response.get("competing_hypotheses"))]
    if not hypotheses:
        return '<div class="card"><p class="empty">No competing hypotheses available.</p></div>'
    cards = []
    counts = {"benign": 0, "adversary": 0}
    for item in hypotheses:
        hyp_type = _clean_text(item.get("hypothesis_type"), "unknown").lower()
        if hyp_type == "benign":
            counts["benign"] += 1
            label = f"Benign {counts['benign']}"
            num_class = "ben2"
            title_class = "ben2"
        elif hyp_type == "adversary":
            counts["adversary"] += 1
            label = f"Adversary {counts['adversary']}"
            num_class = "adv"
            title_class = "adv"
        else:
            label = "Unknown"
            num_class = "unk"
            title_class = "unk"
        pivots = [_pivot_text(pivot) for pivot in _as_list(item.get("best_pivots"))]
        cards.append(
            '<div class="hyp-card">'
            '<div class="hyp-card-header" data-hyp-toggle>'
            f'<span class="hyp-num {num_class}">{_html(label)}</span>'
            f'<span class="hyp-card-title {title_class}">{_html(_clean_text(item.get("hypothesis")))}</span>'
            '<span class="hyp-chevron">v</span>'
            '</div>'
            '<div class="hyp-card-body">'
            '<div class="hyp-section-title sup">Evidence support</div>'
            f'{_list_items(_as_list(item.get("evidence_support")), empty="No supporting evidence listed.")}'
            '<div class="hyp-section-title gap">Evidence gaps</div>'
            f'{_list_items(_as_list(item.get("evidence_gaps")), empty="No evidence gaps listed.")}'
            '<div class="hyp-section-title piv">Best pivots</div>'
            f'<div class="pivot-block">{_html(" | ".join(pivots) if pivots else "No pivots provided.")}</div>'
            '</div>'
            '</div>'
        )
    return "".join(cards)


def _action_count(actions: List[str] | Dict[str, List[str]]) -> int:
    if isinstance(actions, dict):
        return sum(len(items) for items in actions.values())
    return len(actions)


def _render_query_results(response: Dict[str, Any]) -> str:
    section = _as_dict(response.get("query_result_section"))
    summary = _as_dict(section.get("summary"))
    queries = _as_list(section.get("queries"))
    metrics = "".join(
        [
            _metric("Attempted", summary.get("attempted", 0)),
            _metric("Executed", summary.get("executed", 0)),
            _metric("Denied", summary.get("denied", 0)),
            _metric("Failed", summary.get("failed", 0)),
            _metric("Skipped", summary.get("skipped", 0)),
        ]
    )
    rows = []
    for index, raw_item in enumerate(queries, 1):
        item = _as_dict(raw_item)
        status = _clean_text(item.get("status"))
        query = _clean_text(item.get("query"), "")
        ref = _clean_text(item.get("search_reference", item.get("search_id", "")), "n/a")
        result_count = _clean_text(item.get("result_count", 0), "0")
        hyp_index = item.get("hypothesis_index")
        hyp_label = str(hyp_index + 1) if isinstance(hyp_index, int) else "n/a"
        status_class = "ben2" if status.lower() in ("executed", "success") else "adv"
        title_class = "ben2" if status_class == "ben2" else "adv"
        message = _clean_text(item.get("message"), "")
        message_block = (
            '<div class="hyp-section-title gap">Message</div>'
            f'<p class="summary-spaced">{_html(message)}</p>'
            if message
            else ""
        )
        rows.append(
            '<div class="hyp-card">'
            '<div class="hyp-card-header" data-hyp-toggle>'
            f'<span class="hyp-num {status_class}">Query {index}</span>'
            f'<span class="hyp-card-title {title_class}">{_html(status)}</span>'
            '<span class="hyp-chevron">v</span>'
            '</div>'
            '<div class="hyp-card-body">'
            '<div class="hyp-section-title piv">SPL</div>'
            f'<div class="pivot-block">{_html(query or "No query text recorded.")}</div>'
            '<div class="hyp-section-title sup">Result summary</div>'
            '<div class="ev-grid">'
            '<div class="ev-row">'
            '<span class="ev-key">Hypothesis</span>'
            f'<span class="ev-val">{_html(hyp_label)}</span>'
            '</div>'
            '<div class="ev-row">'
            '<span class="ev-key">Result count</span>'
            f'<span class="ev-val">{_html(result_count)}</span>'
            '</div>'
            '<div class="ev-row">'
            '<span class="ev-key">Reference</span>'
            f'<span class="ev-val">{_html(ref)}</span>'
            '</div>'
            '</div>'
            f'{message_block}'
            '</div>'
            '</div>'
        )
    return f'<div class="metrics">{metrics}</div><div class="card">{"".join(rows) or "<p class=\"empty\">No query attempts recorded.</p>"}</div>'


def _render_interpretation(response: Dict[str, Any]) -> str:
    items = _as_list(response.get("query_result_interpretation"))
    cards = []
    for raw_item in items:
        item = _as_dict(raw_item)
        idx = item.get("hypothesis_index")
        hyp_label = str(idx + 1) if isinstance(idx, int) else "n/a"
        detail_rows = _detail_grid(
            [
                ("Assessment", item.get("assessment")),
                ("Confidence movement", item.get("confidence_delta")),
            ]
        )
        cards.append(
            '<div class="card">'
            f'<div class="card-title">Hypothesis {_html(hyp_label)}</div>'
            f'{detail_rows}'
            f'<p class="summary-spaced">{_html(_clean_text(item.get("rationale"), "No rationale provided."))}</p>'
            '<div class="driver-grid">'
            '<div class="driver-col ben"><h4>Key observations</h4>'
            f'{_list_items(_as_list(item.get("key_observations")), empty="No key observations listed.")}'
            '</div>'
            '<div class="driver-col mal"><h4>Remaining gaps</h4>'
            f'{_list_items(_as_list(item.get("remaining_gaps")), empty="No remaining gaps listed.")}'
            '</div>'
            '</div>'
            '</div>'
        )
    return "".join(cards)


def _severity_for_score(score: float) -> Tuple[str, str]:
    if score >= 0.8:
        return "High", "pill-hi"
    if score >= 0.5:
        return "Medium", "pill-med"
    return "Low", "pill-lo"


def _render_ttps(scored_ttps: List[Dict[str, Any]]) -> str:
    if not scored_ttps:
        return '<div class="card"><p class="empty">No TTPs scored.</p></div>'
    rows = []
    for ttp in sorted(scored_ttps, key=_score_value, reverse=True):
        score = _score_value(ttp)
        label, pill_class = _severity_for_score(score)
        rows.append(
            '<div class="ttp-row">'
            f'<span class="ttp-id">{_html(_clean_text(ttp.get("ttp_id"), "unknown"))}</span>'
            f'<span class="ttp-name">{_html(_clean_text(ttp.get("ttp_name"), "unknown"))}</span>'
            f'<span class="ttp-pill {pill_class}">{_html(label)}</span>'
            '<div class="ttp-bar-bg">'
            f'<div class="ttp-bar" style="width:{int(score * 100)}%;background:#{"ef4444" if score >= 0.8 else "f59e0b" if score >= 0.5 else "475569"};"></div>'
            '</div>'
            f'<span class="ttp-score">{score:.2f}</span>'
            '</div>'
        )
    return '<div class="card"><div class="card-title">MITRE ATT&CK - scored TTPs</div>' + "".join(rows) + "</div>"


def _render_iocs(response: Dict[str, Any]) -> str:
    iocs = _as_dict(response.get("ioc_extraction"))
    cards = []
    for key, label in _IOC_FIELDS:
        values = [str(value).strip() for value in _as_list(iocs.get(key)) if str(value).strip()]
        if not values:
            continue
        cards.append(
            '<div class="ioc-item">'
            f'<div class="ioc-type">{_html(label)}</div>'
            + "".join(f'<span class="ioc-val">{_html(value)}</span>' for value in values)
            + "</div>"
        )
    if not cards:
        return '<div class="card"><p class="empty">No IOCs extracted.</p></div>'
    return '<div class="card"><div class="card-title">Indicators of compromise</div><div class="ioc-grid">' + "".join(cards) + "</div></div>"


def _evidence_pairs(alert_data: Dict[str, Any]) -> List[Tuple[str, str, bool]]:
    pairs: List[Tuple[str, str, bool]] = []
    seen_labels: set[str] = set()
    for key, label in _EVIDENCE_KEYS:
        value = alert_data.get(key)
        if value is None or label in seen_labels:
            continue
        if isinstance(value, (dict, list)):
            continue
        text = str(value).strip()
        if not text:
            continue
        seen_labels.add(label)
        pairs.append((label, text, "error" in label.lower() or "denied" in text.lower()))
    tags = _as_dict(alert_data.get("tags"))
    for key, value in tags.items():
        pairs.append((f"Tag: {key}", str(value), False))
    return pairs


def _render_evidence(response: Dict[str, Any], alert_data: Dict[str, Any]) -> str:
    pairs = _evidence_pairs(alert_data)
    raw_rows = "".join(
        '<div class="ev-row">'
        f'<span class="ev-key">{_html(label)}</span>'
        f'<span class="ev-val{" danger" if danger else ""}">{_html(value)}</span>'
        '</div>'
        for label, value, danger in pairs
    )
    evi = _as_dict(response.get("evidence_vs_inference"))
    if not raw_rows:
        raw_rows = '<p class="empty">No raw alert fields available.</p>'
    return (
        '<div class="card"><div class="card-title">Raw evidence fields</div>'
        f'<div class="ev-grid">{raw_rows}</div></div>'
        '<div class="two-col">'
        '<div class="card"><div class="card-title">Evidence facts</div>'
        f'{_list_items(_as_list(evi.get("evidence")), empty="No direct evidence listed.")}'
        '</div>'
        '<div class="card"><div class="card-title">Inferences</div>'
        f'{_list_items(_as_list(evi.get("inferences")), empty="No inferences listed.")}'
        '</div></div>'
    )


def _render_missing_context(response: Dict[str, Any]) -> str:
    gaps: List[str] = []
    for item in _as_list(response.get("competing_hypotheses")):
        for gap in _as_list(_as_dict(item).get("evidence_gaps")):
            text = str(gap).strip()
            if text and text not in gaps:
                gaps.append(text)
    if not gaps:
        return ""
    return (
        '<div class="missing">'
        '<div class="card-title">Missing context - required to close</div>'
        f'{_list_items(gaps[:8], empty="No missing context listed.")}'
        '</div>'
    )


def _render_servicenow(response: Dict[str, Any]) -> str:
    section = _as_dict(response.get("servicenow_section"))
    draft = _as_dict(section.get("draft"))
    create = _as_dict(section.get("create"))
    approval = _as_dict(create.get("approval"))
    create_details = _detail_grid(
        [
            ("Status", create.get("status")),
            ("Incident", _clean_text(create.get("number"), "n/a")),
            ("Approved by", _clean_text(approval.get("approved_by"), "n/a")),
        ]
    )
    return (
        '<div class="two-col">'
        '<div class="card"><div class="card-title">Draft</div>'
        f'{_detail_grid([("Status", draft.get("status"))])}'
        f'<p class="summary-spaced">{_html(_clean_text(draft.get("message"), ""))}</p>'
        '</div>'
        '<div class="card"><div class="card-title">Create</div>'
        f'{create_details}'
        f'<p class="summary-spaced">{_html(_clean_text(create.get("message"), ""))}</p>'
        '</div>'
        '</div>'
    )


def _render_poc(response: Dict[str, Any]) -> str:
    return (
        '<div class="missing">'
        '<div class="card-title">Raw model output</div>'
        '<p>Structured JSON validation did not succeed. Review this output manually.</p>'
        f'<p><strong>Fallback reason:</strong> {_html(_clean_text(response.get("poc_fallback_reason"), "unknown"))}</p>'
        f'<div class="pivot-block">{_html(_clean_text(response.get("raw_response"), ""))}</div>'
        '</div>'
    )


def _header_title(alert_data: Dict[str, Any]) -> str:
    finding = _first_value(alert_data, ("finding_type", "findingType", "search_name", "title"))
    if finding:
        return f"Alert Reconciliation - {finding}"
    return "Alert Reconciliation"


def _header_meta(alert_data: Dict[str, Any]) -> str:
    parts = [
        _first_value(alert_data, ("instance_id", "host", "hostname")),
        _first_value(alert_data, ("role", "principal", "principalName")),
        _first_value(alert_data, ("first_seen", "firstSeen", "alert_time")),
        _first_value(alert_data, ("account_id", "account")),
    ]
    labels = ["EC2", "Role", "Time", "Account"]
    rendered = [f"{label}: {value}" for label, value in zip(labels, parts) if value]
    return " &nbsp;&middot;&nbsp; ".join(_html(item) for item in rendered)


def _build_metrics(alert_data: Dict[str, Any], response: Dict[str, Any], scored_ttps: List[Dict[str, Any]]) -> str:
    ar = _as_dict(response.get("alert_reconciliation"))
    confidence_display, _, _ = _confidence_display(ar.get("confidence"))
    window_value, window_sub = _window_metric(alert_data)
    credential_count = _count_matching_strings(alert_data, r"\bASIA[A-Z0-9]+\b")
    source_ips = set(_as_list(_as_dict(response.get("ioc_extraction")).get("ip_addresses")))
    source_ip = _first_value(alert_data, ("source_ip", "sourceIPAddress"))
    if source_ip:
        source_ips.add(source_ip)
    error = _first_value(alert_data, ("errorCode", "error_code", "api_result"), "unknown")
    api_call = _first_value(alert_data, ("eventName", "event_name", "api_call"), "")
    return "".join(
        [
            _metric("Confidence", confidence_display, _clean_text(ar.get("verdict"), "")),
            _metric("Window", window_value, window_sub),
            _metric("Credentials", credential_count or "unknown", "ASIA-prefix (STS temp)" if credential_count else "Not provided"),
            _metric("Source IPs", len(source_ips) if source_ips else "unknown", ", ".join(sorted(source_ips)) if source_ips else "Not provided"),
            _metric("API result", error, api_call, danger=error.lower() not in ("", "unknown", "success")),
            _metric("TTPs", len(scored_ttps), "Scored techniques"),
        ]
    )


def generate_html_report(
    alert_text: str,
    llm_response: Dict[str, Any],
    scored_ttps: List[Dict[str, Any]],
) -> str:
    """Generate a standalone static HTML dashboard from an analysis result."""
    alert_data = _parse_alert(alert_text)
    response = _as_dict(llm_response)
    ar = _as_dict(response.get("alert_reconciliation"))
    verdict = _clean_text(ar.get("verdict"))
    actions = _actions_from_response(response)
    query_section = _as_dict(response.get("query_result_section"))
    interpretation = _as_list(response.get("query_result_interpretation"))
    servicenow = _as_dict(response.get("servicenow_section"))

    tabs = [_tab_button("verdict", "Verdict", active=True)]
    sections = [_section("verdict", _render_verdict(response), active=True)]

    if response.get("poc_unstructured_output"):
        tabs.append(_tab_button("raw-output", "Raw Output"))
        sections.append(_section("raw-output", _render_poc(response)))
    if _as_list(response.get("competing_hypotheses")):
        tabs.append(_tab_button("hypotheses", "Hypotheses"))
        sections.append(_section("hypotheses", _render_hypotheses(response)))
    if _action_count(actions) > 0:
        tabs.append(_tab_button("actions", "Actions"))
        sections.append(_section("actions", _render_actions(actions)))
    if query_section:
        tabs.append(_tab_button("queries", "Query Results"))
        sections.append(_section("queries", _render_query_results(response)))
    if interpretation:
        tabs.append(_tab_button("interpretation", "Interpretation"))
        sections.append(_section("interpretation", _render_interpretation(response)))
    if scored_ttps:
        tabs.append(_tab_button("ttps", "TTPs"))
        sections.append(_section("ttps", _render_ttps(scored_ttps)))
    if any(_as_list(_as_dict(response.get("ioc_extraction")).get(key)) for key, _ in _IOC_FIELDS):
        tabs.append(_tab_button("iocs", "IOCs"))
        sections.append(_section("iocs", _render_iocs(response)))
    if alert_data or response.get("evidence_vs_inference"):
        tabs.append(_tab_button("evidence", "Evidence"))
        sections.append(_section("evidence", _render_evidence(response, alert_data) + _render_missing_context(response)))
    if servicenow:
        tabs.append(_tab_button("servicenow", "ServiceNow"))
        sections.append(_section("servicenow", _render_servicenow(response)))

    metrics = _build_metrics(alert_data, response, scored_ttps)
    header_meta = _header_meta(alert_data)

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Alert Reconciliation</title>
<style>
* {{ box-sizing: border-box; margin: 0; padding: 0; }}
html {{ scrollbar-gutter: stable; }}
body {{ overflow-y: scroll; font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif; background: #0f1117; color: #e2e8f0; font-size: 14px; line-height: 1.5; }}
.container {{ max-width: 1100px; margin: 0 auto; padding: 24px; }}
.header {{ display: flex; align-items: flex-start; justify-content: space-between; margin-bottom: 24px; flex-wrap: wrap; gap: 12px; }}
.header h1 {{ font-size: 18px; font-weight: 600; color: #f1f5f9; }}
.header p {{ font-size: 13px; color: #64748b; margin-top: 4px; }}
.badges {{ display: flex; gap: 8px; flex-wrap: wrap; align-items: center; }}
.badge {{ padding: 4px 12px; border-radius: 9999px; font-size: 12px; font-weight: 600; }}
.badge-red {{ background: #2d1b1b; color: #f87171; border: 1px solid #7f1d1d; }}
.badge-amber {{ background: #2d2010; color: #fbbf24; border: 1px solid #78350f; }}
.badge-blue {{ background: #0f1e3d; color: #60a5fa; border: 1px solid #1e3a8a; }}
.metrics {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(140px, 1fr)); gap: 12px; margin-bottom: 24px; }}
.metric {{ background: #1a1f2e; border: 1px solid #2d3748; border-radius: 10px; padding: 14px 16px; }}
.metric-label {{ font-size: 11px; color: #64748b; text-transform: uppercase; letter-spacing: 0.05em; margin-bottom: 6px; }}
.metric-value {{ font-size: 26px; font-weight: 700; color: #f1f5f9; }}
.metric-sub {{ font-size: 11px; color: #475569; margin-top: 2px; }}
.tabs {{ display: flex; gap: 0; border-bottom: 1px solid #2d3748; margin-bottom: 20px; overflow-x: auto; overflow-y: hidden; scrollbar-width: none; -ms-overflow-style: none; }}
.tabs::-webkit-scrollbar {{ display: none; }}
.tab {{ padding: 10px 16px; font-size: 13px; cursor: pointer; background: none; border: none; color: #64748b; border-bottom: 2px solid transparent; margin-bottom: -1px; font-weight: 500; white-space: nowrap; transition: color 0.15s; }}
.tab:hover {{ color: #cbd5e1; }}
.tab.active {{ color: #f1f5f9; border-bottom-color: #6366f1; }}
.section {{ display: none; }}
.section.active {{ display: block; }}
.card {{ background: #1a1f2e; border: 1px solid #2d3748; border-radius: 10px; padding: 18px 20px; margin-bottom: 14px; }}
.card-title {{ font-size: 11px; font-weight: 600; color: #64748b; text-transform: uppercase; letter-spacing: 0.06em; margin-bottom: 14px; }}
.detail-grid {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(180px, 1fr)); gap: 8px 12px; margin-bottom: 12px; }}
.detail-row {{ background: #111827; border: 1px solid #2d3748; border-radius: 8px; padding: 9px 12px; }}
.detail-label {{ display: block; font-size: 10px; color: #475569; text-transform: uppercase; letter-spacing: 0.06em; margin-bottom: 3px; }}
.detail-value {{ display: block; font-size: 13px; color: #e2e8f0; font-weight: 600; }}
.two-col {{ display: grid; grid-template-columns: 1fr 1fr; gap: 14px; margin-bottom: 14px; }}
.conf-row {{ display: flex; align-items: center; gap: 10px; margin-bottom: 8px; }}
.conf-label {{ font-size: 12px; color: #64748b; min-width: 80px; }}
.bar-bg {{ flex: 1; height: 6px; background: #2d3748; border-radius: 3px; overflow: hidden; }}
.bar-fill {{ height: 6px; border-radius: 3px; }}
.conf-pct {{ font-size: 13px; font-weight: 600; color: #f1f5f9; min-width: 36px; text-align: right; }}
.summary-spaced {{ font-size:13px;color:#64748b;margin-top:12px;line-height:1.7; }}
.hyp {{ border-left: 3px solid #334155; padding: 10px 14px; margin-bottom: 10px; border-radius: 0 6px 6px 0; background: #111827; }}
.hyp.mal {{ border-left-color: #ef4444; }}
.hyp.ben {{ border-left-color: #22c55e; }}
.hyp-title {{ font-size: 13px; font-weight: 600; margin-bottom: 4px; }}
.hyp.mal .hyp-title {{ color: #fca5a5; }}
.hyp.ben .hyp-title {{ color: #86efac; }}
.hyp-body {{ font-size: 13px; color: #64748b; line-height: 1.6; }}
.driver-grid {{ display: grid; grid-template-columns: 1fr 1fr; gap: 16px; }}
.driver-col h4 {{ font-size: 12px; font-weight: 600; margin-bottom: 8px; }}
.driver-col.mal h4 {{ color: #f87171; }}
.driver-col.ben h4 {{ color: #4ade80; }}
.clean-list {{ list-style: none; padding: 0; }}
.clean-list li {{ font-size: 13px; color: #94a3b8; padding: 4px 0; border-bottom: 1px solid #1e2130; display: flex; gap: 8px; }}
.clean-list li::before {{ content: '-'; color: #334155; flex-shrink: 0; }}
.ttp-row {{ display: flex; align-items: center; gap: 10px; padding: 10px 0; border-bottom: 1px solid #1e2130; }}
.ttp-row:last-child {{ border-bottom: none; }}
.ttp-id {{ font-family: 'SF Mono', 'Fira Code', monospace; font-size: 12px; color: #818cf8; min-width: 96px; }}
.ttp-name {{ font-size: 13px; color: #cbd5e1; flex: 1; }}
.ttp-pill {{ font-size: 11px; padding: 2px 8px; border-radius: 9999px; font-weight: 600; }}
.pill-hi {{ background: #2d1b1b; color: #f87171; }}
.pill-med {{ background: #2d2010; color: #fbbf24; }}
.pill-lo {{ background: #1e2130; color: #64748b; }}
.ttp-bar-bg {{ width: 80px; height: 5px; background: #2d3748; border-radius: 3px; overflow: hidden; }}
.ttp-bar {{ height: 5px; border-radius: 3px; }}
.ttp-score {{ font-size: 12px; font-weight: 700; min-width: 32px; text-align: right; }}
.ioc-grid {{ display: grid; grid-template-columns: 1fr 1fr; gap: 10px; }}
.ioc-item {{ background: #111827; border: 1px solid #2d3748; border-radius: 8px; padding: 12px 14px; }}
.ioc-type {{ font-size: 11px; color: #475569; text-transform: uppercase; letter-spacing: 0.05em; margin-bottom: 6px; }}
.ioc-val {{ font-family: 'SF Mono', 'Fira Code', monospace; font-size: 12px; color: #94a3b8; display: block; margin-bottom: 3px; word-break: break-all; }}
.ev-grid {{ display: grid; grid-template-columns: 1fr 1fr; gap: 0; }}
.ev-row {{ display: flex; gap: 10px; padding: 7px 0; border-bottom: 1px solid #1e2130; }}
.ev-key {{ font-size: 12px; color: #475569; min-width: 120px; flex-shrink: 0; }}
.ev-val {{ font-family: 'SF Mono', 'Fira Code', monospace; font-size: 12px; color: #94a3b8; word-break: break-all; }}
.ev-val.danger {{ color: #f87171; }}
.missing {{ border: 1px solid #78350f; background: #1c1208; border-radius: 10px; padding: 16px 20px; margin-top: 14px; }}
.missing .card-title {{ color: #d97706; }}
.action-group {{ margin-bottom: 16px; }}
.action-group-title {{ font-size: 11px; font-weight: 700; text-transform: uppercase; letter-spacing: 0.06em; margin-bottom: 8px; padding: 4px 10px; border-radius: 6px; display: inline-block; }}
.ag-immediate {{ background: #2d1b1b; color: #f87171; }}
.ag-short {{ background: #2d2010; color: #fbbf24; }}
.ag-long {{ background: #0f1e3d; color: #60a5fa; }}
.action-item {{ display: flex; gap: 10px; padding: 8px 0; border-bottom: 1px solid #1e2130; align-items: flex-start; }}
.action-dot {{ width: 7px; height: 7px; border-radius: 50%; flex-shrink: 0; margin-top: 5px; }}
.dot-red {{ background: #ef4444; }}
.dot-amber {{ background: #f59e0b; }}
.dot-blue {{ background: #60a5fa; }}
.action-text {{ font-size: 13px; color: #94a3b8; line-height: 1.6; }}
.hyp-card {{ background: #1a1f2e; border: 1px solid #2d3748; border-radius: 10px; margin-bottom: 12px; overflow: hidden; }}
.hyp-card-header {{ display: flex; align-items: center; gap: 12px; padding: 14px 18px; cursor: pointer; user-select: none; }}
.hyp-card-header:hover {{ background: #202536; }}
.hyp-num {{ font-size: 11px; font-weight: 700; padding: 3px 8px; border-radius: 9999px; flex-shrink: 0; }}
.hyp-num.adv {{ background: #2d1b1b; color: #f87171; }}
.hyp-num.ben2 {{ background: #0f2d1b; color: #4ade80; }}
.hyp-card-title {{ font-size: 14px; font-weight: 500; flex: 1; }}
.hyp-card-title.adv {{ color: #fca5a5; }}
.hyp-card-title.ben2 {{ color: #86efac; }}
.hyp-chevron {{ font-size: 12px; color: #475569; transition: transform 0.2s; }}
.hyp-chevron.open {{ transform: rotate(180deg); }}
.hyp-card-body {{ display: none; padding: 0 18px 16px; border-top: 1px solid #1e2130; }}
.hyp-card-body.open {{ display: block; }}
.hyp-section-title {{ font-size: 11px; font-weight: 600; text-transform: uppercase; letter-spacing: 0.05em; margin: 12px 0 6px; }}
.hyp-section-title.sup {{ color: #4ade80; }}
.hyp-section-title.gap {{ color: #f87171; }}
.hyp-section-title.piv {{ color: #818cf8; }}
.pivot-block {{ background: #111827; border-radius: 6px; padding: 8px 12px; margin-top: 6px; font-family: 'SF Mono', 'Fira Code', monospace; font-size: 11px; color: #818cf8; line-height: 1.8; }}
.empty {{ font-size: 13px; color: #64748b; }}
pre {{ white-space: pre-wrap; word-break: break-word; }}
@media (max-width: 600px) {{ .two-col, .driver-grid, .ioc-grid, .ev-grid, .detail-grid {{ grid-template-columns: 1fr; }} }}
</style>
</head>
<body>
<div class="container">
  <div class="header">
    <div>
      <h1>{_html(_header_title(alert_data))}</h1>
      <p>{header_meta}</p>
    </div>
    <div class="badges">
      {_severity_badge(alert_data)}
      <span class="badge badge-amber">{_html(verdict)}</span>
      {_source_badge(alert_data)}
    </div>
  </div>
  <div class="metrics">{metrics}</div>
  <div class="tabs">{"".join(tabs)}</div>
  {"".join(sections)}
</div>
<script>
function showTab(name, el) {{
  document.querySelectorAll('.tab').forEach(t => t.classList.remove('active'));
  document.querySelectorAll('.section').forEach(s => s.classList.remove('active'));
  document.getElementById(name).classList.add('active');
  el.classList.add('active');
}}
document.querySelectorAll('.tab').forEach(tab => {{
  tab.addEventListener('click', () => showTab(tab.dataset.tab, tab));
}});
document.querySelectorAll('[data-hyp-toggle]').forEach(header => {{
  header.addEventListener('click', () => {{
    const body = header.nextElementSibling;
    const chevron = header.querySelector('.hyp-chevron');
    const isOpen = body.classList.contains('open');
    body.classList.toggle('open', !isOpen);
    chevron.classList.toggle('open', !isOpen);
  }});
}});
</script>
</body>
</html>
"""
