"""Distributed, per-user chat admission control backed by Cosmos DB.

One strongly-consistent document is maintained per user partition. ETag guarded
replacements make lease and budget changes atomic across Function App workers.
"""

from __future__ import annotations

import hashlib
import logging
import math
import time
import uuid
from dataclasses import dataclass
from typing import Any, Callable, Mapping

from .cosmos_store import CosmosStore, ttl_from_expiry

_DOCUMENT_ID = "chat-quota"


@dataclass(frozen=True)
class ChatQuotaDecision:
    allowed: bool
    request_id: str
    retry_after_seconds: int = 0
    reason: str = "allowed"


class ChatQuotaStoreError(RuntimeError):
    """The distributed quota could not be evaluated safely."""


class CosmosChatQuota:
    """Atomic per-user concurrency, request-rate, and cost-budget gate."""

    def __init__(
        self,
        store: CosmosStore,
        *,
        container_name: str,
        max_concurrency: int,
        window_seconds: int,
        max_requests_per_window: int,
        max_budget_units_per_window: int,
        lease_seconds: int,
        dedupe_seconds: int,
        clock: Callable[[], float] = time.time,
        logger: logging.Logger | None = None,
        max_attempts: int = 8,
    ) -> None:
        self.store = store
        self.container_name = container_name
        self.max_concurrency = max_concurrency
        self.window_seconds = window_seconds
        self.max_requests_per_window = max_requests_per_window
        self.max_budget_units_per_window = max_budget_units_per_window
        self.lease_seconds = lease_seconds
        self.dedupe_seconds = dedupe_seconds
        self.clock = clock
        self.logger = logger or logging.getLogger(__name__)
        self.max_attempts = max_attempts

    def acquire(
        self,
        *,
        user_id: str,
        budget_units: int,
        request_id: str | None = None,
    ) -> ChatQuotaDecision:
        normalized_user = _required_text(user_id, "user_id")
        normalized_request = request_id or str(uuid.uuid4())
        units = int(budget_units)
        if units <= 0:
            raise ValueError("budget_units must be positive")

        for _attempt in range(self.max_attempts):
            now = int(self.clock())
            item = self.store.read_item(
                self.container_name,
                item_id=_DOCUMENT_ID,
                partition_key=normalized_user,
            )
            if item is None:
                body = self._new_document(
                    user_id=normalized_user,
                    request_id=normalized_request,
                    budget_units=units,
                    now=now,
                )
                outcome = self.store.create_if_absent(self.container_name, body)
                if outcome.created:
                    self._log("allowed", normalized_user, normalized_request)
                    return ChatQuotaDecision(True, normalized_request)
                continue

            updated, decision = self._admit_existing(
                item,
                request_id=normalized_request,
                budget_units=units,
                now=now,
            )
            if not decision.allowed:
                self._log(decision.reason, normalized_user, normalized_request)
                return decision
            etag = _required_text(item.get("_etag"), "quota _etag")
            outcome = self.store.replace_if_match(
                self.container_name,
                updated,
                expected_etag=etag,
            )
            if outcome.applied:
                self._log("allowed", normalized_user, normalized_request)
                return decision

        raise ChatQuotaStoreError("Chat quota contention exceeded the retry limit.")

    def release(self, *, user_id: str, request_id: str) -> None:
        """Release a lease; crash recovery is guaranteed by lease expiry."""

        normalized_user = _required_text(user_id, "user_id")
        normalized_request = _required_text(request_id, "request_id")
        for _attempt in range(self.max_attempts):
            item = self.store.read_item(
                self.container_name,
                item_id=_DOCUMENT_ID,
                partition_key=normalized_user,
            )
            if item is None:
                return
            leases = _object_list(item.get("active_leases"))
            remaining = [
                lease for lease in leases if lease.get("request_id") != normalized_request
            ]
            if len(remaining) == len(leases):
                return
            updated = dict(item)
            updated["active_leases"] = remaining
            updated["updated_at_epoch"] = int(self.clock())
            outcome = self.store.replace_if_match(
                self.container_name,
                updated,
                expected_etag=_required_text(item.get("_etag"), "quota _etag"),
            )
            if outcome.applied or outcome.outcome == "not_found":
                return
        self.logger.warning(
            "chat_quota_release_deferred request_id=%s",
            normalized_request,
            extra={"chat_quota_outcome": "lease_expiry_recovery"},
        )

    def _new_document(
        self, *, user_id: str, request_id: str, budget_units: int, now: int
    ) -> dict[str, Any]:
        window_start = now - (now % self.window_seconds)
        retention_end = max(
            window_start + self.window_seconds,
            now + self.dedupe_seconds,
            now + self.lease_seconds,
        )
        return {
            "id": _DOCUMENT_ID,
            "user_id": user_id,
            "window_start_epoch": window_start,
            "request_count": 1,
            "budget_units": budget_units,
            "active_leases": [self._lease(request_id, now)],
            "recent_request_ids": [self._recent(request_id, now)],
            "updated_at_epoch": now,
            "ttl": ttl_from_expiry(retention_end, now_epoch=now),
        }

    def _admit_existing(
        self,
        item: Mapping[str, Any],
        *,
        request_id: str,
        budget_units: int,
        now: int,
    ) -> tuple[dict[str, Any], ChatQuotaDecision]:
        window_start = now - (now % self.window_seconds)
        if int(item.get("window_start_epoch") or -1) != window_start:
            request_count = 0
            used_budget = 0
        else:
            request_count = int(item.get("request_count") or 0)
            used_budget = int(item.get("budget_units") or 0)

        leases = [
            lease
            for lease in _object_list(item.get("active_leases"))
            if int(lease.get("expires_at_epoch") or 0) > now
        ]
        recent = [
            entry
            for entry in _object_list(item.get("recent_request_ids"))
            if int(entry.get("expires_at_epoch") or 0) > now
        ]
        duplicate = next(
            (entry for entry in recent if entry.get("request_id") == request_id), None
        )
        if duplicate is not None:
            return dict(item), ChatQuotaDecision(
                False,
                request_id,
                _retry_after(int(duplicate["expires_at_epoch"]), now),
                "duplicate_request",
            )
        if len(leases) >= self.max_concurrency:
            earliest = min(int(lease["expires_at_epoch"]) for lease in leases)
            return dict(item), ChatQuotaDecision(
                False, request_id, _retry_after(earliest, now), "concurrency"
            )
        window_end = window_start + self.window_seconds
        if request_count >= self.max_requests_per_window:
            return dict(item), ChatQuotaDecision(
                False, request_id, _retry_after(window_end, now), "request_window"
            )
        if used_budget + budget_units > self.max_budget_units_per_window:
            return dict(item), ChatQuotaDecision(
                False, request_id, _retry_after(window_end, now), "budget_window"
            )

        leases.append(self._lease(request_id, now))
        recent.append(self._recent(request_id, now))
        retention_end = max(
            window_end,
            max(int(entry["expires_at_epoch"]) for entry in recent),
            max(int(lease["expires_at_epoch"]) for lease in leases),
        )
        updated = dict(item)
        updated.update(
            {
                "window_start_epoch": window_start,
                "request_count": request_count + 1,
                "budget_units": used_budget + budget_units,
                "active_leases": leases,
                "recent_request_ids": recent,
                "updated_at_epoch": now,
                "ttl": ttl_from_expiry(retention_end, now_epoch=now),
            }
        )
        return updated, ChatQuotaDecision(True, request_id)

    def _lease(self, request_id: str, now: int) -> dict[str, Any]:
        return {"request_id": request_id, "expires_at_epoch": now + self.lease_seconds}

    def _recent(self, request_id: str, now: int) -> dict[str, Any]:
        return {"request_id": request_id, "expires_at_epoch": now + self.dedupe_seconds}

    def _log(self, outcome: str, user_id: str, request_id: str) -> None:
        self.logger.info(
            "chat_quota_decision outcome=%s request_id=%s",
            outcome,
            request_id,
            extra={
                "chat_quota_outcome": outcome,
                "chat_quota_user_hash": hashlib.sha256(user_id.encode("utf-8")).hexdigest()[:16],
                "chat_quota_request_id": request_id,
            },
        )


def _object_list(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []
    return [dict(item) for item in value if isinstance(item, Mapping)]


def _retry_after(expiry: int, now: int) -> int:
    return max(1, math.ceil(expiry - now))


def _required_text(value: Any, field_name: str) -> str:
    text = str(value or "").strip()
    if not text:
        raise ValueError(f"{field_name} is required")
    return text
