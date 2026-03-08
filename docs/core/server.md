# Server

This section explains how to run and operate gRPC server in Django using `django-grpc-extra`.

## Entry Points

You can run server in two ways:

1. management command (`run_grpcserver`)
2. Python API (`GrpcExtra.run_server(...)`)

## Option A: Management Command

Basic run:

```bash
python manage.py run_grpcserver
```

Typical local run:

```bash
python manage.py run_grpcserver --bind 0.0.0.0:50051 --health --reflection
```

### Important flags

- `--bind`: server bind address (default from settings)
- `--max-workers`: gRPC thread pool size
- `--max-msg-mb`: send/receive message size limit
- `--health` / `--no-health`: enable or disable health service
- `--reflection` / `--no-reflection`: enable or disable server reflection
- `--reload` / `--no-reload`: live reload mode
- `--reload-path <path>` (repeatable): watched paths in reload mode
- `--auth-backend`: import path for auth backend
- `--interceptor` (repeatable): importable runtime interceptor
- `--request-logging` / `--no-request-logging`
- `--logger-name`: logger used by request logging interceptor
- `--discover` / `--no-discover`: service autodiscovery toggle

## Option B: Python API

```python
import os
import django
from grpc_extra import GrpcExtra


def main() -> None:
    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "example_project.settings")
    django.setup()

    grpc_extra = GrpcExtra(pattern="{app}.grpc.services")
    grpc_extra.run_server(
        bind="0.0.0.0:50051",
        enable_health=True,
        enable_reflection=True,
    )


if __name__ == "__main__":
    main()
```

## Service Discovery

By default, server autodiscovers modules by pattern:

```python
"{app}.grpc.services"
```

Meaning each Django app should expose decorated services in `grpc/services.py`.

You can override pattern in `GrpcExtra(pattern=...)`.

## Runtime Components

When server starts:

1. autodiscovers decorated services
2. imports generated `*_pb2.py` and `*_pb2_grpc.py`
3. adapts methods through runtime adapter
4. registers servicers in gRPC server
5. optionally adds health/reflection
6. starts listening on bind address

## Health and Reflection

### Health

Enable for service health checks:

```bash
python manage.py run_grpcserver --health
```

### Reflection

Enable for tools like Postman/grpcurl schema introspection:

```bash
python manage.py run_grpcserver --reflection
```

If reflection is enabled, remember to recreate connection in some clients after schema changes.

## Interceptors

Runtime supports:

- auth interceptor (when auth backend configured)
- request logging interceptor (when enabled)
- custom interceptors from settings/CLI

### Custom interceptor

```python
GRPC_EXTRA = {
    "INTERCEPTORS": [
        "path.to.CustomServerInterceptor",
    ]
}
```

For reload mode, prefer importable interceptors via settings (not runtime object instances).

## Live Reload

Enable reload in dev:

```bash
python manage.py run_grpcserver --reload --reload-path app
```

Or in settings:

```python
GRPC_EXTRA = {
    "ENABLE_RELOAD": True,
    "RELOAD_PATHS": ("app",),
}
```

### Notes

- reload mode uses `watchfiles`
- if package is missing, install `django-grpc-extra[reload]`
- on worker restart `KeyboardInterrupt` may appear internally and is handled by runtime

## Auth Integration

Configure backend (callable/class/import path):

```python
GRPC_EXTRA = {
    "AUTH_BACKEND": "path.to.auth.GrpcBearerAuth",
}
```

See [Authentication](authentication.md) for full contract.

## Message Size Limits

Set max message size (MB):

```python
GRPC_EXTRA = {
    "MAX_MSG_MB": 64,
}
```

This is applied to both send and receive options.

## Logging

Request logs are controlled by:

```python
GRPC_EXTRA = {
    "ENABLE_REQUEST_LOGGING": True,
    "LOGGER_NAME": "grpc_extra",
}
```

## Production Notes

- Keep reflection disabled in production unless needed.
- Prefer explicit auth and permissions for all non-public RPCs.
- Set conservative message limits.
- Use dedicated process management (systemd/docker/k8s) and health checks.
- Keep proto generation and app deployment in sync.

## Common Server Errors

### `pb2_grpc module not found`

Cause: proto files were not generated.

Fix:

```bash
python manage.py generate_proto --all
```

### `ModuleNotFoundError` for app grpc module

Cause: discovery pattern mismatch or missing `grpc/services.py` module.

### Reflection doesn't show service

Cause: stale client connection cache.

Fix: recreate connection after server/proto restart.
