from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from .config import load_config
from .controller import Controller
from .errors import GPUPriorityError
from .linux import NvidiaInspector, SystemdSupervisor
from .registry import Registry
from .simulator import run_simulation


def build_controller(config_path: Path | None) -> Controller:
    config = load_config(config_path)
    return Controller(
        config,
        SystemdSupervisor(),
        NvidiaInspector(config.gpu.index),
        Registry(config.paths.run_root, config.paths.lock_path),
    )


def parser() -> argparse.ArgumentParser:
    root = argparse.ArgumentParser(prog="gpu-priority", description="Single-host GPU priority controller")
    root.add_argument("--config", type=Path, help="TOML configuration path")
    sub = root.add_subparsers(dest="command", required=True)
    sub.add_parser("status", help="Show classified GPU state")
    sub.add_parser("admit", help="Preempt registered jobs and admit the priority service")
    run = sub.add_parser("run", help="Run a preemptible command in a registered systemd scope")
    run.add_argument("--name", required=True)
    run.add_argument("job_command", nargs=argparse.REMAINDER)
    yield_parser = sub.add_parser("yield", help="Stop the priority service and release its GPU context")
    yield_parser.add_argument("--force", action="store_true")
    sub.add_parser("doctor", help="Check production backend prerequisites")
    sub.add_parser("simulate", help="Run the portable policy simulation")
    return root


def doctor() -> int:
    problems = [*SystemdSupervisor.check_platform(), *NvidiaInspector.check_platform()]
    deduplicated = list(dict.fromkeys(problems))
    payload = {
        "production_backend": "ready" if not deduplicated else "unavailable",
        "problems": deduplicated,
        "simulation_backend": "ready",
    }
    print(json.dumps(payload, indent=2))
    return 0 if not deduplicated else 1


def main(argv: list[str] | None = None) -> int:
    args = parser().parse_args(argv)
    try:
        if args.command == "simulate":
            result = run_simulation()
            print(json.dumps(result, indent=2))
            return 0 if result["simulation"] == "ok" else 1
        if args.command == "doctor":
            return doctor()

        controller = build_controller(args.config)
        if args.command == "status":
            print(json.dumps(controller.status(), indent=2))
            return 0
        if args.command == "admit":
            print(json.dumps(controller.admit(), indent=2))
            return 0
        if args.command == "yield":
            print(json.dumps(controller.yield_service(force=args.force), indent=2))
            return 0
        if args.command == "run":
            command = args.job_command[1:] if args.job_command[:1] == ["--"] else args.job_command
            return controller.run_job(args.name, command)
    except GPUPriorityError as exc:
        print(f"gpu-priority: {exc}", file=sys.stderr)
        return 1
    return 1

