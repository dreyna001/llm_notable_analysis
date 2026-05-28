import importlib.util
import sys
import tempfile
import unittest
from pathlib import Path


SCRIPT_PATH = (
    Path(__file__).resolve().parents[1]
    / "scripts"
    / "benchmark_inference_server.py"
)
SPEC = importlib.util.spec_from_file_location("benchmark_inference_server", SCRIPT_PATH)
assert SPEC is not None
benchmark = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
sys.modules[SPEC.name] = benchmark
SPEC.loader.exec_module(benchmark)


class TestBenchmarkInferenceServer(unittest.TestCase):
    def test_read_config_env_parses_export_and_quotes(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            config_path = Path(tmpdir) / "config.env"
            config_path.write_text(
                "\n".join(
                    [
                        "# comment",
                        "LLM_API_URL=http://127.0.0.1:4000/v1/chat/completions",
                        "export LLM_MODEL_NAME='gemma-4-31B-it'",
                        'LLM_API_TOKEN="local token"',
                    ]
                ),
                encoding="utf-8",
            )

            values = benchmark.read_config_env(str(config_path))

        self.assertEqual(
            values["LLM_API_URL"],
            "http://127.0.0.1:4000/v1/chat/completions",
        )
        self.assertEqual(values["LLM_MODEL_NAME"], "gemma-4-31B-it")
        self.assertEqual(values["LLM_API_TOKEN"], "local token")

    def test_parse_int_list_rejects_non_positive_values(self) -> None:
        with self.assertRaises(Exception):
            benchmark.parse_int_list("1,0,2", name="--concurrency")

    def test_percentile_uses_nearest_rank(self) -> None:
        self.assertEqual(benchmark.percentile([1.0, 2.0, 3.0, 4.0], 0.95), 4.0)
        self.assertEqual(benchmark.percentile([1.0, 2.0, 3.0, 4.0], 0.50), 2.0)

    def test_summarize_case_omits_token_rates_when_usage_missing(self) -> None:
        case = benchmark.BenchmarkCase(
            concurrency=1,
            requests=1,
            context_tokens_target=512,
            max_tokens=128,
        )
        result = benchmark.summarize_case(
            case,
            2.0,
            [
                {
                    "ok": True,
                    "latency_s": 2.0,
                    "ttft_s": 0.5,
                    "prompt_tokens": None,
                    "completion_tokens": None,
                    "total_tokens": None,
                    "output_chars": 100,
                    "error": None,
                }
            ],
        )

        self.assertEqual(result["success"], 1)
        self.assertEqual(result["usage_response_count"], 0)
        self.assertIsNone(result["total_tok_per_sec"])
        self.assertEqual(result["p50_ttft_s"], 0.5)

    def test_summarize_case_reports_token_rates_when_usage_present(self) -> None:
        case = benchmark.BenchmarkCase(
            concurrency=2,
            requests=2,
            context_tokens_target=512,
            max_tokens=128,
        )
        result = benchmark.summarize_case(
            case,
            2.0,
            [
                {
                    "ok": True,
                    "latency_s": 1.0,
                    "ttft_s": 0.2,
                    "prompt_tokens": 100,
                    "completion_tokens": 20,
                    "total_tokens": 120,
                    "output_chars": 50,
                    "error": None,
                },
                {
                    "ok": True,
                    "latency_s": 2.0,
                    "ttft_s": 0.3,
                    "prompt_tokens": 100,
                    "completion_tokens": 30,
                    "total_tokens": 130,
                    "output_chars": 60,
                    "error": None,
                },
            ],
        )

        self.assertEqual(result["success"], 2)
        self.assertEqual(result["completion_tokens"], 50)
        self.assertEqual(result["completion_tok_per_sec"], 25.0)
        self.assertEqual(result["request_per_sec"], 1.0)


if __name__ == "__main__":
    unittest.main()
