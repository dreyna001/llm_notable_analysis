"""Application-oriented Azure Cosmos DB persistence boundary.

The boundary deliberately exposes plain application documents and typed
outcomes.  Cosmos continuation tokens, SDK response envelopes, and database
query syntax do not escape into business modules.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Callable, Mapping

from azure.core import MatchConditions


CONTAINER_PARTITION_KEYS: dict[str, str] = {
    "side_effect_idempotency": "/id",
    "case_index": "/case_id",
    "disposition": "/snow_sys_id",
    "disposition_sync_state": "/job_name",
    "chat_sessions": "/user_id",
    "chat_messages": "/session_id",
    "chat_quota": "/user_id",
}


@dataclass(frozen=True)
class CreateOutcome:
    """Result of a create-if-absent operation."""

    created: bool
    item: dict[str, Any] | None = None


@dataclass(frozen=True)
class ConditionalOutcome:
    """Result of an ETag-guarded replace or delete operation."""

    applied: bool
    outcome: str
    item: dict[str, Any] | None = None


def ttl_from_expiry(expiry_epoch: int | float, *, now_epoch: int | None = None) -> int:
    """Return a positive Cosmos item TTL derived from business expiry."""

    now = int(time.time()) if now_epoch is None else int(now_epoch)
    return max(1, int(expiry_epoch) - now)


class CosmosStore:
    """Native Cosmos persistence facade for the application's aggregates.

    The deployed account is single-region and configured for Strong
    consistency. Point reads therefore retain the correctness assumptions of
    the original strongly-consistent persistence operations.
    """

    def __init__(
        self,
        database: Any,
        *,
        logger: logging.Logger | None = None,
        clock: Callable[[], float] = time.time,
        perf_counter: Callable[[], float] = time.perf_counter,
    ) -> None:
        self.database = database
        self._logger = logger or logging.getLogger(__name__)
        self._clock = clock
        self._perf_counter = perf_counter

    @classmethod
    def from_config(cls, config: Any) -> "CosmosStore":
        """Construct the store from the native Cosmos runtime contract."""

        from .azure_clients import cosmos_client

        endpoint = _required_text(getattr(config, "COSMOS_ENDPOINT", ""), "COSMOS_ENDPOINT")
        database_name = _required_text(
            getattr(config, "COSMOS_DATABASE_NAME", ""),
            "COSMOS_DATABASE_NAME",
        )
        return cls(cosmos_client(endpoint).get_database_client(database_name))

    def create_if_absent(
        self,
        container_name: str,
        item: Mapping[str, Any],
    ) -> CreateOutcome:
        """Create a document, returning ``created=False`` for native 409 conflicts."""

        container = self._container(container_name)
        body = self._prepare_item(item)
        try:
            created = self._call(
                container_name,
                "create",
                container.create_item,
                body=body,
                if_none_match="*",
            )
        except Exception as exc:
            if _status_code(exc) == 409:
                return CreateOutcome(created=False)
            raise
        return CreateOutcome(created=True, item=_plain_item(created))

    def probe_container(self, container_name: str) -> None:
        """Verify that a container exists and the identity can read its metadata.

        A sentinel item read cannot distinguish a missing item from a missing
        container because both are native 404 responses.  Reading container
        metadata is non-mutating and preserves that distinction for readiness
        checks.
        """

        container = self._container(container_name)
        self._call(container_name, "probe", container.read)

    def read_item(
        self,
        container_name: str,
        *,
        item_id: str,
        partition_key: str,
    ) -> dict[str, Any] | None:
        """Perform a Strong point read, returning ``None`` for a native 404."""

        container = self._container(container_name)
        try:
            item = self._call(
                container_name,
                "read",
                container.read_item,
                item=item_id,
                partition_key=partition_key,
            )
        except Exception as exc:
            if _status_code(exc) == 404:
                return None
            raise
        return _plain_item(item)

    def replace_if_match(
        self,
        container_name: str,
        item: Mapping[str, Any],
        *,
        expected_etag: str,
    ) -> ConditionalOutcome:
        """Replace a document only when its ETag remains unchanged."""

        container = self._container(container_name)
        body = self._prepare_item(item)
        item_id = _required_text(body.get("id"), "id")
        try:
            replaced = self._call(
                container_name,
                "replace",
                container.replace_item,
                item=item_id,
                body=body,
                etag=_required_text(expected_etag, "expected_etag"),
                match_condition=MatchConditions.IfNotModified,
            )
        except Exception as exc:
            status = _status_code(exc)
            if status == 404:
                return ConditionalOutcome(False, "not_found")
            if status == 412:
                return ConditionalOutcome(False, "precondition_failed")
            raise
        return ConditionalOutcome(True, "replaced", _plain_item(replaced))

    def delete_if_match(
        self,
        container_name: str,
        *,
        item_id: str,
        partition_key: str,
        expected_etag: str,
    ) -> ConditionalOutcome:
        """Delete a document only when its ETag remains unchanged."""

        container = self._container(container_name)
        try:
            self._call(
                container_name,
                "delete",
                container.delete_item,
                item=item_id,
                partition_key=partition_key,
                etag=_required_text(expected_etag, "expected_etag"),
                match_condition=MatchConditions.IfNotModified,
            )
        except Exception as exc:
            status = _status_code(exc)
            if status == 404:
                return ConditionalOutcome(False, "not_found")
            if status == 412:
                return ConditionalOutcome(False, "precondition_failed")
            raise
        return ConditionalOutcome(True, "deleted")

    def upsert_item(
        self,
        container_name: str,
        item: Mapping[str, Any],
    ) -> dict[str, Any]:
        """Upsert one aggregate document with business-derived TTL."""

        container = self._container(container_name)
        result = self._call(
            container_name,
            "upsert",
            container.upsert_item,
            body=self._prepare_item(item),
        )
        return _plain_item(result)

    def get_case(self, container_name: str, case_id: str) -> dict[str, Any] | None:
        """Read one case by its natural id and partition key."""

        normalized = _required_text(case_id, "case_id")
        return self.read_item(
            container_name,
            item_id=normalized,
            partition_key=normalized,
        )

    def upsert_case(
        self,
        container_name: str,
        case: Mapping[str, Any],
    ) -> dict[str, Any]:
        """Upsert one case-index document using ``id=case_id``."""

        body = dict(case)
        case_id = _required_text(body.get("case_id"), "case_id")
        body["id"] = case_id
        return self.upsert_item(container_name, body)

    def create_case_if_absent(
        self,
        container_name: str,
        case: Mapping[str, Any],
    ) -> CreateOutcome:
        """Conditionally create one case-index document by natural case ID."""

        body = dict(case)
        case_id = _required_text(body.get("case_id"), "case_id")
        body["id"] = case_id
        return self.create_if_absent(container_name, body)

    def publish_case_run_if_latest(
        self,
        container_name: str,
        *,
        case_id: str,
        run_id: str,
        run_record: Mapping[str, Any],
        expected_etag: str,
        processed_at: str,
    ) -> ConditionalOutcome:
        """Publish an immutable run while preserving a newer latest pointer."""

        body = self.get_case(container_name, _required_text(case_id, "case_id"))
        if body is None:
            return ConditionalOutcome(False, "not_found")
        runs = body.get("runs")
        run_map = dict(runs) if isinstance(runs, Mapping) else {}
        run_map[_required_text(run_id, "run_id")] = dict(run_record)
        replacement = dict(body)
        replacement["runs"] = run_map
        current_latest = str(body.get("latest_run_at") or "")
        if not current_latest or str(processed_at) >= current_latest:
            replacement.update(
                {
                    "latest_run_id": run_id,
                    "latest_run_key": str(run_record.get("envelope_key") or ""),
                    "latest_run_at": processed_at,
                    "case_envelope_key": str(run_record.get("envelope_key") or ""),
                }
            )
        return self.replace_if_match(
            container_name,
            replacement,
            expected_etag=_required_text(expected_etag, "expected_etag"),
        )

    def update_case_retrieval_status(
        self,
        container_name: str,
        *,
        case_id: str,
        status: str,
        message: str,
        updated_at: str,
        max_attempts: int = 3,
    ) -> dict[str, Any]:
        """Update retrieval state with bounded ETag retries for duplicate workers."""

        normalized_case_id = _required_text(case_id, "case_id")
        normalized_status = _required_text(status, "status")
        attempts = int(max_attempts)
        if attempts < 1 or attempts > 10:
            raise ValueError("max_attempts must be from 1 to 10")
        for _attempt in range(attempts):
            item = self.get_case(container_name, normalized_case_id)
            if item is None:
                raise KeyError(f"case index item not found: {normalized_case_id}")
            etag = _required_text(item.get("_etag"), "case _etag")
            replacement = dict(item)
            replacement.update(
                {
                    "retrieval_status": normalized_status,
                    "retrieval_status_message": str(message or "")[:500],
                    "retrieval_updated_at": _required_text(updated_at, "updated_at"),
                }
            )
            outcome = self.replace_if_match(
                container_name,
                replacement,
                expected_etag=etag,
            )
            if outcome.applied:
                return outcome.item or replacement
            if outcome.outcome != "precondition_failed":
                raise KeyError(f"case index item not found: {normalized_case_id}")
        raise RuntimeError(
            f"case retrieval status update exhausted ETag retries: {normalized_case_id}"
        )

    def list_cases(
        self,
        container_name: str,
        *,
        limit: int,
        before: tuple[str, str] | None = None,
        start_date: str | None = None,
        end_date: str | None = None,
        verdict: str | None = None,
        search_name: str | None = None,
    ) -> list[dict[str, Any]]:
        """Return a bounded newest-first case page using application keysets."""

        bounded = _bounded_limit(limit, maximum=500)
        parameters: list[dict[str, Any]] = [{"name": "@limit", "value": bounded}]
        predicates: list[str] = []
        if before is not None:
            processed_at, case_id = before
            predicates.append(
                "(c.processed_at < @processed_at OR "
                "(c.processed_at = @processed_at AND c.case_id < @case_id))"
            )
            parameters.extend(
                [
                    {"name": "@processed_at", "value": _required_text(processed_at, "processed_at")},
                    {"name": "@case_id", "value": _required_text(case_id, "case_id")},
                ]
            )
        if start_date:
            predicates.append("c.processed_at >= @start_date")
            parameters.append({"name": "@start_date", "value": start_date})
        if end_date:
            predicates.append("c.processed_at <= @end_date")
            parameters.append({"name": "@end_date", "value": end_date})
        if verdict:
            predicates.append("LOWER(c.verdict) = @verdict")
            parameters.append({"name": "@verdict", "value": verdict.lower()})
        if search_name:
            predicates.append("CONTAINS(LOWER(c.search_name), @search_name)")
            parameters.append({"name": "@search_name", "value": search_name.lower()})
        predicate = f" WHERE {' AND '.join(predicates)}" if predicates else ""
        query = (
            "SELECT TOP @limit * FROM c"
            f"{predicate} ORDER BY c.processed_at DESC, c.case_id DESC"
        )
        return self._query(
            container_name,
            query=query,
            parameters=parameters,
            max_results=bounded,
            cross_partition=True,
            operation="list_cases",
        )

    def find_cases_by_correlation(
        self,
        container_name: str,
        *,
        correlation_id: str,
        limit: int = 10,
    ) -> list[dict[str, Any]]:
        """Return bounded newest-first case candidates across partitions."""

        bounded = _bounded_limit(limit, maximum=200)
        return self._query(
            container_name,
            query=(
                "SELECT TOP @limit * FROM c WHERE c.correlation_id = @correlation_id "
                "ORDER BY c.processed_at DESC, c.case_id DESC"
            ),
            parameters=[
                {"name": "@limit", "value": bounded},
                {"name": "@correlation_id", "value": _required_text(correlation_id, "correlation_id")},
            ],
            max_results=bounded,
            cross_partition=True,
            operation="find_cases_by_correlation",
        )

    def get_disposition(
        self,
        container_name: str,
        snow_sys_id: str,
    ) -> dict[str, Any] | None:
        normalized = _required_text(snow_sys_id, "snow_sys_id")
        return self.read_item(container_name, item_id=normalized, partition_key=normalized)

    def upsert_disposition(
        self,
        container_name: str,
        disposition: Mapping[str, Any],
    ) -> dict[str, Any]:
        body = dict(disposition)
        snow_sys_id = _required_text(body.get("snow_sys_id"), "snow_sys_id")
        body["id"] = snow_sys_id
        return self.upsert_item(container_name, body)

    def get_sync_checkpoint(
        self,
        container_name: str,
        job_name: str,
    ) -> dict[str, Any] | None:
        normalized = _required_text(job_name, "job_name")
        return self.read_item(container_name, item_id=normalized, partition_key=normalized)

    def upsert_sync_checkpoint(
        self,
        container_name: str,
        checkpoint: Mapping[str, Any],
    ) -> dict[str, Any]:
        body = dict(checkpoint)
        job_name = _required_text(body.get("job_name"), "job_name")
        body["id"] = job_name
        return self.upsert_item(container_name, body)

    def get_chat_session(
        self,
        container_name: str,
        *,
        session_id: str,
        user_id: str,
    ) -> dict[str, Any] | None:
        return self.read_item(
            container_name,
            item_id=_required_text(session_id, "session_id"),
            partition_key=_required_text(user_id, "user_id"),
        )

    def create_chat_session(
        self,
        container_name: str,
        session: Mapping[str, Any],
    ) -> CreateOutcome:
        body = dict(session)
        body["id"] = _required_text(body.get("session_id"), "session_id")
        _required_text(body.get("user_id"), "user_id")
        return self.create_if_absent(container_name, body)

    def upsert_chat_session(
        self,
        container_name: str,
        session: Mapping[str, Any],
    ) -> dict[str, Any]:
        body = dict(session)
        body["id"] = _required_text(body.get("session_id"), "session_id")
        _required_text(body.get("user_id"), "user_id")
        return self.upsert_item(container_name, body)

    def replace_chat_session_if_match(
        self,
        container_name: str,
        session: Mapping[str, Any],
        *,
        expected_etag: str,
    ) -> ConditionalOutcome:
        body = dict(session)
        body["id"] = _required_text(body.get("session_id"), "session_id")
        _required_text(body.get("user_id"), "user_id")
        return self.replace_if_match(
            container_name,
            body,
            expected_etag=expected_etag,
        )

    def list_chat_sessions(
        self,
        container_name: str,
        *,
        user_id: str,
        now_epoch: int,
        limit: int,
        oldest_first: bool = False,
    ) -> list[dict[str, Any]]:
        bounded = _bounded_limit(limit, maximum=101)
        direction = "ASC" if oldest_first else "DESC"
        return self._query(
            container_name,
            query=(
                "SELECT TOP @limit * FROM c WHERE c.user_id = @user_id "
                "AND c.expires_at_epoch > @now_epoch "
                f"ORDER BY c.updated_at {direction}, c.session_id {direction}"
            ),
            parameters=[
                {"name": "@limit", "value": bounded},
                {"name": "@user_id", "value": _required_text(user_id, "user_id")},
                {"name": "@now_epoch", "value": int(now_epoch)},
            ],
            max_results=bounded,
            partition_key=user_id,
            operation="list_chat_sessions",
        )

    def delete_chat_session(
        self,
        container_name: str,
        *,
        session_id: str,
        user_id: str,
    ) -> bool:
        container = self._container(container_name)
        try:
            self._call(
                container_name,
                "delete_chat_session",
                container.delete_item,
                item=session_id,
                partition_key=user_id,
            )
        except Exception as exc:
            if _status_code(exc) == 404:
                return False
            raise
        return True

    def create_chat_message(
        self,
        container_name: str,
        message: Mapping[str, Any],
    ) -> CreateOutcome:
        body = dict(message)
        body["id"] = _required_text(body.get("message_id"), "message_id")
        _required_text(body.get("session_id"), "session_id")
        return self.create_if_absent(container_name, body)

    def get_chat_message(
        self,
        container_name: str,
        *,
        session_id: str,
        message_id: str,
    ) -> dict[str, Any] | None:
        return self.read_item(
            container_name,
            item_id=_required_text(message_id, "message_id"),
            partition_key=_required_text(session_id, "session_id"),
        )

    def list_chat_messages(
        self,
        container_name: str,
        *,
        session_id: str,
        limit: int,
    ) -> list[dict[str, Any]]:
        bounded = _bounded_limit(limit, maximum=200)
        return self._query(
            container_name,
            query=(
                "SELECT TOP @limit * FROM c WHERE c.session_id = @session_id "
                "ORDER BY c.created_at ASC, c.message_id ASC"
            ),
            parameters=[
                {"name": "@limit", "value": bounded},
                {"name": "@session_id", "value": _required_text(session_id, "session_id")},
            ],
            max_results=bounded,
            partition_key=session_id,
            operation="list_chat_messages",
        )

    def delete_chat_message(
        self,
        container_name: str,
        *,
        session_id: str,
        message_id: str,
    ) -> bool:
        container = self._container(container_name)
        try:
            self._call(
                container_name,
                "delete_chat_message",
                container.delete_item,
                item=message_id,
                partition_key=session_id,
            )
        except Exception as exc:
            if _status_code(exc) == 404:
                return False
            raise
        return True

    def delete_chat_messages(
        self,
        container_name: str,
        *,
        session_id: str,
        limit: int = 200,
    ) -> int:
        """Delete a bounded set of messages for a session."""

        rows = self.list_chat_messages(container_name, session_id=session_id, limit=limit)
        for row in rows:
            self.delete_chat_message(
                container_name,
                session_id=session_id,
                message_id=_required_text(row.get("message_id"), "message_id"),
            )
        return len(rows)

    def _container(self, name: str) -> Any:
        return self.database.get_container_client(_required_text(name, "container_name"))

    def _prepare_item(self, item: Mapping[str, Any]) -> dict[str, Any]:
        body = dict(item)
        for system_field in ("_etag", "_rid", "_self", "_attachments", "_ts"):
            body.pop(system_field, None)
        _required_text(body.get("id"), "id")
        expiry_epoch = _expiry_epoch(body)
        if expiry_epoch is not None:
            body["ttl"] = ttl_from_expiry(expiry_epoch, now_epoch=int(self._clock()))
        return body

    def _query(
        self,
        container_name: str,
        *,
        query: str,
        parameters: list[dict[str, Any]],
        max_results: int,
        operation: str,
        partition_key: str | None = None,
        cross_partition: bool = False,
    ) -> list[dict[str, Any]]:
        container = self._container(container_name)
        kwargs: dict[str, Any] = {
            "query": query,
            "parameters": parameters,
            "max_item_count": max_results,
        }
        if partition_key is not None:
            kwargs["partition_key"] = partition_key
        if cross_partition:
            kwargs["enable_cross_partition_query"] = True
        results = self._call(
            container_name,
            operation,
            lambda **call_kwargs: list(container.query_items(**call_kwargs))[:max_results],
            **kwargs,
        )
        return [_plain_item(item) for item in results]

    def _call(
        self,
        container_name: str,
        operation: str,
        function: Callable[..., Any],
        **kwargs: Any,
    ) -> Any:
        started = self._perf_counter()
        request_charge = 0.0

        def response_hook(headers: Mapping[str, Any], _response: Any) -> None:
            nonlocal request_charge
            request_charge += _request_charge(headers)

        kwargs["response_hook"] = response_hook
        try:
            return function(**kwargs)
        finally:
            latency_ms = max(0.0, (self._perf_counter() - started) * 1000.0)
            self._logger.info(
                "cosmos_request operation=%s container=%s request_charge=%s latency_ms=%.3f",
                operation,
                container_name,
                request_charge,
                latency_ms,
                extra={
                    "cosmos_operation": operation,
                    "cosmos_container": container_name,
                    "cosmos_request_charge": request_charge,
                    "cosmos_latency_ms": latency_ms,
                },
            )


def _plain_item(item: Any) -> dict[str, Any]:
    if not isinstance(item, Mapping):
        raise TypeError("Cosmos item response must be an object")
    return dict(item)


def _required_text(value: Any, field_name: str) -> str:
    text = str(value or "").strip()
    if not text:
        raise ValueError(f"{field_name} is required")
    return text


def _bounded_limit(value: int, *, maximum: int) -> int:
    limit = int(value)
    if limit < 1:
        raise ValueError("limit must be positive")
    return min(limit, maximum)


def _status_code(exc: Exception) -> int | None:
    value = getattr(exc, "status_code", None)
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _expiry_epoch(item: Mapping[str, Any]) -> int | None:
    if item.get("expires_at_epoch") is not None:
        try:
            return int(item["expires_at_epoch"])
        except (TypeError, ValueError) as exc:
            raise ValueError("expires_at_epoch must be an integer epoch") from exc
    value = item.get("expires_at")
    if value is None or value == "":
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        pass
    try:
        return int(datetime.fromisoformat(str(value).replace("Z", "+00:00")).timestamp())
    except (TypeError, ValueError) as exc:
        raise ValueError("expires_at must be an epoch or ISO 8601 timestamp") from exc


def _request_charge(headers: Mapping[str, Any]) -> float:
    raw = headers.get("x-ms-request-charge", 0.0)
    try:
        return float(raw)
    except (TypeError, ValueError):
        return 0.0


__all__ = [
    "CONTAINER_PARTITION_KEYS",
    "ConditionalOutcome",
    "CosmosStore",
    "CreateOutcome",
    "ttl_from_expiry",
]
