from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from gpu_priorityd.config import load_config
from gpu_priorityd.errors import ConfigurationError


VALID = """
version = 1
[gpu]
index = 0
required_free_mib = 20480
[service]
unit = "interactive.service"
protected_units = ["safety.service"]
safe_to_stop_command = ["/bin/true"]
[preemption]
grace_seconds = 5
release_timeout_seconds = 20
exit_code = 75
[paths]
state_root = "/tmp/state"
run_root = "/tmp/run"
lock_path = "/tmp/controller.lock"
"""


class ConfigTests(unittest.TestCase):
    def write(self, contents: str) -> Path:
        directory = tempfile.mkdtemp(prefix="gpu-priorityd-config-")
        path = Path(directory) / "config.toml"
        path.write_text(contents, encoding="utf-8")
        self.addCleanup(lambda: __import__("shutil").rmtree(directory))
        return path

    def test_loads_and_auto_protects_priority_unit(self) -> None:
        config = load_config(self.write(VALID))
        self.assertEqual(config.gpu.required_free_mib, 20480)
        self.assertEqual(
            set(config.service.protected_units),
            {"interactive.service", "safety.service"},
        )

    def test_rejects_relative_runtime_path(self) -> None:
        path = self.write(VALID.replace('/tmp/state', 'relative/state'))
        with self.assertRaisesRegex(ConfigurationError, "runtime path"):
            load_config(path)

    def test_rejects_non_integer_without_traceback_leak(self) -> None:
        path = self.write(VALID.replace("required_free_mib = 20480", 'required_free_mib = "many"'))
        with self.assertRaisesRegex(ConfigurationError, "gpu.required_free_mib"):
            load_config(path)

    def test_rejects_boolean_as_integer(self) -> None:
        path = self.write(VALID.replace("index = 0", "index = true"))
        with self.assertRaisesRegex(ConfigurationError, "gpu.index"):
            load_config(path)

    def test_rejects_unsupported_version(self) -> None:
        with self.assertRaisesRegex(ConfigurationError, "version 1"):
            load_config(self.write(VALID.replace("version = 1", "version = 2")))

    def test_rejects_option_shaped_service_unit(self) -> None:
        path = self.write(VALID.replace('unit = "interactive.service"', 'unit = "--now.service"'))
        with self.assertRaisesRegex(ConfigurationError, "valid .service"):
            load_config(path)


if __name__ == "__main__":
    unittest.main()
