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
        "disposition_sync_timer",
        "operations_monitor_timer",
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

    timer_binding = registered["disposition_sync_timer"].get_bindings()[0].get_dict_repr()
    assert timer_binding["type"] == "timerTrigger"
    assert timer_binding["name"] == "timer"
    assert timer_binding["schedule"] == "0 0 0 * * *"
    assert timer_binding["runOnStartup"] is False
    assert timer_binding["useMonitor"] is True

    monitor_binding = registered["operations_monitor_timer"].get_bindings()[0].get_dict_repr()
    assert monitor_binding["type"] == "timerTrigger"
    assert monitor_binding["name"] == "timer"
    assert monitor_binding["schedule"] == "0 */5 * * * *"
    assert monitor_binding["runOnStartup"] is False
    assert monitor_binding["useMonitor"] is True


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


def test_disposition_timer_wrapper_passes_native_timer_request(monkeypatch) -> None:
    timer = SimpleNamespace(past_due=False)
    calls = []
    monkeypatch.setattr(function_app, "handle_timer", lambda value: calls.append(value))

    function_app.disposition_sync_timer(timer)

    assert calls == [timer]


def test_operations_monitor_wrapper_polls_native_queues(monkeypatch) -> None:
    calls = []
    monkeypatch.setattr(function_app, "emit_queue_depth_traces", lambda: calls.append("poll"))

    function_app.operations_monitor_timer(SimpleNamespace(past_due=False))

    assert calls == ["poll"]
