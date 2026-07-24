# AGENTS.md — gpu-priorityd

`gpu-priorityd` is a small, fail-safe GPU priority controller for one Linux
host. The production backend targets systemd, cgroups v2 and NVIDIA.

## Safety invariants

1. Never kill an unregistered or unclassified CUDA process.
2. Protected units are never preempted.
3. Register a transient job before it can reach CUDA.
4. Abort admission if process ownership cannot be established.
5. Keep simulation and unit tests independent from systemd and physical GPUs.
6. Do not add application-specific authentication or session logic to the core.

Run before committing:

```bash
PYTHONPATH=src python3 -m unittest discover -s tests -v
PYTHONPATH=src python3 -m gpu_priorityd simulate
```

