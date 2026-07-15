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
    assert config.PORTAL_CHAT_DISTRIBUTED_QUOTA_ENABLED
    assert config.PORTAL_CHAT_PER_USER_MAX_CONCURRENCY == 2
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
            "RAG_TENANT_ID": "customer-tenant",
            "CASE_QA_AZURE_SEARCH_INDEX": "case-index",
                "PORTAL_JWT_ISSUER": "https://login.microsoftonline.us/tenant/v2.0",
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
    assert config.PORTAL_CHAT_QUOTA_CONTAINER == "notable-chat-quota"
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


def test_chat_request_dedupe_must_cover_the_crash_recovery_lease() -> None:
    with patch.dict(
        "os.environ",
        {
            "CAPABILITY_PROFILES": "core,analyst_portal",
            "CASE_INDEX_CONTAINER": "notable-case-index",
            "RAG_TENANT_ID": "customer-tenant",
            "CASE_QA_AZURE_SEARCH_INDEX": "case-index",
            "PORTAL_JWT_ISSUER": "https://login.microsoftonline.us/tenant/v2.0",
            "PORTAL_JWT_AUDIENCE": "portal",
            "PORTAL_ENTRA_REQUIRED_APP_ROLE": "Portal.Access",
            "PORTAL_CHAT_LEASE_SECONDS": "300",
            "PORTAL_CHAT_REQUEST_DEDUPE_SECONDS": "60",
        },
        clear=True,
    ), pytest.raises(ValueError, match="DEDUPE_SECONDS"):
        load_config()


def test_chat_quota_rejects_a_dedupe_window_that_can_overgrow_its_document() -> None:
    with patch.dict(
        "os.environ",
        {
            "CAPABILITY_PROFILES": "core,analyst_portal",
            "CASE_INDEX_CONTAINER": "notable-case-index",
            "RAG_TENANT_ID": "customer-tenant",
            "CASE_QA_AZURE_SEARCH_INDEX": "case-index",
            "PORTAL_JWT_ISSUER": "https://login.microsoftonline.us/tenant/v2.0",
            "PORTAL_JWT_AUDIENCE": "portal",
            "PORTAL_ENTRA_REQUIRED_APP_ROLE": "Portal.Access",
            "PORTAL_CHAT_QUOTA_WINDOW_SECONDS": "60",
            "PORTAL_CHAT_MAX_REQUESTS_PER_WINDOW": "3",
            "PORTAL_CHAT_REQUEST_DEDUPE_SECONDS": "86400",
        },
        clear=True,
    ), pytest.raises(ValueError, match="4096 recent request IDs"):
        load_config()


def test_chat_quota_request_rate_has_a_conservative_per_window_ceiling() -> None:
    with patch.dict(
        "os.environ",
        {"PORTAL_CHAT_MAX_REQUESTS_PER_WINDOW": "2049"},
        clear=True,
    ), pytest.raises(ValueError, match="PORTAL_CHAT_MAX_REQUESTS_PER_WINDOW"):
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
            "PORTAL_JWT_ISSUER": "https://login.microsoftonline.us/tenant/v2.0",
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

    assert config.AZURE_CLOUD_ENVIRONMENT == "AzureUSGovernment"
    assert config.AZURE_REGION == "usgovvirginia"
    assert config.AZURE_OPENAI_ANALYSIS_DEPLOYMENT == ""
    assert config.REPORT_SINK_MODE == "blob"
    assert config.OUTPUT_CONTAINER_NAME == "output"
    assert not hasattr(config, "BEDROCK_MODEL_ID")
    assert not hasattr(config, "OUTPUT_BUCKET_NAME")


def test_commercial_cloud_and_endpoint_contracts_fail_closed() -> None:
    with patch.dict(
        "os.environ",
        {"AZURE_CLOUD_ENVIRONMENT": "AzureCloud"},
        clear=True,
    ), pytest.raises(ValueError, match="AzureUSGovernment"):
        load_config()

    with patch.dict(
        "os.environ",
        {"AZURE_OPENAI_ENDPOINT": "https://resource.openai.azure.com"},
        clear=True,
    ), pytest.raises(ValueError, match="Azure Government endpoint"):
        load_config()


def test_queue_retention_and_customer_key_contracts_fail_closed() -> None:
    with patch.dict(
        "os.environ",
        {"INPUT_RETENTION_DAYS": "1", "QUEUE_RECOVERY_WINDOW_SECONDS": "86400"},
        clear=True,
    ), pytest.raises(ValueError, match="INPUT_RETENTION_DAYS"):
        load_config()

    with patch.dict(
        "os.environ",
        {"CUSTOMER_MANAGED_KEY_ENABLED": "true"},
        clear=True,
    ), pytest.raises(ValueError, match="CUSTOMER_MANAGED_KEY_URI"):
        load_config()


def test_rag_contract_uses_government_search_and_versioned_blob_source() -> None:
    with patch.dict(
        "os.environ",
        {
            "CAPABILITY_PROFILES": "core,rag",
            "AZURE_SEARCH_ENDPOINT": "https://tenant.search.azure.us",
            "RAG_TENANT_ID": "customer-tenant",
            "RAG_SOURCE_CONTAINER": "knowledge",
            "RAG_SOURCE_PREFIX": "rag-sources",
            "RAG_SOURCE_STORAGE_ACCOUNT_URL": "https://source.blob.core.usgovcloudapi.net",
            "RAG_AZURE_SEARCH_INDEX": "soc-knowledge",
        },
        clear=True,
    ):
        config = load_config()

    assert config.RAG_RETRIEVAL_BACKEND == "azure_search"
    assert config.RAG_INGEST_QUEUE_NAME == "rag-ingest-invocations"
    assert config.RAG_TENANT_ID == "customer-tenant"

    with patch.dict(
        "os.environ",
        {"RAG_RETRIEVAL_BACKEND": "commercial_search"},
        clear=True,
    ), pytest.raises(ValueError, match="RAG_RETRIEVAL_BACKEND"):
        load_config()
