"""Azure-native runtime entrypoint for ServiceNow closed ticket synchronization."""

from __future__ import annotations

import argparse
import json
import logging
from datetime import datetime
from typing import Any, Callable, Mapping

from .azure_clients import blob_service_client
from .config import Config, load_config
from .cosmos_store import CosmosStore
from .servicenow_closed_ticket_sync import run_closed_ticket_sync

logger = logging.getLogger(__name__)


class ClosedTicketSyncInvocationError(RuntimeError):
    """A sync pass failed and the Azure invocation must be marked failed."""


SyncWorkflow = Callable[..., dict[str, Any]]


class _DryRunCosmosStore:
    """Simulate closed-ticket writes in memory while delegating native reads."""

    def __init__(self, store: CosmosStore) -> None:
        self._store = store
        self._tickets: dict[tuple[str, str], dict[str, Any]] = {}
        self._checkpoints: dict[tuple[str, str], dict[str, Any]] = {}

    def get_closed_ticket(self, container_name: str, ticket_id: str) -> dict[str, Any] | None:
        key = (container_name, ticket_id)
        if key in self._tickets:
            return dict(self._tickets[key])
        return self._store.get_closed_ticket(container_name, ticket_id)

    def upsert_closed_ticket(
        self,
        container_name: str,
        ticket: Mapping[str, Any],
    ) -> dict[str, Any]:
        body = dict(ticket)
        ticket_id = str(body.get("ticket_id") or "").strip()
        if not ticket_id:
            raise ValueError("ticket_id is required")
        body["id"] = ticket_id
        self._tickets[(container_name, ticket_id)] = body
        return dict(body)

    def get_sync_checkpoint(self, container_name: str, job_name: str) -> dict[str, Any] | None:
        key = (container_name, job_name)
        if key in self._checkpoints:
            return dict(self._checkpoints[key])
        return self._store.get_sync_checkpoint(container_name, job_name)

    def upsert_sync_checkpoint(
        self,
        container_name: str,
        checkpoint: Mapping[str, Any],
    ) -> dict[str, Any]:
        body = dict(checkpoint)
        job_name = str(body.get("job_name") or "").strip()
        if not job_name:
            raise ValueError("job_name is required")
        body["id"] = job_name
        self._checkpoints[(container_name, job_name)] = body
        return dict(body)

    def list_expired_closed_tickets(self, *args: Any, **kwargs: Any) -> list[dict[str, Any]]:
        return self._store.list_expired_closed_tickets(*args, **kwargs)

    def list_active_closed_tickets_updated_since(self, *args: Any, **kwargs: Any) -> list[dict[str, Any]]:
        return self._store.list_active_closed_tickets_updated_since(*args, **kwargs)

    def deactivate_closed_ticket(self, *args: Any, **kwargs: Any) -> dict[str, Any] | None:
        return None

    def delete_closed_ticket(self, *args: Any, **kwargs: Any) -> bool:
        return False


def invoke_closed_ticket_sync(
    *,
    dry_run: bool = False,
    config: Config | None = None,
    cosmos_store: CosmosStore | None = None,
    blob_service: Any | None = None,
    http_session: Any | None = None,
    now: datetime | None = None,
    workflow: SyncWorkflow | None = None,
) -> dict[str, Any]:
    """Run one native closed-ticket sync pass for a timer or manual invocation."""

    runtime_config = config or load_config()
    selected_workflow = workflow or run_closed_ticket_sync
    if not runtime_config.SERVICENOW_CLOSED_TICKET_SYNC_ENABLED:
        return selected_workflow(
            config=runtime_config,
            cosmos_store=cosmos_store,  # type: ignore[arg-type]
            blob_service=blob_service,
            http_session=http_session,
            now=now,
        )

    persistence = cosmos_store or CosmosStore.from_config(runtime_config)
    archive_blob_service = blob_service
    if archive_blob_service is None and runtime_config.OUTPUT_STORAGE_ACCOUNT_URL.strip():
        archive_blob_service = blob_service_client(runtime_config.OUTPUT_STORAGE_ACCOUNT_URL)

    selected_store: Any = _DryRunCosmosStore(persistence) if dry_run else persistence
    result = selected_workflow(
        config=runtime_config,
        cosmos_store=selected_store,
        blob_service=archive_blob_service,
        http_session=http_session,
        now=now,
    )
    if not dry_run:
        return result

    dry_run_result = dict(result)
    would_advance = bool(dry_run_result.get("cursor_advanced"))
    dry_run_result.update(
        {
            "dry_run": True,
            "would_advance_cursor": would_advance,
            "cursor_advanced": False,
        }
    )
    if dry_run_result.get("status") != "error":
        dry_run_result["message"] = "dry run; no Cosmos writes or checkpoint advancement performed"
    return dry_run_result


def handle_timer(timer: Any) -> dict[str, Any]:
    """Handle one native ``azure.functions.TimerRequest`` invocation."""

    if bool(getattr(timer, "past_due", False)):
        logger.warning("ServiceNow closed ticket sync timer invocation is past due")
    result = invoke_closed_ticket_sync()
    if result.get("status") == "error":
        message = str(result.get("message") or result.get("errors") or "ServiceNow closed ticket sync failed")
        logger.error("ServiceNow closed ticket sync failed: %s", message)
        raise ClosedTicketSyncInvocationError(str(message))
    logger.info("ServiceNow closed ticket sync invocation completed: %s", result)
    return result


def main(argv: list[str] | None = None) -> int:
    """Support an explicit operator invocation without an Azure event envelope."""

    parser = argparse.ArgumentParser(description="Run ServiceNow closed ticket synchronization")
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="read and evaluate rows without writing tickets or the checkpoint",
    )
    args = parser.parse_args(argv)
    result = invoke_closed_ticket_sync(dry_run=args.dry_run)
    print(json.dumps(result, sort_keys=True))
    return 1 if result.get("status") == "error" else 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())


__all__ = [
    "ClosedTicketSyncInvocationError",
    "handle_timer",
    "invoke_closed_ticket_sync",
    "main",
]
