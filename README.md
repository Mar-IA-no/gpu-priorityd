# gpu-priorityd

`gpu-priorityd` lets one interactive service borrow a single NVIDIA GPU from
batch jobs on a Linux workstation. Batch jobs opt into preemption through a
wrapper. When the priority service is admitted, registered jobs are stopped;
unknown CUDA processes make admission fail instead of being killed.

This is an early, deliberately narrow MVP for workstations where interactive
inference must remain available while the same GPU is used for experiments.
It is not a cluster scheduler.

```text
                    one Linux host / one NVIDIA GPU

  gpu-priority run -- train.py          priority application request
              |                                      |
              v                                      v
  registered transient systemd unit        socket-activated service
              |                             ExecStartPre: admit
              +-------------------+------------------+
                                  |
                          gpu-priorityd policy
                       /          |          \
                 protected    registered    unknown
                  never kill    preempt      abort
```

## What the MVP does

- Registers batch commands as transient `systemd` services before they can
  reach CUDA.
- Maps NVIDIA compute PIDs back to cgroups and systemd units.
- Protects an explicit allowlist of critical services.
- Stops only jobs registered through `gpu-priority run`.
- Refuses admission when any CUDA process cannot be classified.
- Returns exit code `75` when a batch job was preempted, so an outer workflow
  can distinguish preemption from failure.
- Can stop the priority service through an application-specific safety check,
  releasing residual model tensors with the process.
- Includes a hardware-independent simulator for development on macOS or CI.

## Requirements

The production backend requires:

- Linux with `systemd` and cgroups v2
- one NVIDIA GPU visible through `nvidia-smi`
- Python 3.11 or newer
- root privileges for service control and transient units

The simulator and tests run without Linux, systemd, NVIDIA hardware or root.

## Quick start: simulation

```bash
python3 -m venv .venv
. .venv/bin/activate
python -m pip install -e .
gpu-priority simulate
gpu-priority doctor
python -m unittest discover -s tests -v
```

On macOS, `doctor` reports that the production backend is unavailable. That is
expected; `simulate` is the portable acceptance test.

## Linux setup

1. Install the package in a dedicated virtual environment.
2. Copy [`examples/gpu-priorityd.toml`](examples/gpu-priorityd.toml) to
   `/etc/gpu-priorityd.toml` and adapt the unit names and memory threshold.
3. Protect the configuration from non-root writes.
4. Integrate `gpu-priority admit` into the priority service's `ExecStartPre`.
5. Launch every expendable GPU command through `gpu-priority run`.

```bash
sudo install -m 0644 examples/gpu-priorityd.toml /etc/gpu-priorityd.toml
sudo gpu-priority --config /etc/gpu-priorityd.toml doctor

sudo gpu-priority --config /etc/gpu-priorityd.toml run \
  --name nightly-train -- python train.py
```

See [`docs/INTEGRATION.md`](docs/INTEGRATION.md) and the templates under
[`deploy/`](deploy/) before enabling automatic admission.

## Commands

```text
gpu-priority status
gpu-priority admit
gpu-priority run --name NAME -- COMMAND [ARGS...]
gpu-priority yield [--force]
gpu-priority doctor
gpu-priority simulate
```

`yield` runs `service.safe_to_stop_command` first. If no safety predicate is
configured, it refuses to stop the service unless `--force` is explicit.

## Safety contract

The controller is fail-safe about ownership, not optimistic:

1. The priority service and configured protected units are never preempted.
2. Only jobs registered by this controller are eligible for preemption.
3. An unknown CUDA PID blocks admission before any job is stopped.
4. A registered unit is stopped even if it has not reached CUDA yet, closing
   the registration-to-allocation race.
5. The lock serializes job registration, admission and service yielding.

Configuration mistakes can still interrupt work. Test with `simulate`, inspect
`status`, and use a disposable workload before connecting a real service.

## Scope and limitations

- One host and one GPU index per controller instance.
- Batch jobs must use the wrapper. A manually launched CUDA process is unknown
  and blocks admission by design.
- Preemption means process termination, not checkpoint migration. Jobs need
  periodic checkpoints if progress matters.
- Socket activation requires a socket-aware server. Public passive endpoints
  may need separate routing so health checks do not wake the GPU service.
- No Kubernetes, Slurm, MIG, MPS, multi-GPU placement or remote queueing.

The design and trust boundaries are documented in
[`docs/DESIGN.md`](docs/DESIGN.md).

## License

MIT

