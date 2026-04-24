"""Deterministic tests for the on-prem LiteLLM core runner."""

from __future__ import annotations

import json
from pathlib import Path
import tempfile
from typing import Any, Mapping
import unittest
from urllib.error import URLError

from updated_notable_analysis.core.context import ContextBundle
from updated_notable_analysis.core.models import AdvisoryContextSnippet, NormalizedAlert
from updated_notable_analysis.onprem.config import OnPremRuntimeConfig
from updated_notable_analysis.onprem.runner import OnPremLiteLlmCoreRunner, StdlibLiteLlmTransport


class _FakeLiteLlmTransport:
    """In-memory LiteLLM transport test double."""

    def __init__(self, response: Mapping[str, Any]) -> None:
        self.response = response
        self.calls: list[dict[str, Any]] = []

    def post_json(
        self,
        url: str,
        payload: Mapping[str, Any],
        *,
        timeout_seconds: int,
    ) -> Mapping[str, Any]:
        self.calls.append(
            {
                "url": url,
                "payload": dict(payload),
                "timeout_seconds": timeout_seconds,
            }
        )
        return self.response


class _FakeContextProvider:
    """Advisory context provider test double."""

    def __init__(self, snippets: tuple[AdvisoryContextSnippet, ...]) -> None:
        self.snippets = snippets
        self.calls: list[dict[str, object]] = []

    def get_advisory_context(
        self, normalized_alert: NormalizedAlert, context_bundle: ContextBundle
    ) -> tuple[AdvisoryContextSnippet, ...]:
        self.calls.append(
            {
                "source_record_ref": normalized_alert.source_record_ref,
                "context_bundle_name": context_bundle.bundle_name,
            }
        )
        return self.snippets


class TestOnPremLiteLlmCoreRunner(unittest.TestCase):
    """Behavior-focused tests for LiteLLM-backed report generation."""

    def _alert(self) -> NormalizedAlert:
        """Return a valid normalized alert fixture."""
        return NormalizedAlert(
            schema_version="1.0",
            source_system="splunk",
            source_type="notable",
            source_record_ref="notable-123",
            received_at="2026-04-21T10:11:12Z",
            raw_content_type="json",
            raw_content='{"event":"failed_auth","user":"jdoe"}',
        )

    def _config(self) -> OnPremRuntimeConfig:
        """Return a valid runner config fixture."""
        return OnPremRuntimeConfig(
            incoming_dir="/var/notables/incoming",
            processed_dir="/var/notables/processed",
            quarantine_dir="/var/notables/quarantine",
            report_output_dir="/var/notables/reports",
            default_customer_bundle_name="acme_default",
            litellm_base_url="http://127.0.0.1:4000",
            litellm_chat_completions_path="/v1/chat/completions",
            litellm_model_name="gemma-4-31B-it",
            litellm_request_timeout_seconds=13,
        )

    def _valid_litellm_response(self) -> dict[str, object]:
        """Return an OpenAI-compatible response carrying an AnalysisReport JSON object."""
        report = {
            "schema_version": "1.0",
            "alert_reconciliation": {"status": "triaged"},
            "competing_hypotheses": [
                {
                    "hypothesis_type": "adversary",
                    "hypothesis": "Credential misuse activity is likely.",
                    "evidence_support": ["failed authentication pattern"],
                    "evidence_gaps": ["endpoint process context pending"],
                }
            ],
            "evidence_sections": [
                {
                    "evidence_type": "alert_direct",
                    "summary": "Alert evidence indicates suspicious authentication behavior.",
                }
            ],
            "ioc_extraction": {"users": ["jdoe"]},
            "ttp_analysis": [{"technique_id": "T1110", "confidence": "medium"}],
            "advisory_context_refs": ["kb://soc/sop/auth-42"],
        }
        return {"choices": [{"message": {"content": json.dumps(report)}}]}

    def test_runner_calls_litellm_chat_completions_and_returns_report(self) -> None:
        """Runner should send assembled prompts to LiteLLM and validate the report."""
        transport = _FakeLiteLlmTransport(self._valid_litellm_response())
        context_provider = _FakeContextProvider(
            (
                AdvisoryContextSnippet(
                    source_type="sop",
                    source_id="auth-42",
                    title="Authentication SOP",
                    content="Escalate repeated suspicious failed authentications.",
                    provenance_ref="kb://soc/sop/auth-42",
                ),
            )
        )
        runner = OnPremLiteLlmCoreRunner(
            config=self._config(),
            transport=transport,
            context_provider=context_provider,
        )

        report = runner.run(
            self._alert(),
            profile_name="analysis_only",
            customer_bundle_name=None,
        )

        self.assertEqual(report.schema_version, "1.0")
        self.assertEqual(report.advisory_context_refs, ("kb://soc/sop/auth-42",))
        self.assertEqual(len(transport.calls), 1)
        call = transport.calls[0]
        self.assertEqual(call["url"], "http://127.0.0.1:4000/v1/chat/completions")
        self.assertEqual(call["timeout_seconds"], 13)
        payload = call["payload"]
        self.assertEqual(payload["model"], "gemma-4-31B-it")
        self.assertEqual(payload["response_format"], {"type": "json_object"})
        self.assertEqual(payload["temperature"], 0)
        self.assertIn("Authentication SOP", payload["messages"][1]["content"])
        self.assertIn("failed_auth", payload["messages"][1]["content"])
        self.assertEqual(payload["metadata"]["customer_bundle_name"], "acme_default")
        self.assertEqual(context_provider.calls[0]["context_bundle_name"], "soc_context_default")

    def test_runner_uses_configured_local_context_provider_by_default(self) -> None:
        """Configured advisory context directory should feed runner prompt assembly."""
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            (root / "soc_sops.json").write_text(
                json.dumps(
                    {
                        "snippets": [
                            {
                                "source_type": "soc_sops",
                                "source_id": "auth-42",
                                "title": "Authentication SOP",
                                "content": "Escalate repeated suspicious failed authentications.",
                                "provenance_ref": "kb://soc/sop/auth-42",
                                "rank": 1,
                            }
                        ]
                    }
                ),
                encoding="utf-8",
            )
            config = self._config()
            config.advisory_context_dir = str(root)
            transport = _FakeLiteLlmTransport(self._valid_litellm_response())
            runner = OnPremLiteLlmCoreRunner(config=config, transport=transport)

            runner.run(self._alert(), profile_name=None, customer_bundle_name="acme_default")

            payload = transport.calls[0]["payload"]
            self.assertIn("Authentication SOP", payload["messages"][1]["content"])
            self.assertIn("kb://soc/sop/auth-42", payload["messages"][1]["content"])

    def test_runner_uses_explicit_customer_bundle_over_config_default(self) -> None:
        """Explicit runtime bundle selection should win over config defaults."""
        transport = _FakeLiteLlmTransport(self._valid_litellm_response())
        runner = OnPremLiteLlmCoreRunner(config=self._config(), transport=transport)

        runner.run(
            self._alert(),
            profile_name=None,
            customer_bundle_name="acme_executive",
        )

        payload = transport.calls[0]["payload"]
        self.assertEqual(payload["metadata"]["customer_bundle_name"], "acme_executive")
        self.assertIn("Tone: executive_brief", payload["messages"][0]["content"])

    def test_runner_requires_customer_bundle_selection(self) -> None:
        """Runner should fail closed when no customer bundle can be resolved."""
        config = self._config()
        config.default_customer_bundle_name = None
        runner = OnPremLiteLlmCoreRunner(
            config=config,
            transport=_FakeLiteLlmTransport(self._valid_litellm_response()),
        )

        with self.assertRaises(ValueError):
            runner.run(self._alert(), profile_name=None, customer_bundle_name=None)

    def test_runner_rejects_invalid_profile_name_before_context_lookup(self) -> None:
        """Malformed profile names should fail before context or LiteLLM side effects."""
        transport = _FakeLiteLlmTransport(self._valid_litellm_response())
        context_provider = _FakeContextProvider(())
        runner = OnPremLiteLlmCoreRunner(
            config=self._config(),
            transport=transport,
            context_provider=context_provider,
        )

        with self.assertRaises(ValueError):
            runner.run(
                self._alert(),
                profile_name=123,  # type: ignore[arg-type]
                customer_bundle_name="acme_default",
            )

        self.assertEqual(context_provider.calls, [])
        self.assertEqual(transport.calls, [])

    def test_runner_rejects_unknown_customer_bundle(self) -> None:
        """Unknown customer bundles should fail before LiteLLM is called."""
        transport = _FakeLiteLlmTransport(self._valid_litellm_response())
        runner = OnPremLiteLlmCoreRunner(config=self._config(), transport=transport)

        with self.assertRaises(ValueError):
            runner.run(self._alert(), profile_name=None, customer_bundle_name="unknown")

        self.assertEqual(transport.calls, [])

    def test_runner_wraps_malformed_litellm_json_content(self) -> None:
        """Malformed model content should raise a deterministic runtime error."""
        runner = OnPremLiteLlmCoreRunner(
            config=self._config(),
            transport=_FakeLiteLlmTransport(
                {"choices": [{"message": {"content": "not-json"}}]}
            ),
        )

        with self.assertRaisesRegex(RuntimeError, "valid JSON"):
            runner.run(self._alert(), profile_name=None, customer_bundle_name="acme_default")

    def test_runner_wraps_invalid_analysis_report_contract(self) -> None:
        """Model JSON that is not an AnalysisReport should fail closed."""
        runner = OnPremLiteLlmCoreRunner(
            config=self._config(),
            transport=_FakeLiteLlmTransport(
                {"choices": [{"message": {"content": json.dumps({"schema_version": "1.0"})}}]}
            ),
        )

        with self.assertRaisesRegex(RuntimeError, "AnalysisReport contract"):
            runner.run(self._alert(), profile_name=None, customer_bundle_name="acme_default")

    def test_runner_requires_config_contract(self) -> None:
        """Runner construction should reject malformed config objects deterministically."""
        with self.assertRaises(ValueError):
            OnPremLiteLlmCoreRunner(config=object())  # type: ignore[arg-type]

    def test_stdlib_transport_wraps_invalid_response_bytes(self) -> None:
        """Invalid response bytes should raise deterministic RuntimeError."""

        class _BadBytesResponse:
            def __enter__(self) -> "_BadBytesResponse":
                return self

            def __exit__(self, exc_type, exc_value, traceback) -> None:  # noqa: ANN001
                return None

            def read(self) -> bytes:
                return b"\xff"

        def opener(*args, **kwargs):  # noqa: ANN002, ANN003
            return _BadBytesResponse()

        import updated_notable_analysis.onprem.runner as runner_module

        original_urlopen = runner_module.urlopen
        runner_module.urlopen = opener
        try:
            with self.assertRaisesRegex(RuntimeError, "chat-completions request failed"):
                StdlibLiteLlmTransport().post_json(
                    "http://127.0.0.1:4000/v1/chat/completions",
                    {"model": "gemma-4-31B-it"},
                    timeout_seconds=1,
                )
        finally:
            runner_module.urlopen = original_urlopen

    def test_stdlib_transport_validates_timeout(self) -> None:
        """Malformed timeout values should fail before any network call."""
        with self.assertRaises(ValueError):
            StdlibLiteLlmTransport().post_json(
                "http://127.0.0.1:4000/v1/chat/completions",
                {"model": "gemma-4-31B-it"},
                timeout_seconds="1",  # type: ignore[arg-type]
            )

    def test_stdlib_transport_wraps_network_errors(self) -> None:
        """Network errors should remain deterministic RuntimeError values."""

        def opener(*args, **kwargs):  # noqa: ANN002, ANN003
            raise URLError("connection refused")

        import updated_notable_analysis.onprem.runner as runner_module

        original_urlopen = runner_module.urlopen
        runner_module.urlopen = opener
        try:
            with self.assertRaisesRegex(RuntimeError, "chat-completions request failed"):
                StdlibLiteLlmTransport().post_json(
                    "http://127.0.0.1:4000/v1/chat/completions",
                    {"model": "gemma-4-31B-it"},
                    timeout_seconds=1,
                )
        finally:
            runner_module.urlopen = original_urlopen


if __name__ == "__main__":
    unittest.main()
