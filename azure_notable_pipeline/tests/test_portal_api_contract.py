"""Live native handler payload alignment with the unchanged portal models."""

from __future__ import annotations

import json

from azure_notable_pipeline import portal_handler
from azure_notable_pipeline.portal_api_models import (
    CaseListResponse,
    HealthResponse,
    portal_response,
)

from test_portal_handler import FakeCosmosStore, portal_config, request


def _authorize(monkeypatch) -> None:
    monkeypatch.setattr(portal_handler, "load_config", lambda: portal_config())
    monkeypatch.setattr(portal_handler, "_cosmos_store", lambda _config: FakeCosmosStore())
    monkeypatch.setattr(
        portal_handler,
        "validate_portal_jwt",
        lambda *_args, **_kwargs: {"sub": "user-1", "roles": ["Case.Reader"]},
    )


def test_health_payload_validates_against_shared_response_model(monkeypatch) -> None:
    _authorize(monkeypatch)
    response = portal_handler.handle_request(request("/health"))
    payload = json.loads(response.get_body())

    assert portal_response(HealthResponse, payload).model_dump(mode="json") == payload


def test_case_list_payload_validates_against_shared_response_model(monkeypatch) -> None:
    _authorize(monkeypatch)
    response = portal_handler.handle_request(request("/api/cases"))
    payload = json.loads(response.get_body())

    assert portal_response(CaseListResponse, payload).model_dump(mode="json") == payload
