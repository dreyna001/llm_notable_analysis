"""Deployment template contract tests."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path
from typing import Any

import yaml
from yaml.nodes import MappingNode, SequenceNode

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_DIR = PROJECT_ROOT / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))


class CfnLoader(yaml.SafeLoader):
    """Loader that tolerates CloudFormation intrinsic tags."""


def _construct_intrinsic(loader: CfnLoader, _suffix: str, node: yaml.Node) -> Any:
    if isinstance(node, MappingNode):
        return loader.construct_mapping(node)
    if isinstance(node, SequenceNode):
        return loader.construct_sequence(node)
    return loader.construct_scalar(node)


CfnLoader.add_multi_constructor("!", _construct_intrinsic)


def load_template(path: str) -> dict[str, Any]:
    """Load a CloudFormation/SAM template."""

    template = yaml.load((PROJECT_ROOT / path).read_text(encoding="utf-8"), Loader=CfnLoader)
    if not isinstance(template, dict):
        raise AssertionError(f"{path} did not parse as a mapping")
    return template


class DeployTemplateTests(unittest.TestCase):
    """Template synchronization tests."""

    def test_portal_ui_static_hosting_resources_are_present(self) -> None:
        for path in (
            "deploy/aws/template-sam.yaml",
            "deploy/aws/template-cfn.yaml",
        ):
            with self.subTest(path=path):
                template = load_template(path)
                self.assertIn("PortalUiBucketName", template["Parameters"])
                self.assertIn("PortalUiPriceClass", template["Parameters"])
                self.assertIn("HasPortalUiDeployment", template["Conditions"])
                self.assertIn("PortalUiBucket", template["Resources"])
                self.assertIn("PortalUiOriginAccessControl", template["Resources"])
                self.assertIn("PortalUiDistribution", template["Resources"])
                self.assertIn("PortalUiBucketPolicy", template["Resources"])
                self.assertIn("PortalUiBucketName", template["Outputs"])
                self.assertIn("PortalUiDistributionDomainName", template["Outputs"])


if __name__ == "__main__":
    unittest.main()
