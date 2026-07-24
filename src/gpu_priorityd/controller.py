from __future__ import annotations

import json
import os
import re
import sys
import time
from pathlib import Path
from typing import Any, Sequence

from .command import run_command
from .config import Config
from .errors import AdmissionBlocked, GPUPriorityError
from .linux import current_owner
from .models import JobRecord, ProcessClasses
from .registry import Registry, utc_now


ACTIVE_STATES = {"active", "activating"}


def sanitize_name(value: str) -> str:
    cleaned = re.sub(r"[^A-Za-z0-9_.-]+", "-", value).strip("-.")
    return cleaned[:40] or "job"


class Controller:
    def __init__(self, config: Config, supervisor: Any, inspector: Any, registry: Registry):
        self.config = config
        self.supervisor = supervisor
        self.inspector = inspector
        self.registry = registry
        self.events_path = config.paths.state_root / "events.jsonl"

    def event(self, kind: str, **fields: Any) -> None:
        payload = {"at": utc_now(), "event": kind, **fields}
        self.events_path.parent.mkdir(parents=True, exist_ok=True)
        with self.events_path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(payload, ensure_ascii=False, separators=(",", ":")) + "\n")
        self.events_path.chmod(0o640)

    def classify(self, jobs: dict[str, JobRecord] | None = None) -> ProcessClasses:
        records = jobs if jobs is not None else self.registry.list()
        protected_units = set(self.config.service.protected_units)
        protected = []
        registered = []
        unknown = []
        for process in self.inspector.processes():
            if process.unit in protected_units:
                protected.append(process)
            elif process.unit in records:
                registered.append(process)
            else:
                unknown.append(process)
        return ProcessClasses(tuple(protected), tuple(registered), tuple(unknown))

    def _wait_for_release(self, units: set[str]) -> None:
        deadline = time.monotonic() + self.config.preemption.release_timeout_seconds
        while time.monotonic() < deadline:
            active = any(self.supervisor.state(unit) in ACTIVE_STATES for unit in units)
            resident = any(process.unit in units for process in self.inspector.processes())
            if not active and not resident:
                return
            time.sleep(0.25)
        raise AdmissionBlocked(f"registered jobs did not release resources: {sorted(units)}")

    def admit(self) -> dict[str, Any]:
        with self.registry.lock():
            jobs = self.registry.list()
            classes = self.classify(jobs)
            if classes.unknown:
                self.event("admission_blocked_unknown", unknown=[item.to_dict() for item in classes.unknown])
                raise AdmissionBlocked(
                    "unknown CUDA processes block admission: "
                    + ", ".join(f"pid={item.pid} unit={item.unit}" for item in classes.unknown)
                )

            units = {
                unit for unit in jobs if self.supervisor.state(unit) in ACTIVE_STATES
            }
            units.update(item.unit for item in classes.registered if item.unit)
            for unit in sorted(units):
                record = jobs.get(unit)
                self.registry.mark_preempted(unit, "priority_service_admission")
                self.event(
                    "job_preemption_requested",
                    unit=unit,
                    name=record.name if record else None,
                    owner=record.owner if record else None,
                )
                self.supervisor.stop(
                    unit,
                    timeout=self.config.preemption.grace_seconds + 10,
                )
            if units:
                self._wait_for_release(units)

            remaining = self.classify(self.registry.list())
            if remaining.registered or remaining.unknown:
                raise AdmissionBlocked("CUDA processes remained after preemption")
            summary = self.inspector.summary()
            if summary.free_mib < self.config.gpu.required_free_mib:
                raise AdmissionBlocked(
                    f"only {summary.free_mib} MiB free; "
                    f"{self.config.gpu.required_free_mib} MiB required"
                )
            result = {
                "admitted": True,
                "preempted_units": sorted(units),
                "gpu": summary.to_dict(),
                "protected": [item.to_dict() for item in remaining.protected],
            }
            self.event("priority_service_admitted", **result)
            return result

    def run_job(self, name: str, command: Sequence[str]) -> int:
        if not command:
            raise GPUPriorityError("run requires a command after --")
        unit = f"gpu-priority-job-{time.time_ns()}-{sanitize_name(name)}.service"
        record = JobRecord(
            unit=unit,
            name=name,
            owner=current_owner(),
            created_at=utc_now(),
        )
        process = None
        with self.registry.lock():
            if self.supervisor.state(self.config.service.unit) in ACTIVE_STATES:
                raise GPUPriorityError(
                    f"priority service {self.config.service.unit} is active; yield it before borrowing the GPU"
                )
            self.registry.register(record)
            self.event("job_registered", **record.to_dict())
            try:
                process = self.supervisor.start_transient(
                    unit,
                    command,
                    self.config.preemption.grace_seconds,
                    owner=record.owner,
                    working_directory=Path(os.getcwd()),
                )
                deadline = time.monotonic() + 10
                while time.monotonic() < deadline:
                    if self.supervisor.state(unit) in ACTIVE_STATES or process.poll() is not None:
                        break
                    time.sleep(0.05)
            except Exception:
                self.registry.remove(unit)
                raise

        assert process is not None
        returncode = process.wait()
        preempted = self.registry.was_preempted(unit)
        try:
            self.event(
                "job_finished",
                unit=unit,
                name=name,
                returncode=returncode,
                preempted=preempted,
            )
        finally:
            self.registry.remove(unit)
            self.supervisor.reset_failed(unit)
        if preempted:
            print(
                f"gpu-priority: job '{name}' was preempted by {self.config.service.unit}",
                file=sys.stderr,
            )
            return self.config.preemption.exit_code
        return returncode

    def yield_service(self, force: bool = False) -> dict[str, Any]:
        unit = self.config.service.unit
        with self.registry.lock():
            if self.supervisor.state(unit) not in ACTIVE_STATES:
                return {"stopped": False, "reason": "already_inactive"}
            if not force:
                command = self.config.service.safe_to_stop_command
                if not command:
                    raise GPUPriorityError(
                        "no safe_to_stop_command is configured; use --force only if state loss is acceptable"
                    )
                result = run_command(command, timeout=30)
                if result.returncode != 0:
                    raise GPUPriorityError("safe_to_stop_command rejected the yield")
            self.event("priority_service_stop_requested", unit=unit, force=force)
            self.supervisor.stop(unit, timeout=self.config.preemption.release_timeout_seconds + 10)
            self._wait_for_release({unit})
            summary = self.inspector.summary()
            self.event("priority_service_stopped", unit=unit, gpu=summary.to_dict())
            return {"stopped": True, "gpu": summary.to_dict()}

    def status(self) -> dict[str, Any]:
        jobs = self.registry.list()
        classes = self.classify(jobs)
        return {
            "schema_version": 1,
            "generated_at": utc_now(),
            "priority_service": {
                "unit": self.config.service.unit,
                "state": self.supervisor.state(self.config.service.unit),
            },
            "gpu": self.inspector.summary().to_dict(),
            "processes": classes.to_dict(),
            "registered_jobs": [record.to_dict() for record in jobs.values()],
        }
