"""Test bootstrap for local imports and fail-closed offline execution."""

from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[1]
WORKSPACE_ROOT = PROJECT_ROOT.parent

# Unit and contract tests must never download models, packages, or remote data.
# Install/prestage scripts own dependency and model acquisition. These settings
# make supported Hugging Face clients fail closed when content is not cached.
_OFFLINE_ENV = {
    "AWS_EC2_METADATA_DISABLED": "true",
    "DO_NOT_TRACK": "1",
    "HF_DATASETS_OFFLINE": "1",
    "HF_HUB_DISABLE_TELEMETRY": "1",
    "HF_HUB_OFFLINE": "1",
    "TRANSFORMERS_OFFLINE": "1",
    "WANDB_DISABLED": "true",
    "WANDB_MODE": "disabled",
}
for key, value in _OFFLINE_ENV.items():
    os.environ[key] = value


def _deny_network(event: str, args: tuple[Any, ...]) -> None:
    """Reject TCP/IP resolution and connections made by unit tests."""
    host: Any = None
    if event == "socket.getaddrinfo" and args:
        host = args[0]
    elif event == "socket.connect" and len(args) >= 2:
        address = args[1]
        if isinstance(address, tuple) and address:
            host = address[0]
        else:
            # Unix-domain sockets use filesystem path strings and are local.
            return
    else:
        return
    raise RuntimeError(f"Network access is prohibited during tests: {host!r}")


sys.addaudithook(_deny_network)

for path in (PROJECT_ROOT / "src", WORKSPACE_ROOT):
    path_str = str(path)
    if path_str not in sys.path:
        sys.path.insert(0, path_str)
