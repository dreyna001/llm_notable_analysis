"""Minimal SDK usage example."""

from onprem_llm_sdk import SDKConfig, VLLMClient


def main() -> None:
    cfg = SDKConfig.from_env()
    client = VLLMClient(cfg)
    result = client.complete("Provide a one-line incident summary.")
    print(result.text)


if __name__ == "__main__":
    main()

