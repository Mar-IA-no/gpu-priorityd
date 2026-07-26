# Changelog

## Unreleased

- Document operating notes from the first live deployment: exit `75` is a
  scheduling event and does not requeue; absolute paths are mandatory in
  transient units; long-lived GPU servers need an idle TTL or a documented
  exception instead of being smuggled through `run`; verify effective config
  against `/proc/<pid>/environ` rather than the config file; a
  socket-activated protected service can look idle to the arbiter; and shared
  venvs/weights mean the isolation is of the GPU and cgroup, not the
  filesystem.

## 0.1.0 - 2026-07-24

- Initial public MVP.
- Fail-safe classification of protected, registered and unknown CUDA work.
- Preemptible transient jobs with a dedicated exit code.
- Priority-service admission and guarded yielding.
- Portable simulator, tests and systemd integration templates.

