"""Tests for bounded external-body reads."""

from __future__ import annotations

import io

import pytest

from s3_notable_pipeline.runtime_security import read_bounded_bytes


def test_read_bounded_bytes_stops_after_limit_plus_one() -> None:
    body = io.BytesIO(b"a" * 100)

    with pytest.raises(ValueError, match="MAX_BYTES"):
        read_bounded_bytes(body, max_bytes=10, setting_name="MAX_BYTES")

    assert body.tell() == 11


def test_read_bounded_bytes_accepts_body_at_limit() -> None:
    assert read_bounded_bytes(b"abcd", max_bytes=4, setting_name="MAX_BYTES") == b"abcd"


def test_read_bounded_bytes_rejects_stream_without_sized_reads() -> None:
    class UnboundedOnly:
        def read(self) -> bytes:
            return b"secret" * 100

    with pytest.raises(ValueError, match="bounded reads"):
        read_bounded_bytes(UnboundedOnly(), max_bytes=10, setting_name="MAX_BYTES")
