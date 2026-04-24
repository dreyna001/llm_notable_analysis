"""LiteLLM-backed on-prem core runner seam."""

from __future__ import annotations

from dataclasses import asdict, is_dataclass
import json
from typing import Any, Mapping, Protocol, Sequence
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from updated_notable_analysis.core.config_models import CustomerBundle
from updated_notable_analysis.core.context import (
    ContextBundle,
    ContextProvider,
    normalize_advisory_context,
    resolve_context_bundle,
)
from updated_notable_analysis.core.models import (
    AdvisoryContextSnippet,
    AnalysisReport,
    NormalizedAlert,
)
from updated_notable_analysis.core.prompting import (
    PromptPack,
    PromptAssemblyInput,
    assemble_prompt_payload,
)
from updated_notable_analysis.core.validators import (
    normalize_optional_string,
    require_int_gt_zero,
    require_non_empty_string,
)
from updated_notable_analysis.profiles import DEFAULT_CONTEXT_BUNDLES, DEFAULT_CUSTOMER_BUNDLES
from updated_notable_analysis.prompt_packs import DEFAULT_PROMPT_PACKS

from .config import OnPremRuntimeConfig
from .context_provider import LocalJsonAdvisoryContextProvider
from .service import CoreAnalysisRunner


class LiteLlmTransport(Protocol):
    """Protocol for OpenAI-compatible LiteLLM JSON calls."""

    def post_json(
        self,
        url: str,
        payload: Mapping[str, Any],
        *,
        timeout_seconds: int,
    ) -> Mapping[str, Any]:
        """POST JSON to LiteLLM and return a JSON object response."""


class StdlibLiteLlmTransport:
    """Stdlib HTTP transport for LiteLLM chat-completions calls."""

    def post_json(
        self,
        url: str,
        payload: Mapping[str, Any],
        *,
        timeout_seconds: int,
    ) -> Mapping[str, Any]:
        """POST one JSON payload and return the decoded JSON object."""
        timeout_seconds = require_int_gt_zero(timeout_seconds, "timeout_seconds")
        request = Request(
            require_non_empty_string(url, "url"),
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json", "Accept": "application/json"},
            method="POST",
        )
        try:
            with urlopen(request, timeout=timeout_seconds) as response:
                response_payload = json.loads(response.read().decode("utf-8"))
        except (
            HTTPError,
            URLError,
            TimeoutError,
            OSError,
            UnicodeDecodeError,
            json.JSONDecodeError,
        ) as exc:
            raise RuntimeError("LiteLLM chat-completions request failed.") from exc
        if not isinstance(response_payload, Mapping):
            raise RuntimeError("LiteLLM chat-completions response must be a JSON object.")
        return dict(response_payload)


class EmptyContextProvider:
    """Default advisory context provider for deployments without retrieval wiring yet."""

    def get_advisory_context(
        self, normalized_alert: NormalizedAlert, context_bundle: ContextBundle
    ) -> Sequence[AdvisoryContextSnippet]:
        """Return no advisory context."""
        return ()


class OnPremLiteLlmCoreRunner(CoreAnalysisRunner):
    """Core runner adapter that sends assembled prompts to LiteLLM on loopback."""

    def __init__(
        self,
        *,
        config: OnPremRuntimeConfig,
        transport: LiteLlmTransport | None = None,
        context_provider: ContextProvider | None = None,
        customer_bundles: Mapping[str, CustomerBundle] | None = None,
        context_bundles: Mapping[str, ContextBundle] | None = None,
        prompt_packs: Mapping[str, PromptPack] | None = None,
    ) -> None:
        """Initialize runner dependencies."""
        if not isinstance(config, OnPremRuntimeConfig):
            raise ValueError("Field 'config' must be OnPremRuntimeConfig.")
        self._config = config
        self._transport = transport or StdlibLiteLlmTransport()
        self._context_provider = context_provider or _default_context_provider(config)
        self._customer_bundles = dict(customer_bundles or DEFAULT_CUSTOMER_BUNDLES)
        self._context_bundles = dict(context_bundles or DEFAULT_CONTEXT_BUNDLES)
        self._prompt_packs = dict(prompt_packs or DEFAULT_PROMPT_PACKS)

    def run(
        self,
        normalized_alert: NormalizedAlert,
        *,
        profile_name: str | None,
        customer_bundle_name: str | None,
    ) -> AnalysisReport:
        """Run one normalized alert through the LiteLLM-backed analysis path."""
        if not isinstance(normalized_alert, NormalizedAlert):
            raise ValueError("Field 'normalized_alert' must be NormalizedAlert.")
        normalized_profile_name = normalize_optional_string(profile_name, "profile_name")

        selected_bundle_name = self._resolve_customer_bundle_name(customer_bundle_name)
        customer_bundle = self._resolve_customer_bundle(selected_bundle_name)
        context_bundle = resolve_context_bundle(customer_bundle, self._context_bundles)
        raw_context = self._context_provider.get_advisory_context(
            normalized_alert, context_bundle
        )
        advisory_context = normalize_advisory_context(
            raw_context,
            retrieval_limit=context_bundle.retrieval_limit,
            context_budget_chars=context_bundle.context_budget_chars,
        )
        prompt_payload = assemble_prompt_payload(
            PromptAssemblyInput(
                normalized_alert=normalized_alert,
                customer_bundle=customer_bundle,
                advisory_context_snippets=advisory_context,
            ),
            self._prompt_packs,
        )
        response = self._transport.post_json(
            self._config.litellm_chat_completions_url,
            _build_chat_completions_payload(
                model_name=self._config.litellm_model_name,
                system_instructions=prompt_payload.system_instructions,
                analyst_prompt=prompt_payload.analyst_prompt,
                alert_direct_payload=prompt_payload.alert_direct_payload,
                metadata={
                    "profile_name": normalized_profile_name,
                    "customer_bundle_name": selected_bundle_name,
                    "prompt_pack_name": prompt_payload.prompt_pack_name,
                },
            ),
            timeout_seconds=self._config.litellm_request_timeout_seconds,
        )
        return _analysis_report_from_litellm_response(response)

    def _resolve_customer_bundle_name(self, customer_bundle_name: str | None) -> str:
        """Resolve explicit or config-default customer bundle name."""
        resolved_name = normalize_optional_string(customer_bundle_name, "customer_bundle_name")
        resolved_name = resolved_name or self._config.default_customer_bundle_name
        if resolved_name is None:
            raise ValueError("A customer bundle name is required for on-prem LiteLLM analysis.")
        return resolved_name

    def _resolve_customer_bundle(self, customer_bundle_name: str) -> CustomerBundle:
        """Resolve one registered customer bundle by name."""
        if customer_bundle_name not in self._customer_bundles:
            available = ", ".join(sorted(self._customer_bundles))
            raise ValueError(
                f"Unknown customer bundle {customer_bundle_name!r}. Available bundles: {available}"
            )
        return self._customer_bundles[customer_bundle_name]


def _build_chat_completions_payload(
    *,
    model_name: str,
    system_instructions: str,
    analyst_prompt: str,
    alert_direct_payload: str,
    metadata: Mapping[str, Any],
) -> dict[str, Any]:
    """Build a deterministic OpenAI-compatible LiteLLM request payload."""
    return {
        "model": require_non_empty_string(model_name, "model_name"),
        "messages": (
            {
                "role": "system",
                "content": require_non_empty_string(
                    system_instructions, "system_instructions"
                ),
            },
            {
                "role": "user",
                "content": (
                    f"{require_non_empty_string(analyst_prompt, 'analyst_prompt')}\n\n"
                    "Direct alert payload:\n"
                    f"{require_non_empty_string(alert_direct_payload, 'alert_direct_payload')}\n\n"
                    "Return only a JSON object compatible with the AnalysisReport contract."
                ),
            },
        ),
        "response_format": {"type": "json_object"},
        "temperature": 0,
        "metadata": dict(metadata),
    }


def _analysis_report_from_litellm_response(response: Mapping[str, Any]) -> AnalysisReport:
    """Parse and validate an AnalysisReport from a LiteLLM response object."""
    choices = response.get("choices")
    if not isinstance(choices, Sequence) or isinstance(choices, (str, bytes)) or not choices:
        raise RuntimeError("LiteLLM response must include at least one choice.")
    first_choice = choices[0]
    if not isinstance(first_choice, Mapping):
        raise RuntimeError("LiteLLM response choice must be a JSON object.")
    message = first_choice.get("message")
    if not isinstance(message, Mapping):
        raise RuntimeError("LiteLLM response choice must include a message object.")
    content = message.get("content")
    if not isinstance(content, str) or not content.strip():
        raise RuntimeError("LiteLLM response message content must be non-empty JSON text.")
    try:
        raw_report = json.loads(content)
    except json.JSONDecodeError as exc:
        raise RuntimeError("LiteLLM response message content must be valid JSON.") from exc
    if not isinstance(raw_report, Mapping):
        raise RuntimeError("LiteLLM response message content must decode to a JSON object.")
    try:
        return AnalysisReport(**_to_plain_json(raw_report))
    except (TypeError, ValueError) as exc:
        raise RuntimeError("LiteLLM response did not satisfy AnalysisReport contract.") from exc


def _to_plain_json(value: Any) -> Any:
    """Convert dataclass-like test payloads into JSON-compatible plain structures."""
    if is_dataclass(value):
        return _to_plain_json(asdict(value))
    if isinstance(value, Mapping):
        return {str(key): _to_plain_json(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_to_plain_json(item) for item in value]
    return value


def _default_context_provider(config: OnPremRuntimeConfig) -> ContextProvider:
    """Build the default advisory context provider for on-prem runner config."""
    if config.advisory_context_dir is None:
        return EmptyContextProvider()
    return LocalJsonAdvisoryContextProvider(context_dir=config.advisory_context_dir)
