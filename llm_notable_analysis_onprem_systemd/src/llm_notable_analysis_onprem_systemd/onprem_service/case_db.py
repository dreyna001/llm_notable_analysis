"""Small shared Postgres helper functions for case archive modules."""

from __future__ import annotations

from typing import Any


def postgres_operation_errors() -> tuple[type[BaseException], ...]:
    """Exception types commonly raised by case-archive Postgres operations."""
    errors: list[type[BaseException]] = [OSError, RuntimeError, ValueError]
    try:
        import psycopg  # type: ignore

        errors.append(psycopg.Error)
    except ImportError:
        pass
    return tuple(errors)


def default_connect(dsn: str) -> Any:
    """Open a psycopg connection for case archive operations."""
    try:
        import psycopg  # type: ignore
    except ImportError as exc:  # pragma: no cover - import guard
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
    mapping = getattr(row, "_mapping", None)
    if mapping is not None:
        try:
            if key in mapping:
                return mapping[key]
        except (KeyError, TypeError, AttributeError):
            pass
    try:
        return row[index]
    except (KeyError, IndexError, TypeError):
        return getattr(row, key, None)
