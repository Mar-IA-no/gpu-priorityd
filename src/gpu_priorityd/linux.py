from __future__ import annotations

import csv
import os
import platform
import pwd
import shutil
import subprocess
from pathlib import Path
from typing import Sequence

from .command import run_command
from .errors import PlatformUnavailable
from .models import GPUProcess, GPUSummary


def cgroup_unit(pid: int) -> str | None:
    try:
        lines = Path(f"/proc/{pid}/cgroup").read_text(encoding="ascii").splitlines()
    except OSError:
        return None
    for line in lines:
        if line.startswith("0::"):
            value = line.split("::", 1)[1].rstrip("/")
            return value.rsplit("/", 1)[-1] if value else None
    return None


class NvidiaInspector:
    def __init__(self, index: int):
        self.index = index

    @staticmethod
    def check_platform() -> list[str]:
        problems: list[str] = []
        if platform.system() != "Linux":
            problems.append("production inspection requires Linux")
        if shutil.which("nvidia-smi") is None:
            problems.append("nvidia-smi was not found")
        if not Path("/sys/fs/cgroup/cgroup.controllers").is_file():
            problems.append("cgroups v2 is not mounted")
        return problems

    def _ensure(self) -> None:
        problems = self.check_platform()
        if problems:
            raise PlatformUnavailable("; ".join(problems))

    def processes(self) -> list[GPUProcess]:
        self._ensure()
        result = run_command(
            [
                "nvidia-smi",
                "-i",
                str(self.index),
                "--query-compute-apps=pid,process_name,used_memory",
                "--format=csv,noheader,nounits",
            ],
            timeout=10,
            check=True,
        )
        processes: list[GPUProcess] = []
        for values in csv.reader(result.stdout.splitlines(), skipinitialspace=True):
            values = [item.strip() for item in values]
            if len(values) != 3:
                raise PlatformUnavailable("nvidia-smi returned an invalid process row")
            try:
                pid = int(values[0])
            except ValueError as exc:
                raise PlatformUnavailable("nvidia-smi returned an invalid process PID") from exc
            try:
                used_mib = int(values[2])
            except ValueError:
                # Some driver/MIG combinations report N/A. Ownership still
                # matters, so retain the process instead of hiding it.
                used_mib = 0
            processes.append(
                GPUProcess(
                    pid=pid,
                    process_name=values[1],
                    used_mib=used_mib,
                    unit=cgroup_unit(pid),
                )
            )
        return processes

    def summary(self) -> GPUSummary:
        self._ensure()
        result = run_command(
            [
                "nvidia-smi",
                "-i",
                str(self.index),
                "--query-gpu=memory.used,memory.free,memory.total,utilization.gpu,temperature.gpu",
                "--format=csv,noheader,nounits",
            ],
            timeout=10,
            check=True,
        )
        try:
            used, free, total, utilization, temperature = [
                int(item.strip()) for item in result.stdout.splitlines()[0].split(",")
            ]
        except (IndexError, ValueError) as exc:
            raise PlatformUnavailable("nvidia-smi returned an invalid GPU summary") from exc
        return GPUSummary(
            index=self.index,
            used_mib=used,
            free_mib=free,
            total_mib=total,
            utilization_percent=utilization,
            temperature_c=temperature,
        )


class SystemdSupervisor:
    @staticmethod
    def check_platform() -> list[str]:
        problems: list[str] = []
        if platform.system() != "Linux":
            problems.append("production supervision requires Linux")
        for binary in ("systemctl", "systemd-run"):
            if shutil.which(binary) is None:
                problems.append(f"{binary} was not found")
        if not Path("/run/systemd/system").is_dir():
            problems.append("systemd is not the active service manager")
        return problems

    def _ensure(self) -> None:
        problems = self.check_platform()
        if problems:
            raise PlatformUnavailable("; ".join(problems))

    def state(self, unit: str) -> str:
        self._ensure()
        result = run_command(["systemctl", "is-active", unit], timeout=5)
        return result.stdout.strip() or "inactive"

    def stop(self, unit: str, timeout: float) -> None:
        self._ensure()
        run_command(["systemctl", "stop", unit], timeout=timeout, check=True)

    def start_transient(
        self,
        unit: str,
        command: Sequence[str],
        grace_seconds: int,
        *,
        owner: str,
        working_directory: Path,
    ) -> subprocess.Popen[bytes]:
        self._ensure()
        return subprocess.Popen(
            [
                "systemd-run",
                "--quiet",
                "--collect",
                "--wait",
                "--pipe",
                f"--unit={unit}",
                "--service-type=exec",
                "--property=KillMode=control-group",
                f"--property=User={owner}",
                f"--property=WorkingDirectory={working_directory}",
                f"--property=TimeoutStopSec={grace_seconds}s",
                "--",
                *command,
            ]
        )

    def reset_failed(self, unit: str) -> None:
        run_command(["systemctl", "reset-failed", unit], timeout=5)


def current_owner() -> str:
    candidate = os.environ.get("SUDO_USER") if os.geteuid() == 0 else None
    if candidate:
        try:
            return pwd.getpwnam(candidate).pw_name
        except KeyError:
            pass
    return pwd.getpwuid(os.getuid()).pw_name
