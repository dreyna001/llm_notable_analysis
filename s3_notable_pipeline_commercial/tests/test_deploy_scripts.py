"""Local contract tests for commercial AWS deployment preflight scripts."""

from __future__ import annotations

import os
import subprocess
import tempfile
import unittest
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
BASH_SCRIPT = PROJECT_ROOT / "scripts" / "setup-and-deploy.sh"
POWERSHELL_SCRIPT = PROJECT_ROOT / "scripts" / "setup-and-deploy.ps1"
LOCALSTACK_BASH_SCRIPT = PROJECT_ROOT / "scripts" / "localstack_bootstrap.sh"
LOCALSTACK_POWERSHELL_SCRIPT = PROJECT_ROOT / "scripts" / "localstack_bootstrap.ps1"


class DeployScriptTests(unittest.TestCase):
    """Deployment tooling must fail closed before any build or mutation."""

    def _write_fake_tools(self, directory: Path) -> Path:
        call_log = directory / "calls.log"
        tools = {
            "aws": """#!/usr/bin/env bash
case "$1" in
  --version) echo "aws-cli/fake" ;;
  configure) echo "us-east-1" ;;
  sts)
    if [ "$6" = "Account" ]; then
      echo "${DEPLOY_TEST_ACCOUNT_ID:-123456789012}"
    else
      echo "${DEPLOY_TEST_CALLER_ARN:-arn:aws:sts::123456789012:assumed-role/DeployRole/session}"
    fi
    ;;
  bedrock) echo "None" ;;
  *) exit 2 ;;
esac
""",
            "sam": """#!/usr/bin/env bash
if [ "$1" = "--version" ]; then
  echo "SAM CLI, fake"
  exit 0
fi
printf 'sam %s\n' "$*" >> "$DEPLOY_TEST_CALL_LOG"
""",
            "docker": """#!/usr/bin/env bash
echo "Docker fake"
""",
        }
        for name, source in tools.items():
            path = directory / name
            path.write_text(source, encoding="utf-8")
            path.chmod(0o755)
        return call_log

    def test_bash_preflight_rejects_wrong_region_before_build(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            tool_dir = Path(temp_dir)
            call_log = self._write_fake_tools(tool_dir)
            env = {
                **os.environ,
                "PATH": f"{tool_dir}{os.pathsep}{os.environ.get('PATH', '')}",
                "AWS_REGION": "us-west-2",
                "AWS_DEFAULT_REGION": "",
                "COMMERCIAL_AWS_ACCOUNT_ID": "123456789012",
                "DEPLOY_TEST_CALL_LOG": str(call_log),
            }

            result = subprocess.run(
                ["bash", str(BASH_SCRIPT)],
                cwd=PROJECT_ROOT,
                env=env,
                capture_output=True,
                text=True,
                check=False,
            )

            self.assertNotEqual(result.returncode, 0)
            self.assertIn("Configured AWS region must be us-east-1", result.stdout)
            self.assertFalse(call_log.exists())

    def test_bash_preflight_rejects_wrong_account_and_partition(self) -> None:
        cases = (
            (
                {"COMMERCIAL_AWS_ACCOUNT_ID": "999999999999"},
                "does not match approved account",
            ),
            (
                {
                    "COMMERCIAL_AWS_ACCOUNT_ID": "123456789012",
                    "DEPLOY_TEST_CALLER_ARN": (
                        "arn:aws-us-gov:sts::123456789012:assumed-role/DeployRole/session"
                    ),
                },
                "not in the commercial aws partition",
            ),
        )
        for overrides, expected_message in cases:
            with (
                self.subTest(expected_message=expected_message),
                tempfile.TemporaryDirectory() as temp_dir,
            ):
                tool_dir = Path(temp_dir)
                call_log = self._write_fake_tools(tool_dir)
                env = {
                    **os.environ,
                    "PATH": f"{tool_dir}{os.pathsep}{os.environ.get('PATH', '')}",
                    "AWS_REGION": "us-east-1",
                    "AWS_DEFAULT_REGION": "",
                    "DEPLOY_TEST_CALL_LOG": str(call_log),
                    **overrides,
                }

                result = subprocess.run(
                    ["bash", str(BASH_SCRIPT)],
                    cwd=PROJECT_ROOT,
                    env=env,
                    capture_output=True,
                    text=True,
                    check=False,
                )

                self.assertNotEqual(result.returncode, 0)
                self.assertIn(expected_message, result.stdout)
                self.assertFalse(call_log.exists())

    def test_bash_guided_deploy_forces_commercial_region(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            tool_dir = Path(temp_dir)
            call_log = self._write_fake_tools(tool_dir)
            env = {
                **os.environ,
                "PATH": f"{tool_dir}{os.pathsep}{os.environ.get('PATH', '')}",
                "AWS_REGION": "us-east-1",
                "AWS_DEFAULT_REGION": "",
                "COMMERCIAL_AWS_ACCOUNT_ID": "123456789012",
                "DEPLOY_TEST_CALL_LOG": str(call_log),
            }

            result = subprocess.run(
                ["bash", str(BASH_SCRIPT)],
                cwd=PROJECT_ROOT,
                env=env,
                capture_output=True,
                text=True,
                check=False,
            )

            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            calls = call_log.read_text(encoding="utf-8")
            self.assertIn("sam build -t deploy/aws/template-sam.yaml", calls)
            self.assertIn(
                "sam deploy --guided --region us-east-1 "
                "--template-file .aws-sam/build/template.yaml",
                calls,
            )

    def test_both_scripts_enforce_account_partition_and_region(self) -> None:
        bash_source = BASH_SCRIPT.read_text(encoding="utf-8")
        powershell_source = POWERSHELL_SCRIPT.read_text(encoding="utf-8")
        for source in (bash_source, powershell_source):
            with self.subTest(script="bash" if source is bash_source else "powershell"):
                self.assertIn("COMMERCIAL_AWS_ACCOUNT_ID", source)
                self.assertIn("arn:aws:", source)
                self.assertIn("us-east-1", source)
                self.assertNotIn("us-gov-east-1", source)
        self.assertIn('sam deploy --region "$region"', bash_source)
        self.assertIn('sam deploy --guided --region "$region"', bash_source)
        self.assertIn("sam deploy --region $region", powershell_source)
        self.assertIn("sam deploy --guided --region $region", powershell_source)

    def test_localstack_bootstrap_rejects_remote_endpoint_before_aws_calls(self) -> None:
        env = {
            **os.environ,
            "AWS_ENDPOINT_URL": "http://localhost.attacker.example:4566",
        }
        result = subprocess.run(
            ["bash", str(LOCALSTACK_BASH_SCRIPT)],
            cwd=PROJECT_ROOT,
            env=env,
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(result.returncode, 2)
        self.assertIn("loopback LocalStack URL", result.stderr)
        powershell_source = LOCALSTACK_POWERSHELL_SCRIPT.read_text(encoding="utf-8")
        self.assertIn("IsLoopback", powershell_source)
        self.assertIn('AWS_ACCESS_KEY_ID = "test"', powershell_source)
        self.assertIn("Get-Command aws -ErrorAction SilentlyContinue", powershell_source)
        self.assertIn("AWS CLI is required for the LocalStack bootstrap", powershell_source)
        self.assertIn("ValueFromRemainingArguments", powershell_source)
        self.assertIn("--cli-input-json", powershell_source)


if __name__ == "__main__":
    unittest.main()
