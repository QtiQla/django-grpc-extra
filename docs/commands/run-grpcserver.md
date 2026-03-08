# Command: `run_grpcserver`

Starts gRPC server for discovered services.

Basic usage:

```bash
python manage.py run_grpcserver --bind [::]:50051 --health --reflection
```

---

## What Command Does

1. auto-discovers registered services
2. builds runtime adapters for methods/schemas
3. starts gRPC server with configured workers and interceptors
4. optionally enables health/reflection and reload watcher

---

## Options

- `--bind <host:port>`: bind address (default from command settings)
- `--max-workers <int>`: thread pool workers
- `--max-msg-mb <int>`: max request/response message size in MB
- `--health` / `--no-health`: enable/disable gRPC health service
- `--reflection` / `--no-reflection`: enable/disable server reflection
- `--reload` / `--no-reload`: enable/disable live reload watcher
- `--reload-path <path>`: additional watched path; can be repeated
- `--auth-backend <import.path>`: auth backend class/function path
- `--interceptor <import.path>`: extra interceptor; can be repeated
- `--request-logging` / `--no-request-logging`: request logging interceptor toggle
- `--logger-name <name>`: logger name used by request logging interceptor
- `--discover <pattern>`: autodiscovery pattern, default `{app}.grpc.services`

Examples:

```bash
# development
python manage.py run_grpcserver --bind 0.0.0.0:50051 --health --reflection --reload

# production-like run
python manage.py run_grpcserver \
  --bind 0.0.0.0:50051 \
  --max-workers 16 \
  --max-msg-mb 16 \
  --health \
  --reflection

# custom auth backend
python manage.py run_grpcserver --auth-backend project.grpc.auth.GrpcBearerAuth
```

---

## Autodiscovery

By default command tries importing modules by pattern:

`{app}.grpc.services`

If your services live elsewhere, set custom pattern:

```bash
python manage.py run_grpcserver --discover {app}.api.grpc_services
```

---

## Reload Mode Notes

With `--reload`, process manager respawns worker process on file change. During restart you may see `KeyboardInterrupt` traces in old worker process; this is expected shutdown behavior if server is being interrupted/restarted.

Tune watched paths with settings and flags:

```python
GRPC_EXTRA = {
    "reload_paths": ["app"],
}
```

And/or:

```bash
python manage.py run_grpcserver --reload --reload-path app --reload-path shared
```

---

## Health and Reflection

- `--health` registers standard gRPC health check service
- `--reflection` exposes service descriptors for API tools

If a service is not visible in client tools:

1. ensure `--reflection` is enabled
2. recreate connection in the client tool (some tools cache descriptors)
3. verify service was discovered in startup logs

---

## Authentication Integration

`--auth-backend` expects import path to backend implementation matching framework auth contract.

Common startup failure:

`ModuleNotFoundError: No module named 'path'`

Reason: wrong import string in settings/flag (placeholder or typo). Use full Python import path to the backend symbol.

---

## Common Errors

## Port already in use

`Address already in use`

Fix: stop previous process or bind another port.

## Unauthorized for all methods

Check metadata key casing for gRPC transport (`authorization` is lowercase in metadata tools), auth scheme format, and backend parsing logic.

## Reflection enabled but service missing

Usually stale client-side descriptor cache. Reconnect/recreate request entry in tool.

---

## Production Recommendations

1. Run behind TLS-terminating edge or enable TLS in deployment topology.
2. Keep reflection disabled in production unless explicitly needed.
3. Keep health enabled for orchestrator probes.
4. Configure worker count according to CPU and DB throughput profile.
5. Keep request logging structured and avoid logging sensitive payloads.
