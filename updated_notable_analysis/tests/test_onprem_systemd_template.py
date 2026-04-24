"""Tests for the on-prem systemd deployment template."""

from __future__ import annotations

from pathlib import Path
import unittest


SYSTEMD_TEMPLATE = (
    Path(__file__).resolve().parents[1]
    / "onprem"
    / "systemd"
    / "notable-analyzer.service.example"
)


class TestOnPremSystemdTemplate(unittest.TestCase):
    """Static checks for deployment-facing systemd wiring."""

    def test_analyzer_depends_on_litellm_not_direct_vllm(self) -> None:
        """Analyzer startup should be gated on LiteLLM, not direct vLLM coupling."""
        service_text = SYSTEMD_TEMPLATE.read_text(encoding="utf-8")

        self.assertIn("After=network-online.target litellm.service", service_text)
        self.assertIn("Requires=litellm.service", service_text)
        self.assertNotIn("vllm.service", service_text)

    def test_template_uses_packaging_owned_launcher_not_python_module_cli(self) -> None:
        """The unit should not introduce a package CLI entrypoint in this slice."""
        service_text = SYSTEMD_TEMPLATE.read_text(encoding="utf-8")

        self.assertIn("ExecStart=/opt/notable-analyzer/bin/run-onprem-worker", service_text)
        self.assertNotIn("python -m", service_text)
        self.assertIn("does not ship a CLI entrypoint", service_text)

    def test_template_loads_config_and_constrains_runtime_scope(self) -> None:
        """The unit should load explicit config and stay narrowed to local resources."""
        service_text = SYSTEMD_TEMPLATE.read_text(encoding="utf-8")

        self.assertIn("EnvironmentFile=/etc/notable-analyzer/config.env", service_text)
        self.assertIn("ReadWritePaths=/var/notables /var/sftp/soar", service_text)
        self.assertIn("IPAddressDeny=any", service_text)
        self.assertIn("IPAddressAllow=127.0.0.1/32 ::1/128", service_text)
        self.assertIn("KillSignal=SIGTERM", service_text)


if __name__ == "__main__":
    unittest.main()
