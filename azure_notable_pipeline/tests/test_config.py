from azure_notable_pipeline.config import load_config


def test_analysis_deployment_is_customer_configured(monkeypatch):
    monkeypatch.setenv("AZURE_OPENAI_ANALYSIS_DEPLOYMENT", "customer-analysis")

    config = load_config()

    assert config.AZURE_OPENAI_ANALYSIS_DEPLOYMENT == "customer-analysis"
    assert not hasattr(config, "AZURE_AI_FOUNDRY_ANALYSIS_DEPLOYMENT")


def test_analysis_deployment_defaults_to_unset(monkeypatch):
    monkeypatch.delenv("AZURE_OPENAI_ANALYSIS_DEPLOYMENT", raising=False)

    config = load_config()

    assert config.AZURE_OPENAI_ANALYSIS_DEPLOYMENT == ""


def test_input_byte_limits_are_independently_configurable(monkeypatch):
    monkeypatch.setenv("MAX_COMPRESSED_INPUT_BYTES", "2048")
    monkeypatch.setenv("MAX_DECOMPRESSED_INPUT_BYTES", "4096")

    config = load_config()

    assert config.MAX_COMPRESSED_INPUT_BYTES == 2048
    assert config.MAX_DECOMPRESSED_INPUT_BYTES == 4096
