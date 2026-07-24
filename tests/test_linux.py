from __future__ import annotations

import subprocess
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from gpu_priorityd.errors import PlatformUnavailable
from gpu_priorityd.linux import NvidiaInspector, SystemdSupervisor


class NvidiaInspectorTests(unittest.TestCase):
    @patch("gpu_priorityd.linux.cgroup_unit", return_value="job.service")
    @patch("gpu_priorityd.linux.run_command")
    @patch.object(NvidiaInspector, "_ensure")
    def test_csv_process_name_and_na_memory_remain_visible(
        self,
        _ensure: Mock,
        run: Mock,
        _cgroup: Mock,
    ) -> None:
        run.return_value = subprocess.CompletedProcess([], 0, '123, "python, worker", N/A\n', "")
        process = NvidiaInspector(0).processes()[0]
        self.assertEqual(process.pid, 123)
        self.assertEqual(process.process_name, "python, worker")
        self.assertEqual(process.used_mib, 0)
        self.assertEqual(process.unit, "job.service")

    @patch("gpu_priorityd.linux.run_command")
    @patch.object(NvidiaInspector, "_ensure")
    def test_malformed_process_row_fails_closed(self, _ensure: Mock, run: Mock) -> None:
        run.return_value = subprocess.CompletedProcess([], 0, "not-a-pid, python, 100\n", "")
        with self.assertRaises(PlatformUnavailable):
            NvidiaInspector(0).processes()


class SystemdSupervisorTests(unittest.TestCase):
    @patch("gpu_priorityd.linux.subprocess.Popen")
    @patch.object(SystemdSupervisor, "_ensure")
    def test_transient_job_drops_privileges_and_retains_working_directory(
        self,
        _ensure: Mock,
        popen: Mock,
    ) -> None:
        SystemdSupervisor().start_transient(
            "gpu-priority-job-test.service",
            ("/opt/venv/bin/python", "train.py"),
            10,
            owner="alice",
            working_directory=Path("/srv/experiment"),
        )
        argv = popen.call_args.args[0]
        self.assertIn("--property=User=alice", argv)
        self.assertIn("--property=WorkingDirectory=/srv/experiment", argv)
        self.assertEqual(argv[-2:], ["/opt/venv/bin/python", "train.py"])


if __name__ == "__main__":
    unittest.main()

