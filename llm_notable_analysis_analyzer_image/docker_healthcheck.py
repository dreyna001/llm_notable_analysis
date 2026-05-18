#!/usr/bin/env python3
"""Container healthcheck for the notable analyzer worker.

Checks:
- ingest/report directories exist and are writable
- optional LiteLLM /v1/models reachability (ANALYZER_HEALTHCHECK_CHECK_LLM=true)
- optional Postgres reachability when RAG is enabled (ANALYZER_HEALTHCHECK_CHECK_POSTGRES=true)
"""

from __future__ import annotations

import os
import sys
from pathlib import Path
from urllib.error import URLError
from urllib.request import Request, urlopen

_TRUE = {"1", "true", "yes"}


def _env_bool(name: str, default: bool = False) -> bool:
    raw = os.getenv(name, "").strip().lower()
    if not raw:
        return default
    return raw in _TRUE


def _check_directories() -> None:
    paths = [
        os.getenv("INCOMING_DIR", "/var/notables/incoming"),
        os.getenv("PROCESSED_DIR", "/var/notables/processed"),
        os.getenv("QUARANTINE_DIR", "/var/notables/quarantine"),
        os.getenv("REPORT_DIR", "/var/notables/reports"),
    ]
    for entry in paths:
        path = Path(entry)
        if not path.is_dir():
            raise RuntimeError(f"missing directory: {path}")
        probe = path / ".healthcheck_write"
        probe.write_text("ok", encoding="utf-8")
        probe.unlink(missing_ok=True)


def _llm_models_url() -> str:
    api_url = os.getenv("LLM_API_URL", "").strip()
    if not api_url:
        return ""
    if api_url.endswith("/chat/completions"):
        return api_url[: -len("chat/completions")] + "models"
    return api_url.rstrip("/") + "/models"


def _check_llm() -> None:
    models_url = _llm_models_url()
    if not models_url:
        return

    request = Request(models_url, method="GET")
    token = os.getenv("LLM_API_TOKEN", "").strip()
    if token:
        request.add_header("Authorization", f"Bearer {token}")

    timeout = float(os.getenv("ANALYZER_HEALTHCHECK_TIMEOUT_SECONDS", "5"))
    with urlopen(request, timeout=timeout) as response:
        if response.status >= 400:
            raise RuntimeError(f"LLM models probe failed: HTTP {response.status}")


def _check_postgres() -> None:
    if not _env_bool("RAG_ENABLED"):
        return
    if os.getenv("RAG_BACKEND", "postgres").strip().lower() != "postgres":
        return

    dsn = os.getenv("RAG_POSTGRES_DSN", "").strip()
    if not dsn:
        raise RuntimeError("RAG_ENABLED with postgres backend but RAG_POSTGRES_DSN is unset")

    try:
        import psycopg  # pylint: disable=import-error
    except Exception as exc:
        raise RuntimeError("Postgres health probe cannot import psycopg") from exc

    timeout = int(os.getenv("ANALYZER_HEALTHCHECK_TIMEOUT_SECONDS", "5"))
    try:
        with psycopg.connect(dsn, connect_timeout=timeout) as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT 1")
    except psycopg.Error as exc:
        raise RuntimeError(
            f"Postgres health probe failed: {exc.__class__.__name__}"
        ) from None


def main() -> int:
    try:
        _check_directories()
        if _env_bool("ANALYZER_HEALTHCHECK_CHECK_LLM", True):
            _check_llm()
        if _env_bool("ANALYZER_HEALTHCHECK_CHECK_POSTGRES", True):
            _check_postgres()
    except (OSError, RuntimeError, URLError, ValueError) as exc:
        print(f"healthcheck failed: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
