#!/usr/bin/env python3
"""Idempotently provision the local Azurite and Cosmos DB contracts."""

from __future__ import annotations

import argparse
import base64
import binascii
import ipaddress
import os
import time
from pathlib import Path
from typing import Callable
from urllib.parse import urlparse


STORAGE_CONTAINERS = ("input", "output")
STORAGE_QUEUES = (
    "notable-analysis-jobs",
    "notable-analysis-jobs-poison",
    "case-embed-invocations",
    "case-embed-invocations-poison",
    "webjobs-blobtrigger-poison",
)
COSMOS_CONTAINERS = (
    ("SIDE_EFFECT_IDEMPOTENCY_CONTAINER", "notable-side-effect-idempotency", "/id", -1),
    ("CASE_INDEX_CONTAINER", "local-case-index", "/case_id", -1),
    ("DISPOSITION_CONTAINER", "local-servicenow-dispositions", "/snow_sys_id", -1),
    ("DISPOSITION_SYNC_STATE_CONTAINER", "local-disposition-sync-state", "/job_name", None),
    ("CHAT_SESSIONS_CONTAINER", "local-chat-sessions", "/user_id", -1),
    ("CHAT_MESSAGES_CONTAINER", "local-chat-messages", "/session_id", -1),
)


def _load_env(path: Path) -> None:
    if not path.is_file():
        raise SystemExit(f"Local environment file not found: {path}")
    for line_number, raw_line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        name, separator, value = line.partition("=")
        if not separator or not name.strip():
            raise SystemExit(f"Invalid environment entry at {path}:{line_number}")
        os.environ[name.strip()] = value.strip()


def _require_local_url(value: str, name: str) -> str:
    parsed = urlparse(value)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        raise SystemExit(f"{name} must be a loopback HTTP(S) URL")
    try:
        address = ipaddress.ip_address(parsed.hostname)
    except ValueError:
        is_local = parsed.hostname.lower() == "localhost"
    else:
        is_local = address.is_loopback
    if not is_local or parsed.username or parsed.password or parsed.query or parsed.fragment:
        raise SystemExit(f"{name} must be a loopback HTTP(S) URL")
    return value


def _validate_local_contract() -> None:
    if os.getenv("LOCAL_EMULATION", "").strip().lower() != "true":
        raise SystemExit("LOCAL_EMULATION=true is required for emulator bootstrap")
    connection_string = _required("AZURITE_CONNECTION_STRING")
    if connection_string.strip().lower() != "usedevelopmentstorage=true":
        endpoints = {
            name.strip().lower(): value.strip()
            for component in connection_string.split(";")
            if (separator := component.partition("="))[1]
            for name, value in [(separator[0], separator[2])]
        }
        for required_endpoint in ("blobendpoint", "queueendpoint"):
            _require_local_url(
                endpoints.get(required_endpoint, ""),
                f"AZURITE_CONNECTION_STRING {required_endpoint}",
            )
    _require_local_url(_required("COSMOS_ENDPOINT"), "COSMOS_ENDPOINT")
    emulator_key = _required("COSMOS_EMULATOR_KEY")
    try:
        base64.b64decode(emulator_key, validate=True)
    except (binascii.Error, ValueError) as exc:
        raise SystemExit("COSMOS_EMULATOR_KEY must be valid base64") from exc


def _required(name: str, default: str = "") -> str:
    value = os.getenv(name, default).strip()
    if not value:
        raise SystemExit(f"{name} is required")
    return value


def _retry(label: str, operation: Callable[[], None], timeout_seconds: int = 120) -> None:
    deadline = time.monotonic() + timeout_seconds
    while True:
        try:
            operation()
            return
        except Exception as exc:
            if time.monotonic() >= deadline:
                raise RuntimeError(f"Timed out provisioning {label}") from exc
            time.sleep(2)


def _provision_storage_idempotently() -> None:
    from azure.core.exceptions import ResourceExistsError
    from azure.storage.blob import BlobServiceClient
    from azure.storage.queue import QueueServiceClient

    connection_string = _required("AZURITE_CONNECTION_STRING", "UseDevelopmentStorage=true")
    blob_service = BlobServiceClient.from_connection_string(
        connection_string, api_version="2023-11-03"
    )
    queue_service = QueueServiceClient.from_connection_string(
        connection_string, api_version="2023-11-03"
    )
    for name in STORAGE_CONTAINERS:
        try:
            blob_service.create_container(name)
        except ResourceExistsError:
            pass
        print(f"Azurite container ready: {name}")
    for name in STORAGE_QUEUES:
        try:
            queue_service.create_queue(name)
        except ResourceExistsError:
            pass
        print(f"Azurite queue ready: {name}")


def _provision_cosmos() -> None:
    from azure.cosmos import CosmosClient, PartitionKey

    client = CosmosClient(
        _required("COSMOS_ENDPOINT", "http://127.0.0.1:8081"),
        credential=_required("COSMOS_EMULATOR_KEY"),
    )
    database_name = _required("COSMOS_DATABASE_NAME", "notable-local")
    database = client.create_database_if_not_exists(database_name)
    print(f"Cosmos database ready: {database_name}")
    for setting_name, default_name, partition_path, default_ttl in COSMOS_CONTAINERS:
        container_name = _required(setting_name, default_name)
        database.create_container_if_not_exists(
            id=container_name,
            partition_key=PartitionKey(path=partition_path),
            default_ttl=default_ttl,
        )
        print(f"Cosmos container ready: {container_name} ({partition_path})")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--env-file", type=Path, required=True)
    args = parser.parse_args()
    _load_env(args.env_file)
    _validate_local_contract()
    _retry("Azurite resources", _provision_storage_idempotently)
    _retry("Cosmos DB resources", _provision_cosmos)


if __name__ == "__main__":
    main()
