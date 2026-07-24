# Security Policy

## Supported version

The current `0.1.x` line is an alpha MVP. It has not received an independent
security audit.

## Trust model

`gpu-priorityd` controls system services and is expected to run with root
privileges. Treat the executable, TOML configuration, runtime registry and
systemd units as privileged administration surfaces. Do not make them writable
by users who should not be able to stop GPU workloads.

The controller never treats process names or PIDs alone as authorization. A
CUDA process is preemptible only when its systemd unit has a controller-created
runtime record. Any unclassified process blocks admission.

Commands are not retained in the registry or event log. Operational events can
still contain local usernames, unit names, process names and PIDs; do not expose
the raw log publicly.

## Reporting

Please report vulnerabilities through a private GitHub security advisory for
this repository rather than a public issue.

