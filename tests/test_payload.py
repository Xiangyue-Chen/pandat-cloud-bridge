from __future__ import annotations

import base64
import json

import pytest

from pandat_bridge.models import JobSpec, JobValidationError
from pandat_bridge.payload import decode_job, encode_job
from test_models import c63_mapping


def encoded_bytes(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).decode("ascii").rstrip("=")


def test_payload_round_trip_is_deterministic() -> None:
    job = JobSpec.from_mapping(c63_mapping())

    first = encode_job(job)
    second = encode_job(job)

    assert first == second
    assert decode_job(first) == job


@pytest.mark.parametrize("value", ["%%%", "not base64!", "A", "é"])
def test_rejects_invalid_base64(value: str) -> None:
    with pytest.raises(JobValidationError, match="base64"):
        decode_job(value)


def test_rejects_non_utf8_payload() -> None:
    with pytest.raises(JobValidationError, match="UTF-8"):
        decode_job(encoded_bytes(b"\xff\xfe"))


def test_rejects_invalid_json() -> None:
    with pytest.raises(JobValidationError, match="JSON"):
        decode_job(encoded_bytes(b"{not-json}"))


def test_rejects_json_arrays() -> None:
    with pytest.raises(JobValidationError, match="object"):
        decode_job(encoded_bytes(b"[]"))


def test_rejects_encoded_input_over_32_kib_before_decoding() -> None:
    with pytest.raises(JobValidationError, match="encoded payload"):
        decode_job("A" * (32 * 1024 + 1))


def test_rejects_decoded_input_over_default_limit() -> None:
    raw = json.dumps({"padding": "x" * 17_000}).encode("utf-8")

    with pytest.raises(JobValidationError, match="decoded payload"):
        decode_job(encoded_bytes(raw))


def test_custom_decoded_limit_is_honored() -> None:
    job = JobSpec.from_mapping(c63_mapping())
    payload = encode_job(job)

    with pytest.raises(JobValidationError, match="decoded payload"):
        decode_job(payload, max_bytes=10)


def test_unknown_top_level_key_is_rejected_after_decode() -> None:
    raw = json.dumps({**JobSpec.from_mapping(c63_mapping()).to_dict(), "command": "calc"}).encode(
        "utf-8"
    )

    with pytest.raises(JobValidationError, match="unknown fields"):
        decode_job(encoded_bytes(raw))
