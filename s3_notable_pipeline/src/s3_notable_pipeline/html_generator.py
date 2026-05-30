"""Generate deterministic static HTML reports for AWS notable analysis."""

from __future__ import annotations

from html import escape
from typing import Any


def _text(value: Any, default: str = "unknown") -> str:
    text = str(value if value is not None else "").strip()
    return text or default


def _list_items(items: Any) -> str:
    if not isinstance(items, list) or not items:
        return '<p class="empty">No items available.</p>'
    return "<ul>" + "".join(f"<li>{escape(_text(item))}</li>" for item in items) + "</ul>"


def generate_html_report(
    alert_text: str,
    llm_response: dict[str, Any],
    scored_ttps: list[dict[str, Any]],
    markdown: str,
) -> str:
    """Render a static HTML companion report.

    The HTML report is deterministic and side-effect free. It reuses the
    validated analysis object and escaped markdown text; it does not call the
    model or reinterpret findings.
    """

    reconciliation = llm_response.get("alert_reconciliation")
    reconciliation = reconciliation if isinstance(reconciliation, dict) else {}
    verdict = _text(reconciliation.get("verdict"))
    confidence = _text(reconciliation.get("confidence"))
    summary = _text(reconciliation.get("one_sentence_summary"))
    ttp_rows = "".join(
        "<tr>"
        f"<td>{escape(_text(ttp.get('ttp_id')))}</td>"
        f"<td>{escape(_text(ttp.get('ttp_name')))}</td>"
        f"<td>{escape(_text(ttp.get('score', ttp.get('confidence_score', 0))))}</td>"
        "</tr>"
        for ttp in scored_ttps
    )
    if not ttp_rows:
        ttp_rows = '<tr><td colspan="3">No TTPs scored</td></tr>'

    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <title>Notable Analysis Report</title>
  <style>
    body {{ font-family: Arial, sans-serif; margin: 24px; background: #0f172a; color: #e2e8f0; }}
    .card {{ background: #111827; border: 1px solid #334155; border-radius: 8px; padding: 16px; margin-bottom: 16px; }}
    .label {{ color: #93c5fd; font-weight: bold; }}
    pre {{ white-space: pre-wrap; background: #020617; border: 1px solid #334155; padding: 12px; overflow-x: auto; }}
    table {{ border-collapse: collapse; width: 100%; }}
    th, td {{ border-bottom: 1px solid #334155; padding: 8px; text-align: left; }}
    th {{ color: #93c5fd; }}
    .empty {{ color: #94a3b8; }}
  </style>
</head>
<body>
  <h1>Notable Analysis Report</h1>
  <section class="card">
    <h2>Verdict</h2>
    <p><span class="label">Verdict:</span> {escape(verdict)}</p>
    <p><span class="label">Confidence:</span> {escape(confidence)}</p>
    <p><span class="label">Summary:</span> {escape(summary)}</p>
  </section>
  <section class="card">
    <h2>Decision Drivers</h2>
    {_list_items(reconciliation.get("decision_drivers"))}
  </section>
  <section class="card">
    <h2>Scored TTPs</h2>
    <table>
      <thead><tr><th>ID</th><th>Name</th><th>Score</th></tr></thead>
      <tbody>{ttp_rows}</tbody>
    </table>
  </section>
  <section class="card">
    <h2>Markdown Report</h2>
    <pre>{escape(markdown)}</pre>
  </section>
  <section class="card">
    <h2>Alert Input</h2>
    <pre>{escape(alert_text)}</pre>
  </section>
</body>
</html>
"""
