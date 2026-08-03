"""DynamoDB-backed idempotency helpers for external side effects."""
# pylint: disable=broad-exception-caught

from __future__ import annotations

import hashlib
import json
import time
from uuid import uuid4
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from .aws_clients import dynamodb_client
from .config import Config

_GENERIC_KEYS = {"unknown", "none", "null", "n/a", "na"}


@dataclass(frozen=True)
class SideEffectReservation:
    """Reservation state for one side-effect attempt."""

    enabled: bool
    should_execute: bool
    operation: str
    key: str
    table_name: str = ""
    item_id: str = ""
    existing_marker: dict[str, Any] | None = None
    client: Any | None = None
    fencing_token: str = ""


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


def _metadata_to_attr(metadata: dict[str, Any]) -> dict[str, Any]:
    return {"S": json.dumps(metadata or {}, sort_keys=True, default=str)}


def _metadata_from_item(item: dict[str, Any]) -> dict[str, Any]:
    raw = item.get("metadata", {}).get("S", "{}")
    try:
        parsed = json.loads(raw)
    except (TypeError, ValueError):
        return {}
    return parsed if isinstance(parsed, dict) else {}


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
    return {
        "operation": item.get("operation", {}).get("S", operation),
        "key": item.get("side_effect_key", {}).get("S", key),
        "status": item.get("status", {}).get("S", "unknown"),
        "started_at": item.get("started_at", {}).get("S", ""),
        "fencing_token": item.get("fencing_token", {}).get("S", ""),
        "metadata": _metadata_from_item(item),
    }


def _is_stale_in_progress(marker: dict[str, Any], *, lock_seconds: int) -> bool:
    if marker.get("status") != "in_progress":
        return False
    started_epoch = _parse_epoch(str(marker.get("started_at", "")))
    if started_epoch is None:
        return False
    return time.time() - started_epoch > max(1, lock_seconds)


def _error_code(exc: Exception) -> str:
    response = getattr(exc, "response", {})
    if isinstance(response, dict):
        return str(response.get("Error", {}).get("Code", ""))
    return ""


def begin_side_effect(
    config: Config,
    *,
    operation: str,
    key: str,
    client: Any | None = None,
) -> SideEffectReservation:
    """Reserve a side-effect key before executing an external write/action."""

    if not bool(getattr(config, "SIDE_EFFECT_IDEMPOTENCY_ENABLED", False)):
        return SideEffectReservation(
            enabled=False,
            should_execute=True,
            operation=operation,
            key=str(key or "").strip(),
        )

    table_name = str(getattr(config, "SIDE_EFFECT_IDEMPOTENCY_TABLE", "")).strip()
    if not table_name:
        raise ValueError("SIDE_EFFECT_IDEMPOTENCY_TABLE is required when idempotency is enabled")

    normalized_key = _normalize_key(key)
    item_id = _item_id(operation, normalized_key)
    ddb = client or dynamodb_client()
    now = datetime.now(timezone.utc).isoformat()
    ttl = _expiry_epoch(int(getattr(config, "SIDE_EFFECT_IDEMPOTENCY_RETENTION_DAYS", 30)))
    fencing_token = uuid4().hex

    for attempt in range(2):
        try:
            ddb.put_item(
                TableName=table_name,
                Item={
                    "id": {"S": item_id},
                    "operation": {"S": operation},
                    "side_effect_key": {"S": normalized_key},
                    "status": {"S": "in_progress"},
                    "started_at": {"S": now},
                    "fencing_token": {"S": fencing_token},
                    "expires_at": {"N": str(ttl)},
                },
                ConditionExpression="attribute_not_exists(id)",
            )
            break
        except Exception as exc:
            if _error_code(exc) != "ConditionalCheckFailedException":
                raise
            existing = ddb.get_item(TableName=table_name, Key={"id": {"S": item_id}}).get("Item", {})
            marker = _marker_from_item(existing, operation=operation, key=normalized_key)
            lock_seconds = int(getattr(config, "SIDE_EFFECT_IDEMPOTENCY_LOCK_SECONDS", 900))
            if attempt == 0 and _is_stale_in_progress(marker, lock_seconds=lock_seconds):
                takeover_token = uuid4().hex
                try:
                    condition_values = {
                        ":status": {"S": "in_progress"},
                        ":started_at": {"S": str(marker.get("started_at", ""))},
                    }
                    condition = "#status = :status AND #started_at = :started_at"
                    names = {"#status": "status", "#started_at": "started_at"}
                    if marker.get("fencing_token"):
                        condition += " AND #fencing_token = :fencing_token"
                        names["#fencing_token"] = "fencing_token"
                        condition_values[":fencing_token"] = {
                            "S": str(marker["fencing_token"])
                        }
                    ddb.update_item(
                        TableName=table_name,
                        Key={"id": {"S": item_id}},
                        UpdateExpression=(
                            "SET #status = :new_status, started_at = :new_started_at, "
                            "fencing_token = :new_fencing_token"
                        ),
                        ConditionExpression=condition,
                        ExpressionAttributeNames=names,
                        ExpressionAttributeValues={
                            **condition_values,
                            ":new_status": {"S": "in_progress"},
                            ":new_started_at": {"S": now},
                            ":new_fencing_token": {"S": takeover_token},
                        },
                    )
                except Exception as delete_exc:
                    if _error_code(delete_exc) != "ConditionalCheckFailedException":
                        raise
                    return SideEffectReservation(
                        enabled=True,
                        should_execute=False,
                        operation=operation,
                        key=normalized_key,
                        table_name=table_name,
                        item_id=item_id,
                        existing_marker=marker,
                        client=ddb,
                    )
                return SideEffectReservation(
                    enabled=True,
                    should_execute=True,
                    operation=operation,
                    key=normalized_key,
                    table_name=table_name,
                    item_id=item_id,
                    client=ddb,
                    fencing_token=takeover_token,
                )
            return SideEffectReservation(
                enabled=True,
                should_execute=False,
                operation=operation,
                key=normalized_key,
                table_name=table_name,
                item_id=item_id,
                existing_marker=marker,
                client=ddb,
            )

    return SideEffectReservation(
        enabled=True,
        should_execute=True,
        operation=operation,
        key=normalized_key,
        table_name=table_name,
        item_id=item_id,
        client=ddb,
        fencing_token=fencing_token,
    )


def complete_side_effect_success(
    reservation: SideEffectReservation,
    *,
    metadata: dict[str, Any] | None = None,
) -> bool:
    """Record success for an acquired side-effect reservation."""

    if not reservation.enabled:
        return True
    if not reservation.should_execute:
        return False
    if not reservation.client:
        return False
    try:
        reservation.client.update_item(
            TableName=reservation.table_name,
            Key={"id": {"S": reservation.item_id}},
            UpdateExpression=(
                "SET #status = :status, completed_at = :completed_at, metadata = :metadata"
            ),
            ConditionExpression="#status = :in_progress AND fencing_token = :fencing_token",
            ExpressionAttributeNames={"#status": "status"},
            ExpressionAttributeValues={
                ":status": {"S": "completed"},
                ":in_progress": {"S": "in_progress"},
                ":fencing_token": {"S": reservation.fencing_token},
                ":completed_at": {"S": datetime.now(timezone.utc).isoformat()},
                ":metadata": _metadata_to_attr(metadata or {}),
            },
        )
        return True
    except Exception:
        mark_side_effect_uncertain(
            reservation,
            metadata={
                **(metadata or {}),
                "external_success": True,
                "uncertain_reason": "completion_marker_write_failed",
            },
        )
        return False


def release_side_effect_lock(reservation: SideEffectReservation) -> None:
    """Release an in-progress reservation after a failed side effect."""

    if not reservation.enabled or not reservation.should_execute or not reservation.client:
        return
    try:
        reservation.client.delete_item(
            TableName=reservation.table_name,
            Key={"id": {"S": reservation.item_id}},
            ConditionExpression="#status = :status AND fencing_token = :fencing_token",
            ExpressionAttributeNames={"#status": "status"},
            ExpressionAttributeValues={
                ":status": {"S": "in_progress"},
                ":fencing_token": {"S": reservation.fencing_token},
            },
        )
    except Exception:
        return


def mark_side_effect_uncertain(
    reservation: SideEffectReservation,
    *,
    metadata: dict[str, Any] | None = None,
) -> bool:
    """Fence a side effect in an uncertain state after an ambiguous outcome."""

    if not reservation.enabled or not reservation.should_execute or not reservation.client:
        return False
    try:
        reservation.client.update_item(
            TableName=reservation.table_name,
            Key={"id": {"S": reservation.item_id}},
            UpdateExpression=(
                "SET #status = :status, completed_at = :completed_at, metadata = :metadata"
            ),
            ConditionExpression="#status = :in_progress AND fencing_token = :fencing_token",
            ExpressionAttributeNames={"#status": "status"},
            ExpressionAttributeValues={
                ":status": {"S": "uncertain"},
                ":in_progress": {"S": "in_progress"},
                ":fencing_token": {"S": reservation.fencing_token},
                ":completed_at": {"S": datetime.now(timezone.utc).isoformat()},
                ":metadata": _metadata_to_attr(metadata or {}),
            },
        )
        return True
    except Exception:
        return False
