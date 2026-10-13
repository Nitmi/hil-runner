from __future__ import annotations

import os
import queue
import subprocess
import threading
import time
from pathlib import Path

from .common import HilError, decode
from .winjob import Job

MAX_LINE = 2 * 1024 * 1024
MAX_STDOUT = 16 * 1024 * 1024
MAX_STDERR = 1024 * 1024


class Capture:
    def __init__(self, fd: int, destination: Path, *, lines: bool, limit: int):
        self.fd = fd
        self.destination = destination
        self.events: queue.Queue = queue.Queue(maxsize=16)
        self.lines = lines
        self.limit = limit
        self.error: Exception | None = None
        self.bytes = 0
        self.output_fd = os.open(
            destination, os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_BINARY", 0), 0o600
        )
        if os.name == "nt":
            import msvcrt

            msvcrt.setmode(fd, os.O_BINARY)
        self.worker = threading.Thread(target=self.read, daemon=True)
        self.worker.start()

    def read(self):
        pending = bytearray()
        try:
            while block := os.read(self.fd, 4096):
                if self.bytes + len(block) > self.limit:
                    raise HilError("LIMIT_EXCEEDED", "native output exceeds its byte limit")
                remaining = block
                while remaining:
                    remaining = remaining[os.write(self.output_fd, remaining) :]
                self.bytes += len(block)
                if self.lines:
                    pending.extend(block)
                    while b"\n" in pending:
                        line, _, rest = pending.partition(b"\n")
                        if len(line) > MAX_LINE:
                            raise HilError("LIMIT_EXCEEDED", "native response line exceeds 2 MiB")
                        self.events.put(bytes(line), timeout=0.25)
                        pending = bytearray(rest)
                    if len(pending) > MAX_LINE:
                        raise HilError("LIMIT_EXCEEDED", "native response line exceeds 2 MiB")
            if pending:
                raise HilError("PROTOCOL_ERROR", "native stdout ended with an incomplete JSON line")
        except Exception as error:
            self.error = error
        finally:
            os.close(self.output_fd)


class Child:
    def __init__(self, command: list[str], directory: Path, name: str, *, jsonl=True):
        self.job = Job()
        self.process: subprocess.Popen | None = None
        self.stdout: Capture | None = None
        self.stderr: Capture | None = None
        self.cleanup: dict | None = None
        try:
            self.process = subprocess.Popen(
                command,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                cwd=directory,
                shell=False,
                close_fds=True,
                creationflags=4 | 0x08000000,  # CREATE_SUSPENDED | CREATE_NO_WINDOW
            )
            self.stdout = Capture(
                self.process.stdout.fileno(),
                directory / (name + ".stdout.jsonl" if jsonl else name + ".stdout.bin"),
                lines=jsonl,
                limit=MAX_STDOUT,
            )
            self.stderr = Capture(
                self.process.stderr.fileno(),
                directory / (name + ".stderr.log"),
                lines=False,
                limit=MAX_STDERR,
            )
            self.job.assign_and_resume(self.process.pid)
        except BaseException:
            # If assignment failed, kill the still-suspended process directly too.
            if self.process is not None:
                self.process.kill()
                self.process.wait(timeout=5)
            self.stop(1)
            raise

    def check_capture(self):
        for capture in (self.stdout, self.stderr):
            if capture is not None and capture.error:
                if isinstance(capture.error, HilError):
                    raise capture.error
                raise HilError("HOST_IO_ERROR", "native output capture failed") from capture.error

    def response(self, timeout: float, guard) -> dict:
        deadline = time.monotonic() + timeout
        while True:
            guard()
            self.check_capture()
            try:
                payload = self.stdout.events.get(timeout=0.05)
                value = decode(payload)
                if not isinstance(value, dict):
                    raise HilError("PROTOCOL_ERROR", "native response must be an object")
                return value
            except queue.Empty:
                if not self.stdout.worker.is_alive() and self.stdout.events.empty():
                    raise HilError(
                        "NATIVE_FAILURE", "native process ended without its response"
                    ) from None
                if time.monotonic() >= deadline:
                    raise HilError("TIMEOUT", "native response deadline exceeded") from None

    def send(self, payload: bytes, timeout: float, guard):
        if len(payload) > 8192:
            raise HilError("INVALID_INPUT", "native request exceeds 8 KiB")
        finished = threading.Event()
        errors = []

        def write():
            try:
                remaining = payload
                while remaining:
                    remaining = remaining[os.write(self.process.stdin.fileno(), remaining) :]
            except OSError as error:
                errors.append(error)
            finally:
                finished.set()

        thread = threading.Thread(target=write, daemon=True)
        thread.start()
        deadline = time.monotonic() + timeout
        while not finished.wait(0.05):
            guard()
            self.check_capture()
            if time.monotonic() >= deadline:
                raise HilError("TIMEOUT", "native stdin write deadline exceeded")
        if errors:
            raise HilError("NATIVE_FAILURE", "native stdin closed") from errors[0]

    def wait(self, timeout: float, guard):
        deadline = time.monotonic() + timeout
        while self.process.poll() is None or self.job.active() != 0:
            guard()
            self.check_capture()
            if time.monotonic() >= deadline:
                raise HilError("TIMEOUT", "native process tree exit deadline exceeded")
            time.sleep(0.025)
        return self.process.returncode

    def control(self, timeout: float, guard) -> tuple[int, bytes]:
        code = self.wait(timeout, guard)
        self.stdout.worker.join(timeout=1)
        self.stderr.worker.join(timeout=1)
        self.check_capture()
        if self.stdout.worker.is_alive() or self.stderr.worker.is_alive():
            raise HilError("TIMEOUT", "native control capture did not finish")
        return code, self.stdout.destination.read_bytes()

    def stop(self, timeout: float) -> dict:
        if self.cleanup is not None:
            return self.cleanup
        forced = False
        stopped = False
        errors = []
        try:
            if self.job.active():
                forced = True
                self.job.terminate()
            deadline = time.monotonic() + timeout
            while self.job.active() and time.monotonic() < deadline:
                time.sleep(0.025)
            stopped = self.job.active() == 0
            if self.process is not None:
                self.process.wait(timeout=max(0.1, deadline - time.monotonic()))
        except Exception as error:
            errors.append(type(error).__name__)
        finally:
            try:
                self.job.close()
            except Exception as error:
                errors.append(type(error).__name__)
        for capture in (self.stdout, self.stderr):
            if capture is not None:
                capture.worker.join(timeout=1)
                if capture.worker.is_alive() or capture.error:
                    errors.append("capture_incomplete")
        if self.process is not None:
            for stream in (self.process.stdin, self.process.stdout, self.process.stderr):
                try:
                    stream.close()
                except OSError:
                    errors.append("pipe_close_failed")
        self.cleanup = {
            "owner_pid": self.process.pid if self.process else None,
            "process_tree_stopped": stopped,
            "forced_termination": forced,
            "exit_code": self.process.returncode if self.process else None,
            "capture_complete": not errors,
            "errors": errors,
        }
        return self.cleanup
