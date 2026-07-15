from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest


_MODULE_PATH = Path(__file__).parents[1] / "scripts" / "soar_playbook" / "phantom_to_blob.py"
_SPEC = importlib.util.spec_from_file_location("phantom_to_blob", _MODULE_PATH)
assert _SPEC and _SPEC.loader
helper = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(helper)


def test_government_url_and_paths_are_strict():
    assert helper.validate_storage_account_url(
        "https://account.blob.core.usgovcloudapi.net/"
    ) == "https://account.blob.core.usgovcloudapi.net"
    assert helper.validate_container_name("Input-Data") == "input-data"
    assert helper.validate_prefix("input/incoming") == "input/incoming"

    with pytest.raises(helper.ConfigurationError):
        helper.validate_storage_account_url("https://account.blob.core.windows.net")
    with pytest.raises(helper.ConfigurationError):
        helper.validate_prefix("input/../secret")


def test_finding_id_is_stable_and_payload_fallback_is_bounded():
    payload = {"finding_id": "SOAR/42", "message": "synthetic"}
    assert helper.derive_finding_id(payload) == "SOAR_42"
    assert helper.derive_finding_id({}).startswith("payload-")
    data_a = helper.serialize_payload(payload, compress=True)[0]
    data_b = helper.serialize_payload(payload, compress=True)[0]
    assert data_a == data_b


def test_read_payload_rejects_oversized_input(tmp_path):
    source = tmp_path / "notable.json"
    source.write_text('{"message":"12345"}', encoding="utf-8")
    with pytest.raises(helper.ConfigurationError):
        helper.read_payload(str(source), max_bytes=5)
