"""Runtime registration tests for Azure Functions wrappers."""

from __future__ import annotations

from types import SimpleNamespace

from azure_notable_pipeline import function_app


def _registered_functions():
    return {
        function.get_function_name(): function
        for function in function_app.app.get_functions()
    }


def test_runtime_enumerates_phase1_wrappers_with_bicep_function_names() -> None:
    registered = _registered_functions()

    assert set(registered) == {"intake_blob", "analyzer_queue", "case_embed_queue"}
    binding = registered["case_embed_queue"].get_bindings()[0].get_dict_repr()
    assert binding["type"] == "queueTrigger"
    assert binding["name"] == "message"
    assert binding["queueName"] == "%CASE_EMBED_QUEUE_NAME%"
    assert binding["connection"] == "OutputStorage"


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
