"""Portable capability behavior plus Azure-native runtime contract tests."""

from __future__ import annotations

from unittest.mock import patch

import pytest

from azure_notable_pipeline.config import load_config


def test_default_config_preserves_core_behavior() -> None:
    with patch.dict("os.environ", {}, clear=True):
        config = load_config()

    assert config.CAPABILITY_PROFILES == "core"
    assert config.REPORT_SINK_MODE == "blob"
    assert config.INPUT_CONTAINER_NAME == "input"
    assert config.OUTPUT_CONTAINER_NAME == "output"
    assert config.CASE_EMBED_QUEUE_NAME == "case-embed-invocations"
    assert config.PORTAL_CHAT_TIMEOUT_SEC == 225
    assert not config.RAG_ENABLED
    assert not config.SPLUNK_SINK_ENABLED
    assert not config.PORTAL_ENABLED


def test_action_gated_profile_preserves_approval_and_idempotency_policy() -> None:
    with patch.dict(
        "os.environ",
        {
            "CAPABILITY_PROFILES": "core,action_gated",
            "SERVICENOW_APPROVAL_HMAC_SECRET_NAME": "snow-approval",
        },
        clear=True,
    ):
        config = load_config()

    assert config.SPLUNK_SINK_ENABLED
    assert config.SERVICENOW_DRAFT_ENABLED
    assert config.SERVICENOW_CREATE_ENABLED
    assert config.SERVICENOW_CREATE_REQUIRES_APPROVAL
    assert config.SIDE_EFFECT_IDEMPOTENCY_ENABLED


def test_analyst_portal_profile_uses_cosmos_and_queue_contracts() -> None:
    with patch.dict(
        "os.environ",
        {
            "CAPABILITY_PROFILES": "core,analyst_portal",
            "CASE_INDEX_CONTAINER": "notable-case-index",
            "PORTAL_JWT_ISSUER": "https://issuer.example.test",
                "PORTAL_JWT_AUDIENCE": "notable-portal",
                "PORTAL_ENTRA_REQUIRED_APP_ROLE": "Case.Reader",
        },
        clear=True,
    ):
        config = load_config()

    assert config.CASE_ARCHIVE_ENABLED
    assert config.PORTAL_ENABLED
    assert config.CASE_QA_ENABLED
    assert config.CASE_ARCHIVE_CONTAINER == "output"
    assert config.CASE_INDEX_CONTAINER == "notable-case-index"
    assert config.CASE_EMBED_QUEUE_NAME == "case-embed-invocations"
    assert not config.HTML_REPORT_ENABLED
    assert not config.SERVICENOW_CREATE_ENABLED


@pytest.mark.parametrize(
    ("environment", "message"),
    [
        ({"CAPABILITY_PROFILES": "core,unknown"}, "unsupported profile"),
        (
            {"CAPABILITY_PROFILES": "core,spl_readonly,elastic_readonly"},
            "cannot include both",
        ),
        ({"REPORT_SINK_MODE": "side_effects"}, "REPORT_SINK_MODE"),
        ({"PORTAL_AUTH_MODE": "none"}, "PORTAL_AUTH_MODE"),
        ({"PORTAL_CHAT_TIMEOUT_SEC": "226"}, "PORTAL_CHAT_TIMEOUT_SEC"),
        ({"CASE_QA_VECTOR_DIMENSIONS": "1536"}, "CASE_QA_VECTOR_DIMENSIONS"),
    ],
)
def test_invalid_runtime_contracts_fail_fast(
    environment: dict[str, str], message: str
) -> None:
    with patch.dict("os.environ", environment, clear=True), pytest.raises(
        ValueError, match=message
    ):
        load_config()


def test_portal_jwt_mode_requires_issuer() -> None:
    with patch.dict(
        "os.environ",
        {"PORTAL_ENABLED": "true", "CASE_INDEX_CONTAINER": "notable-case-index"},
        clear=True,
    ), pytest.raises(ValueError, match="PORTAL_JWT_ISSUER"):
        load_config()


def test_portal_entra_mode_requires_app_role() -> None:
    with patch.dict(
        "os.environ",
        {
            "PORTAL_ENABLED": "true",
            "PORTAL_AUTH_MODE": "iam",
            "CASE_INDEX_CONTAINER": "notable-case-index",
        },
        clear=True,
    ), pytest.raises(ValueError, match="PORTAL_ENTRA_REQUIRED_APP_ROLE"):
        load_config()


def test_portal_jwt_mode_requires_app_role_after_issuer_and_audience() -> None:
    with patch.dict(
        "os.environ",
        {
            "PORTAL_ENABLED": "true",
            "PORTAL_AUTH_MODE": "jwt",
            "CASE_INDEX_CONTAINER": "notable-case-index",
            "PORTAL_JWT_ISSUER": "https://issuer.example.test",
            "PORTAL_JWT_AUDIENCE": "portal",
        },
        clear=True,
    ), pytest.raises(ValueError, match="PORTAL_ENTRA_REQUIRED_APP_ROLE"):
        load_config()


def test_aws_runtime_names_are_not_aliases() -> None:
    with patch.dict(
        "os.environ",
        {
            "BEDROCK_MODEL_ID": "legacy-model",
            "SPLUNK_SINK_MODE": "notable_rest",
            "OUTPUT_BUCKET_NAME": "legacy-bucket",
        },
        clear=True,
    ):
        config = load_config()

    assert config.AZURE_AI_FOUNDRY_ANALYSIS_DEPLOYMENT == "claude-sonnet-4-6"
    assert config.REPORT_SINK_MODE == "blob"
    assert config.OUTPUT_CONTAINER_NAME == "output"
    assert not hasattr(config, "BEDROCK_MODEL_ID")
    assert not hasattr(config, "OUTPUT_BUCKET_NAME")
