# Command: `init_grpc`

Initializes base gRPC scaffold inside Django app(s).

Basic usage:

```bash
python manage.py init_grpc --app products
```

If no flags are provided, command behaves as `--all`.

---

## What Command Creates

For each target app it creates:

- `<app>/grpc/__init__.py`
- `<app>/grpc/services.py`
- `<app>/grpc/proto/__init__.py`

These files are the minimal structure required to start defining services and generating proto.

---

## Options

- `--app <label>`: target app label; can be repeated
- `--all`: scaffold every installed app
- `--force`: overwrite existing scaffold files

Examples:

```bash
# single app
python manage.py init_grpc --app products

# multiple explicit apps
python manage.py init_grpc --app products --app billing

# all installed apps
python manage.py init_grpc --all

# rewrite existing files
python manage.py init_grpc --app products --force
```

---

## Output Behavior

Command prints one line per file:

- `write <path>` when file is created/overwritten
- `skip <path>` when file exists and `--force` is not set

Final summary:

- `gRPC scaffold complete. created=<N> skipped=<M>`

---

## Validation Rules

- `--all` and `--app` cannot be used together.
- Unknown app labels produce `CommandError`.
- If no matching apps found, command fails.

Typical errors:

- `Use either --all or --app, not both.`
- `Unknown app label(s): ...`
- `No matching apps found.`

---

## Recommended Workflow

1. Run `init_grpc` for your app.
2. Implement services in `<app>/grpc/services.py`.
3. Run `generate_proto`.
4. Start server with `run_grpcserver`.

Example:

```bash
python manage.py init_grpc --app products
python manage.py generate_proto --app products --force
python manage.py run_grpcserver --bind 0.0.0.0:50051 --health --reflection
```

---

## Notes on `--force`

`--force` overwrites scaffold files, so use it carefully if those files were already customized.

Safe approach:

1. commit changes before rerunning with `--force`
2. rerun command
3. restore/merge your custom code if needed
