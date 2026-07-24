from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from gpu_priorityd.models import JobRecord
from gpu_priorityd.registry import Registry


class RegistryTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory(prefix="gpu-priorityd-registry-")
        root = Path(self.temporary.name)
        self.registry = Registry(root / "run", root / "controller.lock")

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def test_record_marker_and_cleanup(self) -> None:
        record = JobRecord(
            unit="gpu-priority-job-test.service",
            name="test",
            owner="owner",
            created_at="2026-07-24T00:00:00+00:00",
        )
        self.registry.register(record)
        self.assertEqual(self.registry.list()[record.unit], record)
        self.registry.mark_preempted(record.unit, "test")
        self.assertTrue(self.registry.was_preempted(record.unit))
        self.registry.remove(record.unit)
        self.assertEqual(self.registry.list(), {})
        self.assertFalse(self.registry.was_preempted(record.unit))

    def test_invalid_record_is_ignored(self) -> None:
        self.registry.jobs_root.mkdir(parents=True)
        (self.registry.jobs_root / "broken.service.json").write_text("{", encoding="utf-8")
        self.assertEqual(self.registry.list(), {})

    def test_record_cannot_authorize_a_different_unit(self) -> None:
        self.registry.jobs_root.mkdir(parents=True)
        (self.registry.jobs_root / "expected.service.json").write_text(
            '{"unit":"other.service","name":"x","owner":"x","created_at":"now"}',
            encoding="utf-8",
        )
        self.assertEqual(self.registry.list(), {})

    def test_lock_is_owner_only(self) -> None:
        with self.registry.lock():
            mode = self.registry.lock_path.stat().st_mode & 0o777
        self.assertEqual(mode, 0o600)


if __name__ == "__main__":
    unittest.main()
