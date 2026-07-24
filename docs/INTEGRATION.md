# Integration Guide

## 1. Choose the priority unit

Use one existing systemd service as the priority owner. Add that unit to
`service.unit`. It is automatically included in the protected set.

List every other CUDA service that must never be stopped in
`service.protected_units`. Keep this list narrow and review it before enabling
automatic admission.

## 2. Define safe yielding

The optional `safe_to_stop_command` is an application-owned predicate. Exit
zero means the priority service can be stopped without losing an active
session; any other result rejects the yield.

The controller does not infer application idleness from sockets or GPU usage.
That would confuse transport activity with durable application state.

## 3. Wire admission

For a socket-activated server, put admission in `ExecStartPre` and start the
server from systemd's inherited file descriptor. The templates in `deploy/`
show the shape; replace paths and commands with real values.

The first connection waits while registered jobs stop and the priority service
starts. If a web page calls passive API endpoints on load, route those
endpoints separately or they will activate the service. Do not duplicate
application authentication inside this controller.

For a service activated by another mechanism, invoke `gpu-priority admit`
before `systemctl start`. The same classification rules apply.

## 4. Launch expendable work

Every workload that may be interrupted must use the wrapper:

```bash
sudo gpu-priority --config /etc/gpu-priorityd.toml run \
  --name experiment-42 -- python train.py --config experiment.toml
```

Do not append `&` inside the command to detach the real workload from the
transient unit. The cgroup must retain every descendant.

Exit code `75` means the priority service preempted the job. Other nonzero
codes belong to the command or systemd. Save checkpoints periodically; the
grace window is intended for ordinary termination, not guaranteed multi-GB
checkpoint writes.

## 5. Acceptance sequence

Run this sequence with a disposable test workload:

1. `gpu-priority doctor` reports `production_backend: ready`.
2. `gpu-priority status` classifies all current CUDA processes as protected,
   registered or none. Any unknown process must be understood first.
3. Start a wrapper job that allocates a small amount of VRAM.
4. Admit the priority service and verify the job exits `75`.
5. Confirm the protected units remained active.
6. Complete one real application interaction, including WebSocket traffic if
   applicable.
7. Run `yield` only after the safety predicate reports idle and verify VRAM is
   released with the process.
8. Launch CUDA manually and verify admission aborts without killing it.

## 6. Rollback

Disable socket activation or remove the `ExecStartPre` line, restore the prior
service unit, and stop using the batch wrapper. The controller does not modify
drivers, CUDA, model files or application data.

