from __future__ import annotations

import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Sequence

from .config import Config, GPUConfig, PathConfig, PreemptionConfig, ServiceConfig
from .controller import Controller
from .errors import AdmissionBlocked
from .models import GPUProcess, GPUSummary, JobRecord
from .registry import Registry, utc_now


class FakeProcess:
    def poll(self) -> int | None:
        return 0

    def wait(self) -> int:
        return 0


class FakeSupervisor:
    def __init__(self, states: dict[str, str], on_stop=None):
        self.states = states
        self.stopped: list[str] = []
        self.on_stop = on_stop

    def state(self, unit: str) -> str:
        return self.states.get(unit, "inactive")

    def stop(self, unit: str, timeout: float) -> None:
        self.stopped.append(unit)
        self.states[unit] = "inactive"
        if self.on_stop:
            self.on_stop(unit)

    def start_transient(
        self,
        unit: str,
        command: Sequence[str],
        grace_seconds: int,
        *,
        owner: str,
        working_directory: Path,
    ):
        self.states[unit] = "active"
        return FakeProcess()

    def reset_failed(self, unit: str) -> None:
        return None


class FakeInspector:
    def __init__(self, processes: list[GPUProcess], total_mib: int = 24576):
        self.items = processes
        self.total_mib = total_mib

    def processes(self) -> list[GPUProcess]:
        return list(self.items)

    def remove_unit(self, unit: str) -> None:
        self.items = [item for item in self.items if item.unit != unit]

    def summary(self) -> GPUSummary:
        used = sum(item.used_mib for item in self.items)
        return GPUSummary(0, used, self.total_mib - used, self.total_mib, 0, 40)


def _config(root: Path) -> Config:
    return Config(
        gpu=GPUConfig(index=0, required_free_mib=22000),
        service=ServiceConfig(
            unit="interactive.service",
            protected_units=("interactive.service", "safety.service"),
        ),
        preemption=PreemptionConfig(),
        paths=PathConfig(
            state_root=root / "state",
            run_root=root / "run",
            lock_path=root / "controller.lock",
        ),
    )


def run_simulation() -> dict[str, object]:
    with tempfile.TemporaryDirectory(prefix="gpu-priorityd-") as temporary:
        root = Path(temporary)
        config = _config(root)
        registry = Registry(config.paths.run_root, config.paths.lock_path)
        job = JobRecord(
            unit="gpu-priority-job-demo.service",
            name="demo-batch",
            owner="simulator",
            created_at=utc_now(),
        )
        registry.register(job)
        inspector = FakeInspector(
            [GPUProcess(100, "safety", 350, "safety.service")]
        )
        supervisor = FakeSupervisor(
            {job.unit: "active", "interactive.service": "inactive", "safety.service": "active"},
            on_stop=inspector.remove_unit,
        )
        controller = Controller(config, supervisor, inspector, registry)

        admitted = controller.admit()
        race_closed = job.unit in supervisor.stopped
        protected_survived = supervisor.state("safety.service") == "active"

        inspector.items.append(GPUProcess(200, "unknown", 512, "session.scope"))
        try:
            controller.admit()
        except AdmissionBlocked:
            unknown_blocked = True
        else:
            unknown_blocked = False

        return {
            "simulation": "ok" if race_closed and protected_survived and unknown_blocked else "failed",
            "registered_before_cuda_was_preempted": race_closed,
            "protected_process_survived": protected_survived,
            "unknown_process_blocked_admission": unknown_blocked,
            "first_admission": admitted,
        }
