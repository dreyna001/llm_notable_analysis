"""Local filesystem JSON transport seam for the on-prem deployment wrapper."""

from __future__ import annotations

import json
from pathlib import Path
import shutil
from typing import Any, Mapping, Protocol


class LocalJsonFileTransport(Protocol):
    """Protocol for on-prem JSON reads, writes, moves, and file discovery."""

    def list_json_files(self, directory: str) -> tuple[Path, ...]:
        """Return discovered JSON files for one directory."""

    def read_json_file(self, path: str | Path) -> Mapping[str, Any]:
        """Load and return one JSON object from a file path."""

    def write_json_file(self, path: str | Path, payload: Mapping[str, Any]) -> None:
        """Write one JSON object to a file path."""

    def move_file(self, source_path: str | Path, destination_path: str | Path) -> Path:
        """Move one file to a destination path and return the final path."""


class StdlibLocalJsonFileTransport:
    """Stdlib-backed local JSON transport implementation."""

    def list_json_files(self, directory: str) -> tuple[Path, ...]:
        """Return sorted `.json` files for one directory."""
        directory_path = Path(directory)
        if not directory_path.exists():
            return ()
        return tuple(sorted(path for path in directory_path.iterdir() if path.is_file() and path.suffix == ".json"))

    def read_json_file(self, path: str | Path) -> Mapping[str, Any]:
        """Load and validate one JSON object from local disk."""
        path_obj = Path(path)
        raw_text = path_obj.read_text(encoding="utf-8")
        try:
            payload = json.loads(raw_text)
        except json.JSONDecodeError as exc:
            raise ValueError(f"File {path_obj} did not contain valid JSON.") from exc
        if not isinstance(payload, Mapping):
            raise ValueError(f"File {path_obj} must contain a JSON object.")
        return dict(payload)

    def write_json_file(self, path: str | Path, payload: Mapping[str, Any]) -> None:
        """Serialize and write one JSON object to local disk."""
        path_obj = Path(path)
        path_obj.parent.mkdir(parents=True, exist_ok=True)
        path_obj.write_text(
            json.dumps(payload, sort_keys=True, indent=2) + "\n",
            encoding="utf-8",
        )

    def move_file(self, source_path: str | Path, destination_path: str | Path) -> Path:
        """Move one local file into the destination path."""
        source = Path(source_path)
        destination = Path(destination_path)
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(source), str(destination))
        return destination
