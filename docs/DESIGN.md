# Design

## Problem

A workstation GPU is valuable for both long-running experiments and a
latency-sensitive service. Conventional time sharing does not guarantee that
the service can reclaim enough VRAM when a request arrives. Blindly killing
GPU PIDs is unsafe because PID ownership is ambiguous and unrelated services
may also use CUDA.

`gpu-priorityd` makes preemption an explicit contract. A batch owner opts in by
starting work through the wrapper. The controller records the transient
systemd unit before that unit can allocate GPU memory. Admission can therefore
stop the whole registered cgroup, not an arbitrary PID.

## Components

### Registry

The registry stores one private runtime record per preemptible unit. Records
contain only the unit, display name, owner and creation time; commands are not
stored. A marker records that a unit was stopped for priority
admission, allowing the wrapper to return the dedicated preemption exit code.

### NVIDIA inspector

`nvidia-smi` supplies memory totals and compute PIDs. `/proc/<pid>/cgroup` maps
each PID to its cgroup v2 leaf, which is expected to be a systemd service unit.
Failure to obtain a recognized unit makes the process unknown.

### Systemd supervisor

Batch commands run as transient services with `KillMode=control-group`.
Stopping the unit terminates descendants as a group and gives them the
configured `TimeoutStopSec` grace period.

### Controller

The controller serializes state transitions with a filesystem lock and
classifies each visible CUDA process:

| Class | Meaning | Admission behavior |
|---|---|---|
| Protected | Priority unit or explicit protected unit | Preserve |
| Registered | Unit has a live controller record | Stop unit |
| Unknown | Anything else, including missing cgroup identity | Abort |

Admission checks for unknown processes before stopping registered work. It
also stops active registered units that are not yet visible in `nvidia-smi`,
which closes a race between job registration and CUDA initialization.

## State and permissions

- `/run/gpu-priorityd/jobs`: ephemeral job records and preemption markers
- `/run/lock/gpu-priorityd.lock`: serialization lock
- `/var/lib/gpu-priorityd/events.jsonl`: local operational events

The controller is intended to run as root because it controls system units.
Transient jobs drop back to the invoking user and retain that user's current
working directory; they do not execute as root merely because the wrapper used
`sudo`.
The configuration and executable must not be writable by untrusted users.
Event records can expose process names and local owners; do not publish the raw
event file as a status endpoint.

## Failure behavior

- Unknown CUDA ownership: admission fails before preemption.
- Registered jobs do not stop before timeout: admission fails.
- Required free memory is not reached: admission fails.
- Safety predicate rejects service yield: service remains active.
- Wrapper is interrupted abnormally: a stale record can remain, but an
  inactive stale unit is not killed and does not authorize another unit.

## Deliberate non-goals

The MVP does not validate application authentication, proxy HTTP or WebSocket
traffic, decide when a session is idle, restart batch jobs, or choose
checkpoint cadence. Those responsibilities stay with the application and its
deployment layer.
