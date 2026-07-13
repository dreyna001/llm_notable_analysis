"""Azure-native runtime entrypoint for ServiceNow disposition synchronization."""

from __future__ import annotations

import argparse
import json
import logging
from datetime import datetime
from typing import Any, Callable, Mapping

from .azure_clients import blob_service_client
from .config import Config, load_config
from .cosmos_store import CosmosStore
from .servicenow_disposition_sync import run_disposition_sync

logger = logging.getLogger(__name__)


class DispositionSyncInvocationError(RuntimeError):
    """A sync pass failed and the Azure invocation must be marked failed."""


SyncWorkflow = Callable[..., dict[str, Any]]


class _DryRunCosmosStore:
    """Simulate disposition writes in memory while delegating native reads.

    Keeping an overlay makes repeated rows within one dry run observe the same
    state they would observe after a real upsert. No Cosmos mutation or cursor
    advancement reaches the underlying store.
    """

    def __init__(self, store: CosmosStore) -> None:
        self._store = store
        self._dispositions: dict[tuple[str, str], dict[str, Any]] = {}
        self._checkpoints: dict[tuple[str, str], dict[str, Any]] = {}

    def get_disposition(self, container_name: str, snow_sys_id: str) -> dict[str, Any] | None:
        key = (container_name, snow_sys_id)
        if key in self._dispositions:
            return dict(self._dispositions[key])
        return self._store.get_disposition(container_name, snow_sys_id)

    def upsert_disposition(
        self,
        container_name: str,
        disposition: Mapping[str, Any],
    ) -> dict[str, Any]:
        body = dict(disposition)
        snow_sys_id = str(body.get("snow_sys_id") or "").strip()
        if not snow_sys_id:
            raise ValueError("snow_sys_id is required")
        body["id"] = snow_sys_id
        self._dispositions[(container_name, snow_sys_id)] = body
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

    def find_cases_by_correlation(self, *args: Any, **kwargs: Any) -> list[dict[str, Any]]:
        return self._store.find_cases_by_correlation(*args, **kwargs)

    def list_cases(self, *args: Any, **kwargs: Any) -> list[dict[str, Any]]:
        return self._store.list_cases(*args, **kwargs)


def invoke_disposition_sync(
    *,
    dry_run: bool = False,
    config: Config | None = None,
    cosmos_store: CosmosStore | None = None,
    blob_service: Any | None = None,
    http_session: Any | None = None,
    now: datetime | None = None,
    workflow: SyncWorkflow | None = None,
) -> dict[str, Any]:
    """Run one native sync pass for a timer or an explicit manual invocation.

    ``dry_run`` performs the same reads, mapping, linking, and outcome counting
    while intercepting disposition and checkpoint writes in memory.
    """

    runtime_config = config or load_config()
    selected_workflow = workflow or run_disposition_sync
    if not runtime_config.SERVICENOW_DISPOSITION_SYNC_ENABLED:
        return selected_workflow(
            config=runtime_config,
            cosmos_store=cosmos_store,
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
        logger.warning("ServiceNow disposition sync timer invocation is past due")
    result = invoke_disposition_sync()
    if result.get("status") == "error":
        message = str(result.get("message") or "ServiceNow disposition sync failed")
        logger.error("ServiceNow disposition sync failed: %s", message)
        raise DispositionSyncInvocationError(message)
    logger.info("ServiceNow disposition sync invocation completed: %s", result)
    return result


def main(argv: list[str] | None = None) -> int:
    """Support an explicit operator invocation without an AWS event envelope."""

    parser = argparse.ArgumentParser(description="Run ServiceNow disposition synchronization")
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="read and evaluate rows without writing dispositions or the checkpoint",
    )
    args = parser.parse_args(argv)
    result = invoke_disposition_sync(dry_run=args.dry_run)
    print(json.dumps(result, sort_keys=True))
    return 1 if result.get("status") == "error" else 0


if __name__ == "__main__":  # pragma: no cover - exercised by the installed module entrypoint.
    raise SystemExit(main())


__all__ = [
    "DispositionSyncInvocationError",
    "handle_timer",
    "invoke_disposition_sync",
    "main",
]
