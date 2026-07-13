"""Cosmos-backed idempotency helpers for external side effects."""

from __future__ import annotations

import hashlib
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from .config import Config
from .cosmos_store import CosmosStore

_GENERIC_KEYS = {"unknown", "none", "null", "n/a", "na"}


@dataclass(frozen=True)
class SideEffectReservation:
    """Reservation state for one side-effect attempt."""

    enabled: bool
    should_execute: bool
    operation: str
    key: str
    container_name: str = ""
    item_id: str = ""
    etag: str = ""
    existing_marker: dict[str, Any] | None = None
    store: CosmosStore | None = None


def _normalize_key(key: str) -> str:
    normalized = str(key or "").strip()
    if not normalized or normalized.lower() in _GENERIC_KEYS:
        raise ValueError("side-effect idempotency key must be specific")
    return normalized


def _item_id(operation: str, key: str) -> str:
    digest = hashlib.sha256(f"{operation}:{key}".encode("utf-8")).hexdigest()
    return f"{operation}#{digest}"


def _expiry_epoch(retention_days: int) -> int:
    return int(time.time()) + max(1, int(retention_days)) * 86400


def _parse_epoch(value: str) -> float | None:
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00")).timestamp()
    except (TypeError, ValueError):
        return None


def _marker_from_item(
    item: dict[str, Any],
    *,
    operation: str,
    key: str,
) -> dict[str, Any]:
    metadata = item.get("metadata")
    return {
        "operation": str(item.get("operation") or operation),
        "key": str(item.get("side_effect_key") or key),
        "status": str(item.get("status") or "unknown"),
        "started_at": str(item.get("started_at") or ""),
        "metadata": dict(metadata) if isinstance(metadata, dict) else {},
    }


def _is_stale_in_progress(marker: dict[str, Any], *, lock_seconds: int) -> bool:
    if marker.get("status") != "in_progress":
        return False
    started_epoch = _parse_epoch(str(marker.get("started_at", "")))
    if started_epoch is None:
        return False
    return time.time() - started_epoch > max(1, lock_seconds)


def begin_side_effect(
    config: Config,
    *,
    operation: str,
    key: str,
    client: Any | None = None,
) -> SideEffectReservation:
    """Reserve a side-effect key before executing an external write/action.

    ``client`` remains an injection point used by existing business call sites,
    but its value is a :class:`CosmosStore`, never a database SDK client shape.
    """

    if not config.SIDE_EFFECT_IDEMPOTENCY_ENABLED:
        return SideEffectReservation(False, True, operation, str(key or "").strip())

    container_name = str(config.SIDE_EFFECT_IDEMPOTENCY_CONTAINER or "").strip()
    if not container_name:
        raise ValueError(
            "SIDE_EFFECT_IDEMPOTENCY_CONTAINER is required when idempotency is enabled"
        )
    if client is not None and not isinstance(client, CosmosStore):
        raise TypeError("idempotency client must be a CosmosStore")
    store = client or CosmosStore.from_config(config)
    normalized_key = _normalize_key(key)
    item_id = _item_id(operation, normalized_key)
    now = datetime.now(timezone.utc).isoformat()
    item = {
        "id": item_id,
        "operation": operation,
        "side_effect_key": normalized_key,
        "status": "in_progress",
        "started_at": now,
        "expires_at": _expiry_epoch(config.SIDE_EFFECT_IDEMPOTENCY_RETENTION_DAYS),
    }

    for attempt in range(2):
        created = store.create_if_absent(container_name, item)
        if created.created:
            created_item = created.item or item
            return SideEffectReservation(
                True,
                True,
                operation,
                normalized_key,
                container_name=container_name,
                item_id=item_id,
                etag=str(created_item.get("_etag") or ""),
                store=store,
            )

        existing = store.read_item(
            container_name,
            item_id=item_id,
            partition_key=item_id,
        )
        if not existing:
            continue
        marker = _marker_from_item(existing, operation=operation, key=normalized_key)
        lock_seconds = int(config.SIDE_EFFECT_IDEMPOTENCY_LOCK_SECONDS)
        etag = str(existing.get("_etag") or "")
        if attempt == 0 and etag and _is_stale_in_progress(marker, lock_seconds=lock_seconds):
            deleted = store.delete_if_match(
                container_name,
                item_id=item_id,
                partition_key=item_id,
                expected_etag=etag,
            )
            if deleted.applied:
                continue
        return SideEffectReservation(
            True,
            False,
            operation,
            normalized_key,
            container_name=container_name,
            item_id=item_id,
            etag=etag,
            existing_marker=marker,
            store=store,
        )

    return SideEffectReservation(
        True,
        False,
        operation,
        normalized_key,
        container_name=container_name,
        item_id=item_id,
        store=store,
    )


def complete_side_effect_success(
    reservation: SideEffectReservation,
    *,
    metadata: dict[str, Any] | None = None,
) -> bool:
    """Record success for an acquired side-effect reservation."""

    if not reservation.enabled:
        return True
    if not reservation.should_execute or not reservation.store or not reservation.etag:
        return False
    current = reservation.store.read_item(
        reservation.container_name,
        item_id=reservation.item_id,
        partition_key=reservation.item_id,
    )
    if not current or current.get("status") != "in_progress":
        return False
    current_etag = str(current.get("_etag") or "")
    if not current_etag or current_etag != reservation.etag:
        return False
    updated = dict(current)
    updated.update(
        {
            "status": "completed",
            "completed_at": datetime.now(timezone.utc).isoformat(),
            "metadata": dict(metadata or {}),
        }
    )
    try:
        outcome = reservation.store.replace_if_match(
            reservation.container_name,
            updated,
            expected_etag=current_etag,
        )
    except Exception:
        return False
    return outcome.applied


def release_side_effect_lock(reservation: SideEffectReservation) -> None:
    """Release an in-progress reservation after a failed side effect."""

    if not reservation.enabled or not reservation.should_execute or not reservation.store:
        return
    try:
        current = reservation.store.read_item(
            reservation.container_name,
            item_id=reservation.item_id,
            partition_key=reservation.item_id,
        )
        if not current or current.get("status") != "in_progress":
            return
        etag = str(current.get("_etag") or "")
        if not etag or etag != reservation.etag:
            return
        reservation.store.delete_if_match(
            reservation.container_name,
            item_id=reservation.item_id,
            partition_key=reservation.item_id,
            expected_etag=etag,
        )
    except Exception:
        return
