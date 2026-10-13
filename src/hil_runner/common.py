from __future__ import annotations

import hashlib
import json
from typing import Any

SCHEMA = "embedded-hil-runner.result.v1"
MAX_SELECTION_BYTES = 256 * 1024
MAX_REQUEST_BYTES = 4096
MAX_REQUESTS = 256


class HilError(Exception):
    def __init__(self, code: str, message: str, *, data: dict | None = None):
        super().__init__(message)
        self.code = code
        self.data = data or {}


def invalid(message: str) -> HilError:
    return HilError("INVALID_INPUT", message)


def digest(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def decode(payload: bytes) -> Any:
    depth, quoted, escaped = 0, False, False
    for byte in payload:
        if quoted:
            if escaped:
                escaped = False
            elif byte == 92:
                escaped = True
            elif byte == 34:
                quoted = False
        elif byte == 34:
            quoted = True
        elif byte in (91, 123):
            depth += 1
            if depth > 32:
                raise invalid("JSON nesting exceeds 32 levels")
        elif byte in (93, 125):
            depth -= 1

    def pairs(items):
        value = {}
        for key, item in items:
            if key in value:
                raise invalid("duplicate JSON object key")
            value[key] = item
        return value

    def nonfinite(_):
        raise invalid("non-finite JSON number")

    try:
        return json.loads(
            payload.decode("utf-8"), object_pairs_hook=pairs, parse_constant=nonfinite
        )
    except (ValueError, UnicodeError, RecursionError) as error:
        raise invalid("invalid or overly nested UTF-8 JSON") from error


def report(
    operation: str,
    *,
    data: dict | None = None,
    error: HilError | None = None,
    request_id: str | None = None,
) -> dict:
    return {
        "schema_version": SCHEMA,
        "ok": error is None,
        "operation": operation,
        "request_id": request_id,
        "scope": "host_only_cooperative_leasing",
        "hardware_access": False,
        "component_processes_started": False,
        "authorization_granted": False,
        "target_cleanup_verified": False,
        "data": data or (error.data if error else {}),
        "errors": ([{"code": error.code, "message": str(error)[:1024]}] if error else []),
    }
