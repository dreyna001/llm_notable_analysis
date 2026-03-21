"""Minimal SDK usage example."""

from onprem_llm_sdk import SDKConfig, VLLMClient


def main() -> None:
    """Run a minimal completion call using environment-based configuration."""
    cfg = SDKConfig.from_env()
    client = VLLMClient(cfg)
    result = client.complete("Provide a one-line incident summary.")
    print(result.text)


if __name__ == "__main__":
    main()
