from __future__ import annotations

import os
import re
import tomllib
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .errors import ConfigurationError


DEFAULT_CONFIG_PATH = Path("/etc/gpu-priorityd.toml")
UNIT_PATTERN = re.compile(r"^[A-Za-z0-9_.:@-]+\.service$")


@dataclass(frozen=True)
class GPUConfig:
    index: int = 0
    required_free_mib: int = 0


@dataclass(frozen=True)
class ServiceConfig:
    unit: str
    protected_units: tuple[str, ...]
    safe_to_stop_command: tuple[str, ...] = ()


@dataclass(frozen=True)
class PreemptionConfig:
    grace_seconds: int = 5
    release_timeout_seconds: int = 20
    exit_code: int = 75


@dataclass(frozen=True)
class PathConfig:
    state_root: Path = Path("/var/lib/gpu-priorityd")
    run_root: Path = Path("/run/gpu-priorityd")
    lock_path: Path = Path("/run/lock/gpu-priorityd.lock")


@dataclass(frozen=True)
class Config:
    gpu: GPUConfig
    service: ServiceConfig
    preemption: PreemptionConfig
    paths: PathConfig


def _table(document: dict[str, Any], name: str) -> dict[str, Any]:
    value = document.get(name, {})
    if not isinstance(value, dict):
        raise ConfigurationError(f"[{name}] must be a TOML table")
    return value


def _strings(value: Any, field: str) -> tuple[str, ...]:
    if value is None:
        return ()
    if not isinstance(value, list) or not all(isinstance(item, str) and item for item in value):
        raise ConfigurationError(f"{field} must be an array of non-empty strings")
    return tuple(value)


def _integer(value: Any, field: str) -> int:
    if isinstance(value, bool):
        raise ConfigurationError(f"{field} must be an integer")
    try:
        return int(value)
    except (TypeError, ValueError) as exc:
        raise ConfigurationError(f"{field} must be an integer") from exc


def _service_unit(value: Any, field: str) -> str:
    if not isinstance(value, str) or not UNIT_PATTERN.fullmatch(value) or value.startswith("-"):
        raise ConfigurationError(f"{field} must name a valid .service unit")
    return value


def load_config(path: Path | None = None) -> Config:
    selected = path or Path(os.environ.get("GPU_PRIORITY_CONFIG", DEFAULT_CONFIG_PATH))
    try:
        with selected.open("rb") as handle:
            document = tomllib.load(handle)
    except FileNotFoundError as exc:
        raise ConfigurationError(f"configuration not found: {selected}") from exc
    except tomllib.TOMLDecodeError as exc:
        raise ConfigurationError(f"invalid TOML in {selected}: {exc}") from exc
    if document.get("version", 1) != 1:
        raise ConfigurationError("only configuration version 1 is supported")

    gpu = _table(document, "gpu")
    service = _table(document, "service")
    preemption = _table(document, "preemption")
    paths = _table(document, "paths")

    unit = _service_unit(service.get("unit"), "service.unit")
    protected = {
        _service_unit(item, "service.protected_units")
        for item in _strings(service.get("protected_units", []), "service.protected_units")
    }
    protected.add(unit)

    config = Config(
        gpu=GPUConfig(
            index=_integer(gpu.get("index", 0), "gpu.index"),
            required_free_mib=_integer(
                gpu.get("required_free_mib", 0),
                "gpu.required_free_mib",
            ),
        ),
        service=ServiceConfig(
            unit=unit,
            protected_units=tuple(sorted(protected)),
            safe_to_stop_command=_strings(
                service.get("safe_to_stop_command", []),
                "service.safe_to_stop_command",
            ),
        ),
        preemption=PreemptionConfig(
            grace_seconds=_integer(
                preemption.get("grace_seconds", 5),
                "preemption.grace_seconds",
            ),
            release_timeout_seconds=_integer(
                preemption.get("release_timeout_seconds", 20),
                "preemption.release_timeout_seconds",
            ),
            exit_code=_integer(
                preemption.get("exit_code", 75),
                "preemption.exit_code",
            ),
        ),
        paths=PathConfig(
            state_root=Path(paths.get("state_root", "/var/lib/gpu-priorityd")),
            run_root=Path(paths.get("run_root", "/run/gpu-priorityd")),
            lock_path=Path(paths.get("lock_path", "/run/lock/gpu-priorityd.lock")),
        ),
    )
    validate_config(config)
    return config


def validate_config(config: Config) -> None:
    if config.gpu.index < 0:
        raise ConfigurationError("gpu.index cannot be negative")
    if config.gpu.required_free_mib < 0:
        raise ConfigurationError("gpu.required_free_mib cannot be negative")
    if config.preemption.grace_seconds < 1:
        raise ConfigurationError("preemption.grace_seconds must be positive")
    if config.preemption.release_timeout_seconds < config.preemption.grace_seconds:
        raise ConfigurationError("release_timeout_seconds must be at least grace_seconds")
    if not 1 <= config.preemption.exit_code <= 255:
        raise ConfigurationError("preemption.exit_code must be between 1 and 255")
    for path in (config.paths.state_root, config.paths.run_root, config.paths.lock_path):
        if not path.is_absolute():
            raise ConfigurationError(f"runtime path must be absolute: {path}")
