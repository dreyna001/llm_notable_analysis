"""Run the analyst portal locally with in-memory fake data for UI preview.

Local development only. By default injects proxy auth headers on loopback so a
normal browser can load pages without nginx. Do not use in production.

Cases 1-5 are built through ``preview_synthetic_pipeline`` (real normalization,
query enrichment, and ``build_case_archive_record``). Remaining cases are
lightweight list-pagination fillers.

Auth verification (no running server required)::

    python scripts/preview_portal_ui.py --verify-auth

To exercise the same header contract the Vite dev proxy uses, start the preview
API without auto-injection and rely on ``vite.config.ts`` proxy headers::

    python scripts/preview_portal_ui.py --no-inject-auth

Optional OpenAI-backed chat synthesis for UI testing:

- Set ``OPENAI_API_KEY`` or ``PORTAL_PREVIEW_OPENAI_API_KEY`` in the environment, or
- Copy ``config.portal-preview.env.example`` to ``config.portal-preview.env`` and
  fill in your key (that file is gitignored).
"""

from __future__ import annotations

import argparse
import json
import os
import urllib.error
import urllib.request
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

_SRC = Path(__file__).resolve().parents[1] / "src"
_SCRIPTS = Path(__file__).resolve().parent
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))

from llm_notable_analysis_onprem_systemd.onprem_service.case_store import (  # noqa: E402
    build_case_archive_record,
)
from llm_notable_analysis_onprem_systemd.onprem_service.config import Config  # noqa: E402
from llm_notable_analysis_onprem_systemd.onprem_service.portal_app import (  # noqa: E402
    build_portal_app,
)
from preview_synthetic_pipeline import (  # noqa: E402
    build_synthetic_preview_record,
    preview_scenario_count,
)

_PREVIEW_HOST = "127.0.0.1"
_PREVIEW_PORT = 8765
_PROXY_SECRET = "portal-secret"
_TRUSTED_USER = "dev-preview@local"
_TRUSTED_USER_HEADER = "X-Forwarded-User"
_PROXY_SECRET_HEADER = "X-Notable-Portal-Proxy-Secret"
_OPENAI_CHAT_URL = "https://api.openai.com/v1/chat/completions"
_DEFAULT_OPENAI_MODEL = "gpt-4.1-mini"
# UI requests limit=50; 55 cases yields two pages (has_more on first page).
_PREVIEW_CASE_COUNT = 55
_REPO_ROOT = Path(__file__).resolve().parents[1]


def _parse_env_line(line: str) -> tuple[str, str] | None:
    stripped = line.strip()
    if not stripped or stripped.startswith("#"):
        return None
    if stripped.startswith("export "):
        stripped = stripped[len("export ") :].strip()
    if "=" not in stripped:
        return None
    key, value = stripped.split("=", 1)
    key = key.strip()
    if not key:
        return None
    value = value.strip()
    if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
        value = value[1:-1]
    return key, value


def load_optional_preview_env() -> Path | None:
    """Load optional preview env file without overriding existing os.environ."""
    candidates: list[Path] = []
    override = os.environ.get("PORTAL_PREVIEW_ENV", "").strip()
    if override:
        candidates.append(Path(override))
    candidates.append(_REPO_ROOT / "config.portal-preview.env")
    for path in candidates:
        if not path.is_file():
            continue
        for raw_line in path.read_text(encoding="utf-8").splitlines():
            parsed = _parse_env_line(raw_line)
            if parsed is None:
                continue
            key, value = parsed
            os.environ.setdefault(key, value)
        return path
    return None


def resolve_openai_preview_llm() -> dict[str, str] | None:
    """Return OpenAI chat settings when a preview API key is configured."""
    api_key = (
        os.environ.get("PORTAL_PREVIEW_OPENAI_API_KEY")
        or os.environ.get("OPENAI_API_KEY")
        or ""
    ).strip()
    if not api_key:
        return None
    model = (
        os.environ.get("PORTAL_PREVIEW_OPENAI_MODEL") or _DEFAULT_OPENAI_MODEL
    ).strip()
    api_url = (
        os.environ.get("PORTAL_PREVIEW_OPENAI_API_URL") or _OPENAI_CHAT_URL
    ).strip()
    return {
        "LLM_API_URL": api_url,
        "LLM_API_TOKEN": api_key,
        "LLM_MODEL_NAME": model or _DEFAULT_OPENAI_MODEL,
    }


def preview_chat_mode_label() -> str:
    """Human-readable label for startup logs."""
    if resolve_openai_preview_llm() is not None:
        model = (
            os.environ.get("PORTAL_PREVIEW_OPENAI_MODEL") or _DEFAULT_OPENAI_MODEL
        ).strip()
        return f"OpenAI ({model or _DEFAULT_OPENAI_MODEL})"
    return "stub (set OPENAI_API_KEY or config.portal-preview.env for live chat)"


class _FakeResult:
    def __init__(self, rows=None, row=None):
        self.rows = rows or []
        self.row = row

    def fetchall(self):
        return self.rows

    def fetchone(self):
        return self.row


class _FakeConnection:
    def __init__(
        self,
        *,
        summary_rows: list[tuple],
        details_by_case_id: dict[str, tuple],
        chunk_rows: list[tuple],
        ready: bool = True,
    ):
        self.summary_rows = summary_rows
        self.details_by_case_id = details_by_case_id
        self.chunk_rows = chunk_rows
        self.ready = ready

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, traceback):
        return False

    def execute(self, sql, params=None):
        if not self.ready and "set_config" not in sql:
            raise OSError("database unavailable")
        if "set_config" in sql:
            return _FakeResult()
        if "to_regclass" in sql:
            return _FakeResult(row=(self.ready, self.ready))
        if "case_chunks" in sql:
            rows = list(self.chunk_rows)
            if "ch.case_id = %s" in sql and params:
                case_id = str(params[1])
                rows = [row for row in rows if row[1] == case_id]
            if "ch.case_id <> %s" in sql and params:
                case_id = str(params[1])
                rows = [row for row in rows if row[1] != case_id]
            limit = int(params[-1]) if params else 1
            return _FakeResult(rows=rows[:limit], row=rows[0] if rows else None)
        if "WHERE case_id = %s" in sql:
            case_id = str((params or ("",))[0])
            return _FakeResult(row=self.details_by_case_id.get(case_id))
        if "LIMIT %s OFFSET %s" in sql and params:
            limit = int(params[-2])
            offset = max(0, int(params[-1]))
            rows = list(self.summary_rows)
            filter_params = list(params[:-2])
            param_index = 0
            if "processed_at >= %s" in sql:
                processed_from = filter_params[param_index]
                param_index += 1
                rows = [row for row in rows if row[3] >= processed_from]
            if "processed_at <= %s" in sql:
                processed_to = filter_params[param_index]
                param_index += 1
                rows = [row for row in rows if row[3] <= processed_to]
            if "verdict = %s" in sql:
                verdict = filter_params[param_index]
                param_index += 1
                rows = [row for row in rows if row[5] == verdict]
            if "search_name ILIKE %s" in sql:
                pattern = filter_params[param_index]
                needle = str(pattern)[1:-1]
                needle = (
                    needle.replace("\\%", "%")
                    .replace("\\_", "_")
                    .replace("\\\\", "\\")
                )
                rows = [
                    row
                    for row in rows
                    if row[7] and needle.lower() in str(row[7]).lower()
                ]
            return _FakeResult(rows=rows[offset : offset + limit])
        return _FakeResult(rows=self.summary_rows)


class _FakeEmbeddingModel:
    def encode(self, values, **_kwargs):
        return [[1.0] + [0.0] * 767 for _value in values]


def _minimal_analysis(*, verdict: str, confidence: str) -> dict:
    return {
        "alert_reconciliation": {
            "verdict": verdict,
            "confidence": confidence,
            "one_sentence_summary": "",
            "decision_drivers": [],
            "recommended_actions": [],
        },
        "competing_hypotheses": [],
        "evidence_vs_inference": {"evidence": [], "inferences": []},
        "ioc_extraction": {},
        "ttp_analysis": [],
    }


def _build_preview_records(config: Config):
    """Build synthetic cases for paginated UI preview."""
    base_time = datetime(2026, 6, 4, tzinfo=timezone.utc)
    verdicts = ("likely_malicious", "likely_benign", "unknown")
    search_names = (
        "Suspicious PowerShell",
        "Unusual Login Location",
        "Malware Beaconing",
        "Privilege Escalation Attempt",
        "Scheduled Task - Known Scanner",
    )
    records = []
    synthetic_count = preview_scenario_count()
    for index in range(1, _PREVIEW_CASE_COUNT + 1):
        case_id = f"case-{index}"
        processed_at = base_time - timedelta(hours=index)
        if index <= synthetic_count:
            records.append(
                build_synthetic_preview_record(
                    config=config,
                    scenario_index=index,
                    case_id=case_id,
                    finding_id=f"syn-{index:03d}",
                    source_filename=f"syn-case-{index}.json",
                    processed_at=processed_at,
                )
            )
            continue

        verdict = verdicts[index % len(verdicts)]
        confidence = f"{0.55 + (index % 40) / 100:.2f}"
        records.append(
            build_case_archive_record(
                config=config,
                case_id=case_id,
                finding_id=case_id,
                source_filename=f"{case_id}.json",
                alert_payload={
                    "notable_id": f"abc-{index:03d}",
                    "search_name": search_names[index % len(search_names)],
                },
                analysis=_minimal_analysis(verdict=verdict, confidence=confidence),
                report_md_path=f"/reports/{case_id}.md",
                report_html_path=None,
                processed_at=processed_at,
            )
        )
    records.sort(key=lambda item: (item.processed_at, item.case_id), reverse=True)
    return records


def _summary_row(record):
    return (
        record.case_id,
        record.finding_id,
        record.source_filename,
        record.processed_at,
        record.expires_at,
        record.verdict,
        record.confidence,
        record.search_name,
        record.risk_score,
        record.retrieval_status,
        record.source_completeness,
        record.report_md_path,
        record.report_html_path,
    )


def _detail_row(record):
    return (
        record.case_id,
        record.finding_id,
        record.source_filename,
        record.processed_at,
        record.expires_at,
        record.correlation_id,
        json.dumps(record.capability_snapshot),
        json.dumps(record.archive_metadata),
        json.dumps(record.alert_payload),
        json.dumps(record.analysis),
        record.case_schema_version,
        record.analysis_schema_version,
        record.verdict,
        record.confidence,
        record.search_name,
        record.risk_score,
        record.report_md_path,
        record.report_html_path,
        record.retrieval_status,
        record.backfill_status,
        record.source_completeness,
    )


def _chunk_row(record):
    analysis = record.analysis or {}
    reconciliation = analysis.get("alert_reconciliation", {})
    if not isinstance(reconciliation, dict):
        reconciliation = {}
    summary = str(reconciliation.get("one_sentence_summary") or "").strip()
    if not summary:
        summary = (
            f"{record.search_name or record.case_id}: verdict={record.verdict or 'unknown'} "
            f"confidence={record.confidence if record.confidence is not None else 'unknown'}"
        )
    text = (
        f"Case {record.case_id}. Search name: {record.search_name or 'unknown'}. "
        f"Verdict: {record.verdict or 'unknown'}. Summary: {summary}"
    )
    return (
        f"{record.case_id}:case_analysis:analysis.alert_reconciliation:0",
        record.case_id,
        "case_analysis",
        "analysis.alert_reconciliation",
        "$.alert_reconciliation",
        text,
        json.dumps({"preview_synthetic": True}),
        1.0,
    )


def _preview_config() -> Config:
    kwargs: dict[str, object] = {
        "PORTAL_ENABLED": True,
        "CASE_ARCHIVE_ENABLED": True,
        "CASE_QA_ENABLED": True,
        "CASE_QA_GLOBAL_RETRIEVAL_ENABLED": True,
        "PORTAL_BIND_HOST": _PREVIEW_HOST,
        "PORTAL_PAGE_SIZE": 50,
        "PORTAL_TRUSTED_USER_HEADER": "X-Forwarded-User",
        "PORTAL_PROXY_SECRET_HEADER": "X-Notable-Portal-Proxy-Secret",
        "PORTAL_PROXY_SECRET": _PROXY_SECRET,
        "LLM_TIMEOUT": 120,
    }
    openai_llm = resolve_openai_preview_llm()
    if openai_llm is not None:
        kwargs.update(openai_llm)
    return Config(**kwargs)


def _fake_connect_factory(records):
    summary_rows = [_summary_row(record) for record in records]
    details_by_case_id = {record.case_id: _detail_row(record) for record in records}
    chunk_rows = [_chunk_row(record) for record in records]

    def connect(_dsn: str):
        del _dsn
        return _FakeConnection(
            summary_rows=summary_rows,
            details_by_case_id=details_by_case_id,
            chunk_rows=chunk_rows,
        )

    return connect


def _preview_chat_synthesizer(question, sources):
    cases = sorted(
        {
            source.case_id
            for source in sources
            if source.case_id is not None
        }
    )
    case_text = ", ".join(cases) if cases else "no retained cases"
    return (
        f"Preview answer for: {question}. Retrieved {len(sources)} grounded "
        f"source(s) from {case_text}. In production this answer is synthesized "
        "by the configured local LLM from the retrieved archive context."
    )


def _preview_general_synthesizer(question: str) -> str:
    return (
        f"Preview general-knowledge answer for: {question}. "
        "In production this uses the configured LLM for broad technology "
        "questions when the archive has no match."
    )


def preview_auth_headers(
    *,
    user: str = _TRUSTED_USER,
    proxy_secret: str = _PROXY_SECRET,
) -> dict[str, str]:
    """Headers that mimic nginx after basic auth and proxy secret injection."""
    return {
        _TRUSTED_USER_HEADER: user,
        _PROXY_SECRET_HEADER: proxy_secret,
    }


def preview_inject_auth_enabled() -> bool:
    """Return False when preview should enforce the production auth contract."""
    raw = os.environ.get("PORTAL_PREVIEW_INJECT_AUTH", "true").strip().lower()
    return raw not in {"0", "false", "no", "off"}


def _preview_auth_check(
    name: str,
    *,
    status_code: int,
    expected: int,
    detail: str = "",
) -> tuple[str, bool, str]:
    passed = status_code == expected
    message = detail or f"expected HTTP {expected}, got {status_code}"
    return name, passed, message


def verify_preview_portal_auth() -> list[tuple[str, bool, str]]:
    """Run the portal proxy-auth contract against preview config (no live server)."""
    try:
        from fastapi.testclient import TestClient  # type: ignore
    except ImportError as exc:
        raise RuntimeError(
            "fastapi is required for --verify-auth. Install project dependencies first."
        ) from exc

    app = build_preview_app(inject_loopback_auth=False)
    client = TestClient(app)
    user_only = {_TRUSTED_USER_HEADER: _TRUSTED_USER}
    valid = preview_auth_headers()
    wrong_secret = preview_auth_headers(proxy_secret="wrong-secret")

    checks = [
        _preview_auth_check(
            "public /health without auth",
            status_code=client.get("/health").status_code,
            expected=200,
        ),
        _preview_auth_check(
            "public /ready without auth",
            status_code=client.get("/ready").status_code,
            expected=200,
        ),
        _preview_auth_check(
            "protected /api/cases without headers",
            status_code=client.get("/api/cases").status_code,
            expected=401,
        ),
        _preview_auth_check(
            "protected /api/cases with user header only",
            status_code=client.get("/api/cases", headers=user_only).status_code,
            expected=401,
        ),
        _preview_auth_check(
            "protected /api/cases with wrong proxy secret",
            status_code=client.get("/api/cases", headers=wrong_secret).status_code,
            expected=401,
        ),
        _preview_auth_check(
            "protected /api/cases with trusted proxy headers",
            status_code=client.get("/api/cases", headers=valid).status_code,
            expected=200,
        ),
    ]
    return checks


def _http_status(url: str, headers: dict[str, str] | None = None) -> int:
    request = urllib.request.Request(url, headers=headers or {}, method="GET")
    try:
        with urllib.request.urlopen(request, timeout=5) as response:
            return int(response.status)
    except urllib.error.HTTPError as exc:
        return int(exc.code)


def verify_preview_portal_auth_live(base_url: str) -> list[tuple[str, bool, str]]:
    """Hit a running preview API. Use with --no-inject-auth for a faithful check."""
    root = str(base_url or "").strip().rstrip("/")
    if not root:
        raise ValueError("base_url must be non-empty for live auth verification.")
    user_only = {_TRUSTED_USER_HEADER: _TRUSTED_USER}
    valid = preview_auth_headers()
    wrong_secret = preview_auth_headers(proxy_secret="wrong-secret")

    checks = [
        _preview_auth_check(
            "live /health without auth",
            status_code=_http_status(f"{root}/health"),
            expected=200,
        ),
        _preview_auth_check(
            "live /api/cases without headers",
            status_code=_http_status(f"{root}/api/cases"),
            expected=401,
        ),
        _preview_auth_check(
            "live /api/cases with user header only",
            status_code=_http_status(f"{root}/api/cases", user_only),
            expected=401,
        ),
        _preview_auth_check(
            "live /api/cases with wrong proxy secret",
            status_code=_http_status(f"{root}/api/cases", wrong_secret),
            expected=401,
        ),
        _preview_auth_check(
            "live /api/cases with trusted proxy headers",
            status_code=_http_status(f"{root}/api/cases", valid),
            expected=200,
        ),
    ]
    return checks


def _print_auth_checks(checks: list[tuple[str, bool, str]]) -> bool:
    all_passed = True
    for name, passed, detail in checks:
        status = "PASS" if passed else "FAIL"
        print(f"{status} {name}: {detail}")
        if not passed:
            all_passed = False
    return all_passed


def build_preview_app(*, inject_loopback_auth: bool | None = None):
    if inject_loopback_auth is None:
        inject_loopback_auth = preview_inject_auth_enabled()
    config = _preview_config()
    records = _build_preview_records(config)
    openai_llm = resolve_openai_preview_llm()
    synthesizer = None if openai_llm is not None else _preview_chat_synthesizer
    general_synthesizer = None if openai_llm is not None else _preview_general_synthesizer
    app = build_portal_app(
        config,
        connect=_fake_connect_factory(records),
        chat_embedding_model=_FakeEmbeddingModel(),
        chat_synthesizer=synthesizer,
        chat_general_synthesizer=general_synthesizer,
    )

    if inject_loopback_auth:

        @app.middleware("http")
        async def inject_loopback_auth(request, call_next):
            client = request.client
            if client and client.host in ("127.0.0.1", "::1", "localhost"):
                headers = list(request.scope.get("headers", []))
                headers.append((b"x-forwarded-user", _TRUSTED_USER.encode("ascii")))
                headers.append(
                    (b"x-notable-portal-proxy-secret", _PROXY_SECRET.encode("ascii"))
                )
                request.scope["headers"] = headers
            return await call_next(request)

    return app


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Local analyst portal preview API (fake data, loopback only)."
    )
    parser.add_argument(
        "--verify-auth",
        action="store_true",
        help="Run proxy-auth contract checks in-process and exit (no server start).",
    )
    parser.add_argument(
        "--verify-auth-live",
        metavar="URL",
        help=(
            "Run the same checks against a running preview API, e.g. "
            "http://127.0.0.1:8765. Start the server with --no-inject-auth first."
        ),
    )
    parser.add_argument(
        "--no-inject-auth",
        action="store_true",
        help=(
            "Do not auto-inject proxy auth on loopback. API calls must include "
            f"{_TRUSTED_USER_HEADER!r} and {_PROXY_SECRET_HEADER!r} "
            "(Vite dev proxy does this by default)."
        ),
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> None:
    args = _parse_args(argv)
    load_optional_preview_env()

    if args.verify_auth:
        print("Portal preview proxy-auth verification (in-process)")
        print(f"Expected user header: {_TRUSTED_USER_HEADER}={_TRUSTED_USER!r}")
        print(f"Expected proxy secret header: {_PROXY_SECRET_HEADER!r}")
        passed = _print_auth_checks(verify_preview_portal_auth())
        raise SystemExit(0 if passed else 1)

    if args.verify_auth_live:
        print(f"Portal preview proxy-auth verification (live: {args.verify_auth_live})")
        if preview_inject_auth_enabled() and not args.no_inject_auth:
            print(
                "Warning: PORTAL_PREVIEW_INJECT_AUTH is enabled on this process. "
                "Start the preview API with --no-inject-auth so unauthenticated "
                "requests fail as expected."
            )
        passed = _print_auth_checks(
            verify_preview_portal_auth_live(args.verify_auth_live)
        )
        raise SystemExit(0 if passed else 1)

    try:
        import uvicorn  # type: ignore
    except ImportError as exc:
        raise SystemExit("uvicorn is required. Install project dependencies first.") from exc

    inject_auth = not args.no_inject_auth
    url = f"http://{_PREVIEW_HOST}:{_PREVIEW_PORT}/"
    print("Alert Analysis Portal UI preview (fake data, loopback only)")
    print(f"Open in your browser: {url}")
    print(f"Chat synthesis: {preview_chat_mode_label()}")
    print(f"Loopback auth injection: {'on' if inject_auth else 'off'}")
    if not inject_auth:
        print(
            "API calls need proxy headers. Vite dev proxy sets them when using "
            "scripts/dev_portal_ui.ps1."
        )
        print(
            f"Quick check: python {Path(__file__).name} --verify-auth-live {url.rstrip('/')}"
        )
    print(f"Preview cases: {_PREVIEW_CASE_COUNT} (paginated at limit 50)")
    print(
        f"Pipeline-backed full analysis: case-1 .. case-{preview_scenario_count()} "
        "(real normalize + query enrichment + archive record builder)"
    )
    print("Pages: /  /cases  /cases/case-1")
    uvicorn.run(
        build_preview_app(inject_loopback_auth=inject_auth),
        host=_PREVIEW_HOST,
        port=_PREVIEW_PORT,
        log_level="info",
    )


if __name__ == "__main__":
    main()
