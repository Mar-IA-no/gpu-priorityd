from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any


@dataclass(frozen=True)
class GPUProcess:
    pid: int
    process_name: str
    used_mib: int
    unit: str | None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class GPUSummary:
    index: int
    used_mib: int
    free_mib: int
    total_mib: int
    utilization_percent: int
    temperature_c: int

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class JobRecord:
    unit: str
    name: str
    owner: str
    created_at: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "unit": self.unit,
            "name": self.name,
            "owner": self.owner,
            "created_at": self.created_at,
        }


@dataclass(frozen=True)
class ProcessClasses:
    protected: tuple[GPUProcess, ...]
    registered: tuple[GPUProcess, ...]
    unknown: tuple[GPUProcess, ...]

    def to_dict(self) -> dict[str, Any]:
        return {
            "protected": [item.to_dict() for item in self.protected],
            "registered": [item.to_dict() for item in self.registered],
            "unknown": [item.to_dict() for item in self.unknown],
        }
