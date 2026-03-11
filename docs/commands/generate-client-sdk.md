# Command: `generate_client_sdk`

Generate client SDK from discovered gRPC proto contracts.

> Status: **Experimental**
>
> SDK generator API and generated file layout may change between releases.

Basic usage:

```bash
python manage.py generate_client_sdk --language python --all
```

---

## What Command Does

1. discovers registered gRPC services
2. ensures proto files are generated (unless `--skip-proto`)
3. runs selected SDK generator
4. writes SDK package to output directory

---

## Options

- `--language` (required): target SDK language
- `--out`: output directory (default: `generated-sdks`)
- `--name`: SDK package/folder name
- `--app <label>`: include app (repeatable)
- `--all`: include all installed apps
- `--skip-proto`: skip proto regeneration and use existing proto files

Examples:

```bash
# python sdk for all apps
python manage.py generate_client_sdk --language python --all

# python sdk for one app
python manage.py generate_client_sdk --language python --app products --name products-grpc-sdk

# generate to custom location
python manage.py generate_client_sdk --language python --all --out ./artifacts

# use existing proto files only
python manage.py generate_client_sdk --language python --all --skip-proto
```

---

## Python SDK Layout (Current Experimental)

```text
<sdk>/src/<package>/
  <app>/grpc/proto/            # generated protobuf artifacts
    *_pb2.py
    *_pb2_grpc.py
    *.pyi
  client.py                  # custom layer (not overwritten if exists)
  client_generated.py        # regenerated
  helpers.py                 # helper module (created if missing, not overwritten)
  services.py                # facade, regenerated
  typed_services.py          # facade, regenerated
  models.py                  # facade, regenerated
  generated/
    <app>/
      services.py            # regenerated
      typed_services.py      # regenerated
      models.py              # regenerated
```

Regeneration behavior:

- regenerated every run: generated facades and `generated/<app>/...`
- preserved if exists: `client.py`, `helpers.py`

---

## Raw and Typed Layers

Python SDK exposes two access patterns:

- raw protobuf layer: `client.<service>.<method>()`
- typed pydantic layer: `client.typed.<service>.<method>()`

```python
from my_sdk import ClientConfig, GrpcClient, extract_results, message_to_dict

client = GrpcClient(ClientConfig(host="localhost:50051"))

raw_response = client.product.list({"limit": 20})
raw_payload = message_to_dict(raw_response)
rows = extract_results(raw_response)

typed_response = client.typed.product.list({"limit": 20})
```

---

## Custom Generators

You can register custom generators via settings:

```python
GRPC_EXTRA = {
    "SDK_GENERATORS": {
        "python": "grpc_extra.sdk.generators.PythonClientSDKGenerator",
        "php": "grpc_extra.sdk.generators.PhpClientSDKGenerator",
        "my_lang": "path.to.MyGenerator",
    }
}
```

Generator must inherit `BaseClientSDKGenerator`.

---

## Common Errors

## `Apps have different include roots`

Run command per app:

```bash
python manage.py generate_client_sdk --language python --app app_one
python manage.py generate_client_sdk --language python --app app_two
```

## `grpcio-tools is required`

Install extra dependencies:

```bash
pip install "django-grpc-extra[codegen,sdk]"
```

## Generated SDK mismatch with server

Regenerate proto and SDK from the same revision, then reinstall SDK artifact.

---

## Recommendation

Treat this command as an accelerator for internal SDK workflows.
For external/public SDK distribution, pin exact SDK versions and test generated artifacts in CI.
