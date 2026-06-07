"""Small shared Postgres helper functions for case archive modules."""

from __future__ import annotations

from typing import Any


def default_connect(dsn: str) -> Any:
    """Open a psycopg connection for case archive operations."""
    try:
        import psycopg  # type: ignore
    except Exception as exc:  # pragma: no cover - import guard
        raise RuntimeError("psycopg is unavailable in the runtime.") from exc
    return psycopg.connect(dsn, connect_timeout=5)


def set_statement_timeout(conn: Any, timeout_ms: int) -> None:
    """Set a transaction-local Postgres statement timeout."""
    if int(timeout_ms) > 0:
        conn.execute(
            "SELECT set_config('statement_timeout', %s, true)",
            (f"{int(timeout_ms)}ms",),
        )


def fetchone(result: Any) -> Any:
    """Read one row from a cursor-like result."""
    fetchone_fn = getattr(result, "fetchone", None)
    if callable(fetchone_fn):
        return fetchone_fn()
    return None


def fetchall(result: Any) -> list[Any]:
    """Read all rows from a cursor-like result."""
    fetchall_fn = getattr(result, "fetchall", None)
    if callable(fetchall_fn):
        return list(fetchall_fn())
    return []


def row_get(row: Any, index: int, key: str) -> Any:
    """Read one value from a row object, mapping, or sequence."""
    if row is None:
        return None
    if isinstance(row, dict):
        return row.get(key)
    try:
        mapping = row._mapping  # type: ignore[attr-defined]
        if key in mapping:
            return mapping[key]
    except Exception:
        pass
    try:
        return row[index]
    except Exception:
        return getattr(row, key, None)
