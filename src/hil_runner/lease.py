from __future__ import annotations

import errno
import os
import stat
import time
import uuid
from datetime import UTC, datetime
from pathlib import Path

from .common import HilError, digest, invalid

if os.name == "nt":
    import msvcrt
else:
    import fcntl


def lock(fd: int) -> None:
    if os.name == "nt":
        os.lseek(fd, 0, os.SEEK_SET)
        msvcrt.locking(fd, msvcrt.LK_NBLCK, 1)
    else:
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)


def unlock(fd: int) -> None:
    if os.name == "nt":
        os.lseek(fd, 0, os.SEEK_SET)
        msvcrt.locking(fd, msvcrt.LK_UNLCK, 1)
    else:
        fcntl.flock(fd, fcntl.LOCK_UN)


def bounds(duration: int, idle: int) -> None:
    if type(duration) is not int or not 1 <= duration <= 3600:
        raise invalid("duration must be an integer from 1 to 3600 seconds")
    if type(idle) is not int or not 1 <= idle <= duration:
        raise invalid("idle timeout must be an integer from 1 to duration seconds")


class Lease:
    """One live owner process; files are permanent identities, not stale records."""

    def __init__(self, plan: dict, *, duration: int, idle: int):
        bounds(duration, idle)
        self.plan = plan
        self.root = Path(plan["lease_root"])
        self.duration = duration
        self.idle = idle
        self.lease_id = "lease_" + uuid.uuid4().hex
        self.handles: list[tuple[str, Path, int]] = []
        self.started: float | None = None
        self.last_activity: float | None = None
        self.started_at: str | None = None
        self.root_identity: tuple[int, int] | None = None

    def acquire(self) -> dict:
        if self.handles or self.started is not None:
            raise invalid("lease objects cannot be acquired more than once")
        self.root.mkdir(mode=0o700, parents=True, exist_ok=True)
        root_stat = self.root.stat()
        self.root_identity = (root_stat.st_dev, root_stat.st_ino)
        try:
            for resource in self.plan["resources"]:
                path = self.root / (digest(resource.encode("utf-8")) + ".lock")
                try:
                    before = path.lstat()
                except FileNotFoundError:
                    before = None
                if before is not None and (
                    not stat.S_ISREG(before.st_mode) or before.st_nlink != 1
                ):
                    raise invalid("lock paths must be regular files with one link")
                flags = os.O_CREAT | os.O_RDWR | getattr(os, "O_NOFOLLOW", 0)
                flags |= getattr(os, "O_BINARY", 0)
                fd = os.open(path, flags, 0o600)
                acquired = False
                try:
                    os.set_inheritable(fd, False)
                    opened, named = os.fstat(fd), path.lstat()
                    if (
                        not stat.S_ISREG(opened.st_mode)
                        or not stat.S_ISREG(named.st_mode)
                        or opened.st_nlink != 1
                        or (opened.st_dev, opened.st_ino) != (named.st_dev, named.st_ino)
                    ):
                        raise invalid("lock path changed or is not a regular single-link file")
                    try:
                        lock(fd)
                    except OSError as error:
                        if error.errno in {errno.EACCES, errno.EAGAIN, errno.EDEADLK}:
                            raise HilError(
                                "RESOURCE_BUSY",
                                "resource is owned by another lease",
                                data={"resource": resource, "lease_root": str(self.root)},
                            ) from error
                        raise
                    acquired = True
                    self.handles.append((resource, path, fd))
                finally:
                    if not acquired:
                        os.close(fd)
            self.started = self.last_activity = time.monotonic()
            self.started_at = datetime.now(UTC).isoformat()
            self.check_continuity()
            return self.status()
        except BaseException:
            self.release("acquisition_rollback")
            raise

    def check_continuity(self) -> None:
        current = self.root.stat()
        if (current.st_dev, current.st_ino) != self.root_identity:
            raise HilError("HOST_IO_ERROR", "lease root identity changed")
        for _, path, fd in self.handles:
            opened, named = os.fstat(fd), path.lstat()
            if (
                not stat.S_ISREG(named.st_mode)
                or named.st_nlink != 1
                or (opened.st_dev, opened.st_ino) != (named.st_dev, named.st_ino)
            ):
                raise HilError(
                    "HOST_IO_ERROR", "locked file identity changed; stop native operations"
                )

    def timeout(self) -> float:
        if self.started is None or self.last_activity is None:
            return 0
        return max(
            0, min(self.started + self.duration, self.last_activity + self.idle) - time.monotonic()
        )

    def expiry_reason(self) -> str:
        if self.started is not None and time.monotonic() >= self.started + self.duration:
            return "duration_expired"
        return "idle_expired"

    def status(self, *, touch: bool = False) -> dict:
        if self.started is None or not self.handles or self.timeout() <= 0:
            raise HilError("PROTOCOL_ERROR", "lease is not active")
        self.check_continuity()
        if touch:
            self.last_activity = time.monotonic()
        return {
            **self.plan,
            "effects": ["host_lock_file_create", "host_exclusive_file_lock"],
            "lease_id": self.lease_id,
            "status": "active",
            "owner_pid": os.getpid(),
            "started_at": self.started_at,
            "duration_seconds": self.duration,
            "idle_timeout_seconds": self.idle,
            "remaining_ms": int(self.timeout() * 1000),
            "ownership_scope": "participating_processes_using_same_local_lease_root",
        }

    def release(self, reason: str) -> dict:
        errors = []
        handles, self.handles = self.handles, []
        for _, _, fd in reversed(handles):
            try:
                unlock(fd)
            except OSError as error:
                errors.append(f"unlock: {error.__class__.__name__}")
            finally:
                try:
                    os.close(fd)
                except OSError as error:
                    errors.append(f"close: {error.__class__.__name__}")
        result = {
            "lease_id": self.lease_id,
            "status": "released",
            "reason": reason,
            "resources": self.plan["resources"],
            "lease_root": str(self.root),
            "host_handles_closed": not errors,
            "lock_files_retained": True,
            "native_operations_stopped": False,
            "target_cleanup_verified": False,
        }
        if errors:
            raise HilError("HOST_IO_ERROR", "; ".join(errors), data=result)
        return result
