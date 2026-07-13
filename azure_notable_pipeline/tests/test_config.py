from azure_notable_pipeline.config import load_config


def test_analysis_defaults_to_sonnet_46_foundry_deployment(monkeypatch):
    monkeypatch.delenv("AZURE_AI_FOUNDRY_ANALYSIS_DEPLOYMENT", raising=False)
    monkeypatch.setenv("AZURE_OPENAI_ANALYSIS_DEPLOYMENT", "legacy-openai-name")

    config = load_config()

    assert config.AZURE_AI_FOUNDRY_ANALYSIS_DEPLOYMENT == "claude-sonnet-4-6"
    assert not hasattr(config, "AZURE_OPENAI_ANALYSIS_DEPLOYMENT")


def test_analysis_foundry_deployment_is_operator_overridable(monkeypatch):
    monkeypatch.setenv(
        "AZURE_AI_FOUNDRY_ANALYSIS_DEPLOYMENT", "qualified-sonnet-deployment"
    )

    config = load_config()

    assert (
        config.AZURE_AI_FOUNDRY_ANALYSIS_DEPLOYMENT
        == "qualified-sonnet-deployment"
    )


def test_foundry_anthropic_base_url_is_normalized(monkeypatch):
    monkeypatch.setenv(
        "AZURE_AI_FOUNDRY_ANTHROPIC_BASE_URL",
        "https://example.services.ai.azure.com/anthropic/",
    )

    config = load_config()

    assert (
        config.AZURE_AI_FOUNDRY_ANTHROPIC_BASE_URL
        == "https://example.services.ai.azure.com/anthropic"
    )


def test_foundry_anthropic_base_url_rejects_messages_operation(monkeypatch):
    monkeypatch.setenv(
        "AZURE_AI_FOUNDRY_ANTHROPIC_BASE_URL",
        "https://example.services.ai.azure.com/anthropic/v1/messages",
    )

    try:
        load_config()
    except ValueError as exc:
        assert "must end at /anthropic" in str(exc)
    else:
        raise AssertionError("full Messages operation URL must be rejected")
