# Command: `generate_proto`

Generates `.proto` files from registered gRPC services and (optionally) compiles Python stubs (`*_pb2.py`, `*_pb2_grpc.py`, and optionally `*.pyi`).

Basic usage:

```bash
python manage.py generate_proto --app <app_label>
```

---

## What Command Does

1. auto-discovers services (`{app}.grpc.services` by default)
2. builds proto definitions from method schemas
3. writes/updates app proto files
4. optionally compiles proto to Python stubs

---

## Options

- `--app <label>`: process only selected app; can be repeated
- `--all`: process all installed apps
- `--force`: rewrite proto files even if content changed detection would skip
- `--no-compile`: only write `.proto`, skip `pb2` generation
- `--pyi`: generate `*.pyi` type stubs during compile

Recommended patterns:

```bash
# one app
python manage.py generate_proto --app products

# all apps
python manage.py generate_proto --all

# regenerate and compile with type stubs
python manage.py generate_proto --app products --force --pyi

# proto only (for CI diff checks, for example)
python manage.py generate_proto --app products --no-compile
```

---

## Typical Workflow

When service/schema code changed:

1. run `generate_proto`
2. commit updated `.proto` and generated stubs
3. restart gRPC server
4. refresh client descriptors in tooling (Postman/BloomRPC/etc.)

---

## Multi-app Root Limitation

If apps are discovered under different include roots, command can raise:

`Apps have different include roots; use --app for a single app root.`

In that case, run command per app:

```bash
python manage.py generate_proto --app app_one
python manage.py generate_proto --app app_two
```

---

## Common Errors

## `google/protobuf/empty.proto: File not found`

Reason: protoc include path for bundled Google protos not resolved in environment.

What to check:

1. `grpcio-tools` is installed in active venv
2. command is run from the same Python environment
3. library version includes fixed protoc include resolution

## `AttributeError: type object 'list' has no attribute 'model_fields'`

Reason: old generation path expected model class while method used top-level `list[T]` response schema.

Expected behavior in current implementation: list response schemas are supported and wrapped into repeated message payload.

## Proto name conflicts

Example: duplicate message names for combined decorators/endpoints.

Fix:

1. ensure latest library version with message name dedup logic
2. avoid manually forcing identical explicit message names across incompatible schemas

---

## Best Practices

1. Use `--app` in local development for faster iteration.
2. Use `--all` in CI/release checks.
3. Keep generated files committed, so server and clients stay in sync.
4. Use `--pyi` if team relies on IDE/static typing for generated stubs.
5. Regenerate after changing decorators that alter request/response envelopes (`pagination`, `searching`, `ordering`).
