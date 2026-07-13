"""Runtime registration tests for Azure Functions wrappers."""

from __future__ import annotations

from types import SimpleNamespace

from azure_notable_pipeline import function_app


def _registered_functions():
    return {
        function.get_function_name(): function
        for function in function_app.app.get_functions()
    }


def test_runtime_enumerates_native_wrappers_with_bicep_function_names() -> None:
    registered = _registered_functions()

    assert set(registered) == {
        "intake_blob",
        "analyzer_queue",
        "case_embed_queue",
        "portal_http",
    }
    binding = registered["case_embed_queue"].get_bindings()[0].get_dict_repr()
    assert binding["type"] == "queueTrigger"
    assert binding["name"] == "message"
    assert binding["queueName"] == "%CASE_EMBED_QUEUE_NAME%"
    assert binding["connection"] == "OutputStorage"

    portal_binding = registered["portal_http"].get_bindings()[0].get_dict_repr()
    assert portal_binding["type"] == "httpTrigger"
    assert portal_binding["route"] == "{*path}"
    assert (
        getattr(portal_binding["authLevel"], "value", portal_binding["authLevel"])
        == "anonymous"
    )


def test_case_embed_wrapper_passes_raw_queue_body_to_strict_dispatcher(monkeypatch) -> None:
    calls = []
    monkeypatch.setattr(
        function_app,
        "dispatch_embed_queue_message",
        lambda payload: calls.append(payload),
    )

    function_app.case_embed_queue(
        SimpleNamespace(get_body=lambda: b'{"schema_version":1}')
    )

    assert calls == [b'{"schema_version":1}']


def test_portal_wrapper_passes_native_http_request(monkeypatch) -> None:
    request = SimpleNamespace(method="GET")
    response = object()
    monkeypatch.setattr(
        function_app,
        "handle_request",
        lambda value: response if value is request else None,
    )

    assert function_app.portal_http(request) is response
