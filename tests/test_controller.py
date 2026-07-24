from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from typing import Sequence

from gpu_priorityd.config import Config, GPUConfig, PathConfig, PreemptionConfig, ServiceConfig
from gpu_priorityd.controller import Controller
from gpu_priorityd.errors import AdmissionBlocked, GPUPriorityError
from gpu_priorityd.models import GPUProcess, JobRecord
from gpu_priorityd.registry import Registry
from gpu_priorityd.simulator import FakeInspector, FakeSupervisor


class PreemptedProcess:
    def __init__(self, registry: Registry, unit: str):
        self.registry = registry
        self.unit = unit

    def poll(self) -> int | None:
        return None

    def wait(self) -> int:
        self.registry.mark_preempted(self.unit, "test-preemption")
        return -15


class PreemptingSupervisor(FakeSupervisor):
    def __init__(self, registry: Registry):
        super().__init__({})
        self.registry = registry

    def start_transient(
        self,
        unit: str,
        command: Sequence[str],
        grace_seconds: int,
        *,
        owner: str,
        working_directory: Path,
    ) -> PreemptedProcess:
        self.states[unit] = "active"
        return PreemptedProcess(self.registry, unit)


class ControllerTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory(prefix="gpu-priorityd-controller-")
        root = Path(self.temporary.name)
        self.config = Config(
            gpu=GPUConfig(index=0, required_free_mib=20000),
            service=ServiceConfig(
                unit="interactive.service",
                protected_units=("interactive.service", "safety.service"),
            ),
            preemption=PreemptionConfig(grace_seconds=1, release_timeout_seconds=1),
            paths=PathConfig(root / "state", root / "run", root / "controller.lock"),
        )
        self.registry = Registry(self.config.paths.run_root, self.config.paths.lock_path)

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def controller(self, inspector: FakeInspector, states: dict[str, str]) -> tuple[Controller, FakeSupervisor]:
        supervisor = FakeSupervisor(states, on_stop=inspector.remove_unit)
        return Controller(self.config, supervisor, inspector, self.registry), supervisor

    def register(self, unit: str = "gpu-priority-job-test.service") -> None:
        self.registry.register(JobRecord(unit, "test", "owner", "now"))

    def test_unknown_process_blocks_before_any_stop(self) -> None:
        self.register()
        inspector = FakeInspector([GPUProcess(22, "manual", 1000, "user.scope")])
        controller, supervisor = self.controller(
            inspector,
            {"gpu-priority-job-test.service": "active"},
        )
        with self.assertRaisesRegex(AdmissionBlocked, "unknown CUDA"):
            controller.admit()
        self.assertEqual(supervisor.stopped, [])

    def test_active_registered_unit_is_stopped_before_cuda_allocation(self) -> None:
        unit = "gpu-priority-job-race.service"
        self.register(unit)
        inspector = FakeInspector([GPUProcess(11, "safety", 200, "safety.service")])
        controller, supervisor = self.controller(inspector, {unit: "active"})
        result = controller.admit()
        self.assertEqual(result["preempted_units"], [unit])
        self.assertIn(unit, supervisor.stopped)
        self.assertTrue(self.registry.was_preempted(unit))

    def test_protected_process_survives(self) -> None:
        inspector = FakeInspector([GPUProcess(11, "safety", 200, "safety.service")])
        controller, supervisor = self.controller(inspector, {"safety.service": "active"})
        result = controller.admit()
        self.assertEqual(len(result["protected"]), 1)
        self.assertEqual(supervisor.stopped, [])

    def test_insufficient_free_memory_blocks(self) -> None:
        inspector = FakeInspector([GPUProcess(11, "safety", 6000, "safety.service")])
        controller, _ = self.controller(inspector, {"safety.service": "active"})
        with self.assertRaisesRegex(AdmissionBlocked, "required"):
            controller.admit()

    def test_status_omits_registered_command(self) -> None:
        self.register()
        inspector = FakeInspector([])
        controller, _ = self.controller(inspector, {})
        status = controller.status()
        self.assertNotIn("command", status["registered_jobs"][0])

    def test_run_refuses_while_priority_service_is_active(self) -> None:
        inspector = FakeInspector([])
        controller, _ = self.controller(inspector, {"interactive.service": "active"})
        with self.assertRaisesRegex(GPUPriorityError, "is active"):
            controller.run_job("test", ("true",))

    def test_preempted_job_returns_dedicated_exit_code(self) -> None:
        inspector = FakeInspector([])
        supervisor = PreemptingSupervisor(self.registry)
        controller = Controller(self.config, supervisor, inspector, self.registry)
        self.assertEqual(controller.run_job("test", ("true",)), 75)
        self.assertEqual(self.registry.list(), {})


if __name__ == "__main__":
    unittest.main()
