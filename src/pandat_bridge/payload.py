from __future__ import annotations

import base64
import binascii
import json
from typing import Mapping

from .models import JobSpec, JobValidationError


MAX_ENCODED_BYTES = 32 * 1024
DEFAULT_MAX_DECODED_BYTES = 16 * 1024


def encode_job(job: JobSpec) -> str:
    raw = json.dumps(
        job.to_dict(),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")
    if len(raw) > DEFAULT_MAX_DECODED_BYTES:
        raise JobValidationError("decoded payload exceeds 16384 bytes")
    encoded = base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")
    if len(encoded) > MAX_ENCODED_BYTES:
        raise JobValidationError("encoded payload exceeds 32768 bytes")
    return encoded


def decode_job(value: str, max_bytes: int = DEFAULT_MAX_DECODED_BYTES) -> JobSpec:
    if not isinstance(value, str):
        raise JobValidationError("payload must be a base64 string")
    if len(value) > MAX_ENCODED_BYTES:
        raise JobValidationError("encoded payload exceeds 32768 bytes")
    if isinstance(max_bytes, bool) or not isinstance(max_bytes, int) or max_bytes < 1:
        raise JobValidationError("max_bytes must be a positive integer")
    try:
        encoded = value.encode("ascii")
        padding = b"=" * (-len(encoded) % 4)
        raw = base64.b64decode(encoded + padding, altchars=b"-_", validate=True)
    except (UnicodeEncodeError, binascii.Error, ValueError) as exc:
        raise JobValidationError("payload is not valid URL-safe base64") from exc
    if len(raw) > max_bytes:
        raise JobValidationError(f"decoded payload exceeds {max_bytes} bytes")
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise JobValidationError("payload is not valid UTF-8") from exc
    try:
        data = json.loads(text)
    except (json.JSONDecodeError, RecursionError) as exc:
        raise JobValidationError("payload is not valid JSON") from exc
    if not isinstance(data, Mapping):
        raise JobValidationError("job must be a JSON object")
    return JobSpec.from_mapping(data)
