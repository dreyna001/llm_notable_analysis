"""Shared test utilities."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional


@dataclass
class FakeResponse:
    status_code: int
    json_payload: Optional[Dict[str, Any]] = None
    text: str = ""
    headers: Dict[str, str] = field(default_factory=dict)

    def json(self) -> Dict[str, Any]:
        if self.json_payload is None:
            raise ValueError("No JSON payload")
        return self.json_payload


@dataclass
class FakeSession:
    responses: List[FakeResponse] = field(default_factory=list)
    exceptions: List[Exception] = field(default_factory=list)
    call_count: int = 0

    def post(self, *args, **kwargs) -> FakeResponse:
        del args, kwargs
        self.call_count += 1
        if self.exceptions:
            raise self.exceptions.pop(0)
        if not self.responses:
            raise RuntimeError("No fake responses configured")
        return self.responses.pop(0)

