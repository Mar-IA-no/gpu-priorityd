from __future__ import annotations

import fcntl
import json
import os
import tempfile
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator

from .models import JobRecord


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def atomic_json(path: Path, payload: dict[str, Any], mode: int = 0o600) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=path.parent, delete=False) as handle:
        json.dump(payload, handle, ensure_ascii=False, indent=2)
        handle.write("\n")
        temporary = Path(handle.name)
    os.chmod(temporary, mode)
    temporary.replace(path)


class Registry:
    def __init__(self, run_root: Path, lock_path: Path):
        self.run_root = run_root
        self.jobs_root = run_root / "jobs"
        self.lock_path = lock_path

    @contextmanager
    def lock(self) -> Iterator[None]:
        self.lock_path.parent.mkdir(parents=True, exist_ok=True)
        with self.lock_path.open("a+") as handle:
            os.fchmod(handle.fileno(), 0o600)
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
            try:
                yield
            finally:
                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)

    def _job_path(self, unit: str) -> Path:
        return self.jobs_root / f"{unit}.json"

    def _marker_path(self, unit: str) -> Path:
        return self.jobs_root / f"{unit}.preempted"

    def register(self, record: JobRecord) -> None:
        atomic_json(self._job_path(record.unit), record.to_dict(), mode=0o600)

    def remove(self, unit: str) -> None:
        self._job_path(unit).unlink(missing_ok=True)
        self._marker_path(unit).unlink(missing_ok=True)

    def list(self) -> dict[str, JobRecord]:
        records: dict[str, JobRecord] = {}
        if not self.jobs_root.is_dir():
            return records
        for path in self.jobs_root.glob("*.service.json"):
            try:
                payload = json.loads(path.read_text(encoding="utf-8"))
                record = JobRecord(
                    unit=str(payload["unit"]),
                    name=str(payload["name"]),
                    owner=str(payload["owner"]),
                    created_at=str(payload["created_at"]),
                )
                if path.name != f"{record.unit}.json":
                    continue
            except (OSError, KeyError, TypeError, json.JSONDecodeError):
                continue
            records[record.unit] = record
        return records

    def mark_preempted(self, unit: str, reason: str) -> None:
        atomic_json(
            self._marker_path(unit),
            {"unit": unit, "reason": reason, "at": utc_now()},
            mode=0o600,
        )

    def was_preempted(self, unit: str) -> bool:
        return self._marker_path(unit).is_file()
