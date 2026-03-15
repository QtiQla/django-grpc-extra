# django-grpc-extra

[![PyPI version](https://img.shields.io/pypi/v/django-grpc-extra.svg)](https://pypi.org/project/django-grpc-extra/)
[![Docs](https://img.shields.io/badge/docs-online-2ea44f)](https://qtiqla.github.io/django-grpc-extra/)

`django-grpc-extra` provides a decorator-based workflow for building gRPC APIs in Django:
- declare services and RPC methods with decorators
- generate `.proto` files (and optionally `pb2/pb2_grpc`)
- run a gRPC server with auto-discovery, request conversion, and optional reload/logging

## Acknowledgements
This project is inspired by:
- [Django Ninja](https://django-ninja.rest-framework.com)
- [django-ninja-extra](https://eadwincode.github.io/django-ninja-extra/)

## Quick Start (5 minutes)

1. Install the package:
```bash
pip install "django-grpc-extra[codegen]"
```

2. Add `grpc_extra` to `INSTALLED_APPS`.

3. Scaffold gRPC folders for your app:
```bash
python -m django init_grpc --app example_app
```

4. Create `example_app/grpc/services.py`:
```python
from pydantic import BaseModel
from grpc_extra import grpc_method, grpc_pagination, grpc_service


class PingRequest(BaseModel):
    message: str


class PingResponse(BaseModel):
    message: str


@grpc_service(app_label="example_app", package="example_app")
class ExampleService:
    @grpc_method(request_schema=PingRequest, response_schema=PingResponse)
    def ping(self, request, context):
        return {"message": request.message}
```

5. Generate proto and pb2 files:
```bash
python -m django generate_proto --app example_app
```

6. Run the server (without creating a custom entrypoint module):

```bash
python manage.py run_grpcserver
```

Or run it from your own module if you prefer:
```python
import os
import django
from grpc_extra import GrpcExtra


def main() -> None:
    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "example_project.settings")
    django.setup()
    GrpcExtra(pattern="{app}.grpc.services").run_server()


if __name__ == "__main__":
    main()
```

```bash
PYTHONPATH=app python -m example_project.grpc_server
```

## Installation

```bash
pip install django-grpc-extra
```

Optional extras:

```bash
pip install "django-grpc-extra[codegen]"      # grpcio-tools
pip install "django-grpc-extra[health]"       # health checking
pip install "django-grpc-extra[reflection]"   # server reflection
pip install "django-grpc-extra[reload]"       # watchfiles live reload
```

## 1) Scaffold gRPC folders in Django apps

Create `grpc/` structure in one app:

```bash
python -m django init_grpc --app example_app
```

Options:
- `--app <label>`: target app label (repeatable)
- `--all`: all installed apps
- `--force`: overwrite existing files

If no options are provided, it behaves like `--all`.

## 2) Declare services and methods with decorators

Create `your_app/grpc/services.py`:

```python
from pydantic import BaseModel

from grpc_extra import grpc_method, grpc_service


class PingRequest(BaseModel):
    message: str


class PingResponse(BaseModel):
    message: str


@grpc_service(
    name="ExampleService",
    app_label="example_app",
    package="example_app",
    proto_path="grpc/proto/example_app.proto",
)
class ExampleService:
    @grpc_method(
        request_schema=PingRequest,
        response_schema=PingResponse,
    )
    def ping(self, request, context):
        # request is already PingRequest (Pydantic), not pb2.
        return {"message": f"pong: {request.message}"}

    @grpc_method(
        request_schema=PingRequest,
        response_schema=PingResponse,
        server_streaming=True,
    )
    def ping_stream(self, request, context):
        return [
            {"message": f"chunk-1: {request.message}"},
            {"message": f"chunk-2: {request.message}"},
        ]

    @grpc_method(response_schema=PingResponse)
    @grpc_pagination()  # must be placed under @grpc_method
    def list_ping(self, request, context):
        return [
            {"message": "a"},
            {"message": "b"},
            {"message": "c"},
        ]
```

### Runtime conversion behavior

- Request: `pb2 -> request_schema (Pydantic)`
- Response: `dict/Pydantic/dataclass/model -> pb2`
- Stream responses support iterables and objects with `.iterator()`
- `Decimal` values are coerced to `string` before pb2 encoding (useful for Django `DecimalField` mapped to proto `string`)
- `ValidationError` maps to `INVALID_ARGUMENT`
- `PermissionError` maps to `PERMISSION_DENIED`
- `grpc_pagination` applies pagination in runtime and augments proto schemas

### Naming behavior

- Python method names can stay `snake_case` (PEP 8), for example `get_user`.
- If `name=` is not provided, RPC name is converted to `UpperCamelCase`, for example `GetUser`.
- Service class names are used as-is (typically already `UpperCamelCase`).
- If you need strict naming, pass `name=...` explicitly.
- Message names are normalized for top-level method schemas:
  - `PingSchema` -> `PingRequest` / `PingResponse`
  - `Ping` -> `PingRequest` / `PingResponse`

## 2.1) Build CRUD gRPC methods from model config

Use `ModelService` when you want prebuilt CRUD methods generated from a config.

```python
from django.db import models
from pydantic import BaseModel, ConfigDict, Field

from grpc_extra import (
    AllowedEndpoints,
    ModelFilterSchema,
    ModelService,
    ModelServiceConfig,
    grpc_service,
)


class Product(models.Model):
    name = models.CharField(max_length=100)

    class Meta:
        app_label = "example_app"


class ProductOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    name: str


class ProductCreate(BaseModel):
    name: str


class ProductListFilter(ModelFilterSchema):
    name: str | None = None
    ids: list[int] | None = Field(default=None, json_schema_extra={"op": "in", "field": "id"})
    min_id: int | None = Field(default=None, json_schema_extra={"op": "gte", "field": "id"})


@grpc_service(app_label="example_app", package="example_app")
class ProductService(ModelService):
    config = ModelServiceConfig(
        model=Product,
        allowed_endpoints=[
            AllowedEndpoints.LIST,
            AllowedEndpoints.STREAM_LIST,
            AllowedEndpoints.DETAIL,
            AllowedEndpoints.CREATE,
        ],
        list_schema=ProductOut,
        list_filter=ProductListFilter,
        detail_schema=ProductOut,
        create_schema=ProductCreate,
    )
```

This class generates and registers RPC handlers on the service class itself.
For this config, the service gets:
- `List` (single response with pagination metadata and `results`)
- `StreamList` (server-streaming)
- `Detail`
- `Create`

`Detail` maps missing objects to `NOT_FOUND` (`ObjectDoesNotExist` -> gRPC `NOT_FOUND`).

`List` uses pagination by default via `DEFAULT_PAGINATION_CLASS`.
Set `list_pagination_class=None` in `ModelServiceConfig` to disable pagination.

`list_filter` is used for both `List` and `StreamList` request schemas.
Default helper supports these filter operators via field metadata:
- `exact` (default)
- `in`
- `not_in`
- `lt`
- `gt`
- `lte`
- `gte`

You can customize data access by providing `data_helper_class`.
The helper must inherit `ModelDataHelper` and implement CRUD methods.

```python
from grpc_extra import ModelDataHelper


class CustomDataHelper(ModelDataHelper):
    def list_objects(self, request):
        ...

    def get_object(self, request):
        ...

    def create_object(self, request):
        ...

    def update_object(self, request):
        ...

    def patch_object(self, request):
        ...

    def delete_object(self, request):
        ...
```

## 2.2) Permissions

Permissions can be declared:
- at service level via `@grpc_service(..., permissions=[...])`
- at method level via `@grpc_method(..., permissions=[...])` or `@grpc_permissions(...)` under `@grpc_method`
- service-level permissions are the default policy
- explicit method-level permissions override service-level permissions

Permission contract:
- `has_perm(self, request, context, service, method_meta) -> bool`
- `has_obj_perm(self, request, context, service, method_meta, obj) -> bool`

Runtime behavior:
- service-level: `has_perm` for all methods
- method-level: `has_perm` and `has_obj_perm`
- for `Detail`/`Get`: service-level `has_obj_perm` is also applied

## 3) Generate `.proto` and `pb2`

Generate proto and compiled files for one app:

```bash
python -m django generate_proto --app example_app
```

Default proto location:
- `<app>/grpc/proto/<app>.proto`

Generate only `.proto`:

```bash
python -m django generate_proto --app example_app --no-compile
```

Generate `.pyi` as well:

```bash
python -m django generate_proto --app example_app --pyi
```

## 4) Manual `protoc` (optional)

If you want to run `protoc` yourself:

```bash
python -m grpc_tools.protoc \
  -I app \
  --python_out=app \
  --grpc_python_out=app \
  app/example_app/grpc/proto/example_app.proto
```

With `.pyi`:

```bash
python -m grpc_tools.protoc \
  -I app \
  --python_out=app \
  --grpc_python_out=app \
  --pyi_out=app \
  app/example_app/grpc/proto/example_app.proto
```

## 5) Run the gRPC server

### Option A: `manage.py run_grpcserver` (quick local testing)

```bash
python manage.py run_grpcserver
```

Common flags:
- `--bind [::]:50051`
- `--max-workers 10`
- `--max-msg-mb 32`
- `--health / --no-health`
- `--reflection / --no-reflection`
- `--reload / --no-reload`
- `--reload-path app` (repeatable)
- `--discover / --no-discover`
- `--auth-backend path.to.auth_backend`
- `--interceptor path.to.interceptor` (repeatable)
- `--request-logging / --no-request-logging`
- `--logger-name grpc_extra`

Examples:

```bash
python manage.py run_grpcserver --bind [::]:50051 --health --reflection
python manage.py run_grpcserver --reload --reload-path app
python manage.py run_grpcserver --auth-backend path.to.auth_backend --interceptor path.to.interceptor
```

### Option B: custom server entrypoint module

Create a server entrypoint module:

```python
# app/example_project/grpc_server.py
import os

import django

from grpc_extra import GrpcExtra


def main() -> None:
    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "example_project.settings")
    django.setup()
    grpc_extra = GrpcExtra(pattern="{app}.grpc.services")
    grpc_extra.run_server()


if __name__ == "__main__":
    main()
```

Run it:

```bash
PYTHONPATH=app python -m example_project.grpc_server
```

For development live reload:

```python
grpc_extra.run_server(reload=True, reload_paths=("app",))
```

## 6) Django settings integration

`grpc_extra` reads runtime config from `GRPC_EXTRA`:

```python
GRPC_EXTRA = {
    "ENABLE_HEALTH": True,
    "ENABLE_REFLECTION": False,
    "ENABLE_REQUEST_LOGGING": True,
    "LOGGER_NAME": "grpc_extra",
    "BIND": "[::]:50051",
    "MAX_WORKERS": 10,
    "MAX_MSG_MB": 32,
    "AUTH_BACKEND": "path.to.auth_backend",   # optional
    "EXCEPTION_MAPPER": "path.to.mapper",     # optional
    "SCHEMA_SUFFIX_STRIP": ("Schema",),       # optional
    "REQUEST_SUFFIX": "Request",              # optional
    "RESPONSE_SUFFIX": "Response",            # optional
    "DEFAULT_PAGINATION_CLASS": "grpc_extra.pagination.LimitOffsetPagination",  # optional
    "ENABLE_RELOAD": False,                   # optional
    "RELOAD_PATHS": ("app",),                 # optional
}
```

Notes:
- `AUTH_BACKEND`: callable, class (instantiated without args), or import path
- auth result semantics: `False` or `None` means `UNAUTHENTICATED`
- `EXCEPTION_MAPPER`: callable `(exc: Exception) -> MappedError` or import path to callable (class is not supported)
- `SCHEMA_SUFFIX_STRIP`, `REQUEST_SUFFIX`, `RESPONSE_SUFFIX`: proto message naming adapter for top-level `request_schema`/`response_schema`
- `DEFAULT_PAGINATION_CLASS`: default class used by `@grpc_pagination()` and `ModelService` list endpoint
- request logs go to logger defined by `LOGGER_NAME` and then through standard Django `LOGGING`

## 7) Generate Python SDK (experimental)

> Status: **Experimental**
>
> SDK generator behavior and generated file layout may change between releases.

Generate SDK from discovered proto files:

```bash
python -m django generate_client_sdk --language python --all
```

Common options:
- `--language python`
- `--out <path>`
- `--name <sdk-package-name>`
- `--app <label>` (repeatable)
- `--all`
- `--skip-proto` (skip proto regeneration, use existing proto files)

### Generated layout

SDK now uses per-app generated modules to avoid huge monolithic files:

```text
<sdk>/src/<package>/
  <app>/grpc/proto/            # generated protobuf artifacts
    *_pb2.py
    *_pb2_grpc.py
    *.pyi
  client.py                  # custom layer (not overwritten if exists)
  client_generated.py        # regenerated
  helpers.py                 # custom-safe helper module (created if missing)
  services.py                # facade, regenerated
  typed_services.py          # facade, regenerated
  models.py                  # facade, regenerated
  generated/
    <app>/
      services.py            # regenerated
      typed_services.py      # regenerated
      models.py              # regenerated
```

Files that are safe for your custom code:
- `client.py`
- `helpers.py`

Files that are always regenerated:
- `client_generated.py`
- `services.py`
- `typed_services.py`
- `models.py`
- everything in `generated/<app>/`

### Raw vs typed client

```python
from my_sdk import ClientConfig, GrpcClient, extract_results, message_to_dict

client = GrpcClient(ClientConfig(host="localhost:50051"))

# Raw protobuf response
raw_resp = client.product.list()
raw_dict = message_to_dict(raw_resp)
rows = extract_results(raw_resp)  # for paginated list envelopes

# Typed response (Pydantic models generated from proto)
typed_resp = client.typed.product.list()
```

Notes:
- `client.<service>.<method>()` -> raw protobuf messages (`*_pb2`).
- `client.typed.<service>.<method>()` -> Pydantic models generated from proto schema.
- `extract_results(...)` is a convenience helper for paginated list responses.

## 8) Recommended `.gitignore` entries

If generated files are not committed:

```gitignore
app/**/grpc/**/proto/*_pb2.py
app/**/grpc/**/proto/*_pb2_grpc.py
app/**/grpc/**/proto/*_pb2.pyi
```

## 9) Common issues

`ModuleNotFoundError: <name>_pb2`:
- proto was generated with wrong include path or output path
- re-run generation with correct `-I` and output directories

`RESOURCE_EXHAUSTED`:
- message size limits are too small
- increase `MAX_MSG_MB` (server) and client message limits
