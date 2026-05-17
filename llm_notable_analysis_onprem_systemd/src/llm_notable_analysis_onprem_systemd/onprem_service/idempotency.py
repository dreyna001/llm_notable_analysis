"""Small file-backed idempotency helpers for external side effects."""

from __future__ import annotations

import hashlib
import json
import logging
import os
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .config import Config

logger = logging.getLogger(__name__)

_LOCK_WAIT_TIMEOUT_SECONDS = 30.0
_LOCK_STALE_SECONDS = 300.0
_GENERIC_KEYS = {"unknown", "none", "null", "n/a", "na"}


@dataclass(frozen=True)
class SideEffectReservation:
    """Reservation state for one side-effect attempt."""

    enabled: bool
    should_execute: bool
    operation: str
    key: str
    marker_path: Path | None = None
    lock_path: Path | None = None
    existing_marker: dict[str, Any] | None = None
    lock_acquired: bool = False


def _marker_path(config: Config, operation: str, key: str) -> Path:
    digest = hashlib.sha256(f"{operation}:{key}".encode("utf-8")).hexdigest()
    return config.SIDE_EFFECT_IDEMPOTENCY_DIR / f"{operation}-{digest}.json"


def _lock_path(marker_path: Path) -> Path:
    return marker_path.with_suffix(".lock")


def _normalize_key(key: str) -> str:
    normalized = str(key or "").strip()
    if not normalized or normalized.lower() in _GENERIC_KEYS:
        raise ValueError("side-effect idempotency key must be specific")
    return normalized


def _read_marker(path: Path) -> dict[str, Any] | None:
    if not path.exists():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {"metadata": {}}
    return payload if isinstance(payload, dict) else {"metadata": {}}


def _lock_is_stale(path: Path) -> bool:
    try:
        age_seconds = time.time() - path.stat().st_mtime
    except OSError:
        return False
    return age_seconds > _LOCK_STALE_SECONDS


def _acquire_lock(path: Path, *, operation: str, key: str) -> None:
    fd = os.open(str(path), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
    with os.fdopen(fd, "w", encoding="utf-8") as handle:
        json.dump(
            {
                "operation": operation,
                "key": key,
                "started_at": datetime.now(timezone.utc).isoformat(),
            },
            handle,
            sort_keys=True,
        )


def begin_side_effect(
    config: Config,
    *,
    operation: str,
    key: str,
    wait_timeout_seconds: float = _LOCK_WAIT_TIMEOUT_SECONDS,
) -> SideEffectReservation:
    """Reserve a side-effect key before executing an external write/action."""
    if not bool(getattr(config, "SIDE_EFFECT_IDEMPOTENCY_ENABLED", False)):
        return SideEffectReservation(
            enabled=False,
            should_execute=True,
            operation=operation,
            key=str(key or "").strip(),
        )

    normalized_key = _normalize_key(key)
    base_dir = config.SIDE_EFFECT_IDEMPOTENCY_DIR
    if not base_dir.is_absolute():
        raise ValueError("SIDE_EFFECT_IDEMPOTENCY_DIR must be an absolute path")

    marker_path = _marker_path(config, operation, normalized_key)
    lock_path = _lock_path(marker_path)
    marker_path.parent.mkdir(parents=True, exist_ok=True)
    deadline = time.monotonic() + wait_timeout_seconds

    while True:
        marker = _read_marker(marker_path)
        if marker is not None:
            return SideEffectReservation(
                enabled=True,
                should_execute=False,
                operation=operation,
                key=normalized_key,
                marker_path=marker_path,
                lock_path=lock_path,
                existing_marker=marker,
            )
        try:
            _acquire_lock(lock_path, operation=operation, key=normalized_key)
        except FileExistsError as exc:
            if _lock_is_stale(lock_path):
                try:
                    lock_path.unlink()
                except OSError:
                    pass
                continue
            if time.monotonic() >= deadline:
                raise TimeoutError(
                    f"Timed out waiting for side-effect idempotency lock: {operation}"
                ) from exc
            time.sleep(0.1)
            continue

        marker = _read_marker(marker_path)
        if marker is not None:
            release_side_effect_lock(
                SideEffectReservation(
                    enabled=True,
                    should_execute=False,
                    operation=operation,
                    key=normalized_key,
                    marker_path=marker_path,
                    lock_path=lock_path,
                    existing_marker=marker,
                    lock_acquired=True,
                )
            )
            return SideEffectReservation(
                enabled=True,
                should_execute=False,
                operation=operation,
                key=normalized_key,
                marker_path=marker_path,
                lock_path=lock_path,
                existing_marker=marker,
            )

        return SideEffectReservation(
            enabled=True,
            should_execute=True,
            operation=operation,
            key=normalized_key,
            marker_path=marker_path,
            lock_path=lock_path,
            lock_acquired=True,
        )


def complete_side_effect_success(
    reservation: SideEffectReservation,
    *,
    metadata: dict[str, Any] | None = None,
) -> bool:
    """Record success for an acquired side-effect reservation and release lock."""
    if not reservation.enabled:
        return True
    recorded = False
    if reservation.should_execute:
        payload = {
            "operation": reservation.operation,
            "key": reservation.key,
            "completed_at": datetime.now(timezone.utc).isoformat(),
            "metadata": metadata or {},
        }
        try:
            if reservation.marker_path is None:
                raise OSError("missing side-effect marker path")
            tmp_path = reservation.marker_path.with_suffix(".tmp")
            tmp_path.write_text(json.dumps(payload, sort_keys=True), encoding="utf-8")
            tmp_path.replace(reservation.marker_path)
            recorded = True
        except OSError as exc:
            logger.warning("Failed to write side-effect idempotency marker: %s", exc)
    release_side_effect_lock(reservation)
    return recorded


def release_side_effect_lock(reservation: SideEffectReservation) -> None:
    """Release an acquired side-effect lock."""
    if not reservation.lock_acquired or reservation.lock_path is None:
        return
    try:
        reservation.lock_path.unlink()
    except FileNotFoundError:
        return
    except OSError as exc:
        logger.warning("Failed to release side-effect idempotency lock: %s", exc)
