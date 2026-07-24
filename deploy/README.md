# Deployment templates

These are examples, not drop-in universal units. Review unit names, executable
paths, the inherited socket behavior and timeouts for the target application.

The priority service is activated by `priority-app.socket`. Its `ExecStartPre`
runs fail-safe admission before application startup. The templates do not add
an HTTP proxy, authentication layer, idle detector or public status endpoint.

