"""Atomic lock file for the real daily pipeline."""

from datetime import datetime, timezone
import json
import os
from pathlib import Path
import time
from uuid import uuid4


class RunLock:
    """Acquire a run lock or leave an existing fresh/unknown owner untouched."""

    def __init__(self, path: Path, *, now: float | None = None, stale_seconds: float = 7200) -> None:
        self.path = Path(path)
        self.now = now
        self.stale_seconds = stale_seconds
        self.token = uuid4().hex
        self.acquired = False

    def __enter__(self) -> bool:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        for _ in range(3):
            try:
                descriptor = os.open(self.path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            except FileExistsError:
                try:
                    first = self.path.stat()
                    current = self.now if self.now is not None else time.time()
                    if current - first.st_mtime <= self.stale_seconds:
                        return False
                    second = self.path.stat()
                    if (first.st_ino, first.st_mtime_ns, first.st_size) != (second.st_ino, second.st_mtime_ns, second.st_size):
                        return False
                    self.path.unlink()
                except FileNotFoundError:
                    continue
                continue
            try:
                with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
                    timestamp = datetime.fromtimestamp(self.now if self.now is not None else time.time(), timezone.utc)
                    json.dump({"pid": os.getpid(), "created_at": timestamp.isoformat(), "token": self.token}, handle)
            except Exception:
                self.path.unlink(missing_ok=True)
                raise
            self.acquired = True
            return True
        return False

    def __exit__(self, exc_type, exc_value, traceback) -> None:
        if not self.acquired:
            return
        try:
            content = json.loads(self.path.read_text(encoding="utf-8"))
            if isinstance(content, dict) and content.get("token") == self.token:
                self.path.unlink(missing_ok=True)
        except (FileNotFoundError, OSError, ValueError):
            pass
