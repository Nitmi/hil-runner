from __future__ import annotations

import json
import os
import queue
import threading
import time
from collections.abc import Callable

from .common import MAX_REQUEST_BYTES, MAX_REQUESTS, HilError, decode, report
from .lease import Lease


def requests(fd: int, messages: queue.Queue) -> None:
    """Only raw os.read in the daemon: no buffered stdin lock at interpreter exit."""
    pending = bytearray()
    try:
        while True:
            block = os.read(fd, MAX_REQUEST_BYTES + 1)
            if not block:
                if pending:
                    messages.put(("line", bytes(pending)))
                messages.put(("eof", None))
                return
            pending.extend(block)
            while b"\n" in pending:
                line, _, rest = pending.partition(b"\n")
                if len(line) > MAX_REQUEST_BYTES:
                    messages.put(("oversized", None))
                    return
                messages.put(("line", bytes(line)))
                pending = bytearray(rest)
            if len(pending) > MAX_REQUEST_BYTES:
                messages.put(("oversized", None))
                return
    except OSError:
        messages.put(("io_error", None))
    finally:
        os.close(fd)


def request(payload: bytes, lease_id: str) -> tuple[str, str]:
    value = decode(payload)
    if not isinstance(value, dict) or set(value) != {"id", "operation", "lease_id"}:
        raise HilError("PROTOCOL_ERROR", "request requires exactly id, operation, lease_id")
    request_id = value["id"]
    if (
        not isinstance(request_id, str)
        or not 1 <= len(request_id) <= 64
        or not request_id.isascii()
        or not request_id.isprintable()
    ):
        raise HilError("PROTOCOL_ERROR", "request id must be 1-64 printable ASCII characters")
    if value["lease_id"] != lease_id:
        raise HilError("PROTOCOL_ERROR", "stale or different lease_id")
    if value["operation"] not in ("lease.status", "lease.close"):
        raise HilError("PROTOCOL_ERROR", "only lease.status and lease.close are supported")
    return request_id, value["operation"]


def serve(lease: Lease, input_fd: int, emit: Callable[[dict], None]) -> int:
    messages: queue.Queue = queue.Queue(maxsize=16)
    reason = "host_error"
    code = 0
    final_operation = "lease.closed"
    final_id = None
    terminal_error = None
    try:
        opened = lease.acquire()
        emit(report("lease.open", data=opened))
        reader = threading.Thread(target=requests, args=(os.dup(input_fd), messages), daemon=True)
        reader.start()
        processed = 0
        while processed < MAX_REQUESTS:
            timeout = lease.timeout()
            if timeout <= 0:
                reason = lease.expiry_reason()
                break
            try:
                kind, payload = messages.get(timeout=min(timeout, 0.25))
            except queue.Empty:
                # Detect host namespace replacement while stdin is idle too.
                lease.check_continuity()
                continue
            if lease.timeout() <= 0:
                reason = lease.expiry_reason()
                break
            if kind == "eof":
                reason = "stdin_eof"
                break
            if kind in ("oversized", "io_error"):
                reason = kind
                terminal_error = HilError(
                    "PROTOCOL_ERROR" if kind == "oversized" else "HOST_IO_ERROR",
                    "stdin request limit or I/O error",
                )
                code = 2 if kind == "oversized" else 4
                break
            processed += 1
            try:
                request_id, operation = request(payload, lease.lease_id)
            except HilError as error:
                emit(report("lease.error", error=error))
                continue
            if operation == "lease.close":
                reason, final_operation, final_id = "requested", operation, request_id
                break
            emit(report(operation, data=lease.status(touch=True), request_id=request_id))
        else:
            reason = "request_limit"
            terminal_error = HilError("PROTOCOL_ERROR", "256 request limit reached")
            code = 2
    except HilError as error:
        terminal_error = error
        code = {"RESOURCE_BUSY": 3, "HOST_IO_ERROR": 4}.get(error.code, 2)
    except (OSError, ValueError) as error:
        terminal_error = HilError("HOST_IO_ERROR", str(error))
        code = 4
    except KeyboardInterrupt:
        reason = "interrupted"
        code = 130
    finally:
        try:
            cleanup = lease.release(reason)
        except HilError as error:
            terminal_error, cleanup, code = error, error.data, 4
    try:
        # Failed acquisition must never emit a successful release as an acquired lease.
        if terminal_error and terminal_error.data:
            cleanup["failure"] = terminal_error.data
        emit(report(final_operation, data=cleanup, error=terminal_error, request_id=final_id))
    except (OSError, ValueError):
        return 4
    return code


def emit_json(value: dict) -> None:
    # One bounded JSON line; stderr is reserved for non-protocol diagnostics.
    payload = json.dumps(value, ensure_ascii=True, separators=(",", ":")) + "\n"
    data = payload.encode("ascii")
    while data:
        written = os.write(1, data)
        if written <= 0:
            raise OSError("stdout closed")
        data = data[written:]


class OutputPump:
    """A blocked stdout pipe must not block the owner or its lease deadlines."""

    def __init__(self):
        self.messages: queue.Queue = queue.Queue(maxsize=16)
        self.failed = False
        self.writer = threading.Thread(target=self._write, daemon=True)
        self.writer.start()

    def _write(self) -> None:
        try:
            while True:
                item = self.messages.get()
                if item is None:
                    return
                emit_json(item)
        except (OSError, ValueError):
            self.failed = True

    def emit(self, value: dict) -> None:
        if self.failed:
            raise OSError("stdout writer failed")
        try:
            # Give an actively draining writer a bounded scheduling opportunity.
            self.messages.put(value, timeout=0.05)
        except queue.Full as error:
            raise OSError("stdout backpressure exceeded 16 response queue limit") from error

    def finish(self) -> bool:
        deadline = time.monotonic() + 1
        try:
            self.messages.put(None, timeout=1)
        except queue.Full:
            return False
        self.writer.join(timeout=max(0, deadline - time.monotonic()))
        return not self.writer.is_alive() and not self.failed
