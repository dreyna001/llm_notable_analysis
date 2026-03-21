"""Shared test utilities."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional


@dataclass
class FakeResponse:
    """Minimal response double for SDK client unit tests."""

    status_code: int
    json_payload: Optional[Dict[str, Any]] = None
    text: str = ""
    headers: Dict[str, str] = field(default_factory=dict)

    def json(self) -> Dict[str, Any]:
        """Return fake JSON payload.

        Returns:
            JSON payload configured for this fake response.

        Raises:
            ValueError: If no JSON payload was configured.
        """
        if self.json_payload is None:
            raise ValueError("No JSON payload")
        return self.json_payload


@dataclass
class FakeSession:
    """Minimal session double with queued responses/exceptions."""

    responses: List[FakeResponse] = field(default_factory=list)
    exceptions: List[Exception] = field(default_factory=list)
    call_count: int = 0

    def post(self, *args, **kwargs) -> FakeResponse:
        """Return queued fake response or raise queued exception.

        Args:
            *args: Positional args (unused in fake implementation).
            **kwargs: Keyword args (unused in fake implementation).

        Returns:
            Next queued `FakeResponse`.

        Raises:
            Exception: Next queued exception when configured.
            RuntimeError: If neither responses nor exceptions are queued.
        """
        del args, kwargs
        self.call_count += 1
        if self.exceptions:
            raise self.exceptions.pop(0)
        if not self.responses:
            raise RuntimeError("No fake responses configured")
        return self.responses.pop(0)
