# Settings Reference

Runtime is configured through `GRPC_EXTRA` in Django settings.

```python
GRPC_EXTRA = {
    "BIND": "[::]:50051",
    "MAX_WORKERS": 10,
    "MAX_MSG_MB": 32,
    "ENABLE_HEALTH": True,
    "ENABLE_REFLECTION": False,
    "AUTH_BACKEND": "path.to.auth_backend",
    "INTERCEPTORS": [],
    "EXCEPTION_MAPPER": "path.to.exception_mapper",
    "ENABLE_REQUEST_LOGGING": True,
    "LOGGER_NAME": "grpc_extra",
    "DEFAULT_PAGINATION_CLASS": "grpc_extra.pagination.LimitOffsetPagination",
    "ENABLE_RELOAD": False,
    "RELOAD_PATHS": (".",),

    # proto naming customization
    "SCHEMA_SUFFIX_STRIP": ("Schema",),
    "REQUEST_SUFFIX": "Request",
    "RESPONSE_SUFFIX": "Response",

    # optional SDK generator mapping (internal/advanced)
    "SDK_GENERATORS": {
        # "python": "path.to.CustomPythonGenerator",
    },

    # required for PHP generator when used
    "PHP_GRPC_PLUGIN": "/usr/local/bin/grpc_php_plugin",
}
```

## Core Runtime Keys

### `BIND`

Server bind address.

- type: `str`
- default: `"[::]:50051"`

Examples:

- `"0.0.0.0:50051"`
- `"127.0.0.1:50051"`

### `MAX_WORKERS`

ThreadPool workers for gRPC server.

- type: `int`
- default: `10`

### `MAX_MSG_MB`

Max send/receive message size in MB.

- type: `int`
- default: `32`

## Feature Toggles

### `ENABLE_HEALTH`

Enable gRPC health service.

- type: `bool`
- default: `True`

### `ENABLE_REFLECTION`

Enable gRPC reflection service.

- type: `bool`
- default: `False`

### `ENABLE_REQUEST_LOGGING`

Enable request logging interceptor.

- type: `bool`
- default: `True`

### `LOGGER_NAME`

Logger name used for request logs.

- type: `str`
- default: `"grpc_extra"`

## Auth and Error Handling

### `AUTH_BACKEND`

Auth backend source.

- type: callable | class | import path string | `None`
- default: `None`

Contract:

```python
def auth_backend(context, method: str, request=None) -> bool | object | None:
    ...
```

Semantics:

- `False`/`None` => `UNAUTHENTICATED`
- truthy => allow

### `EXCEPTION_MAPPER`

Custom exception mapper.

- type: callable or import path string to callable
- default: internal mapper

Contract:

```python
from grpc_extra.exceptions import MappedError


def exception_mapper(exc: Exception) -> MappedError:
    ...
```

Class types are not accepted as mapper targets.

## Interceptors

### `INTERCEPTORS`

Extra server interceptors.

- type: iterable of import paths / interceptor objects
- default: empty

In reload mode, prefer import paths instead of runtime object instances.

## Pagination Defaults

### `DEFAULT_PAGINATION_CLASS`

Default pagination class for:

- `@grpc_pagination()`
- `ModelService` list endpoint

- type: import path string | class | `None`
- default: `"grpc_extra.pagination.LimitOffsetPagination"`

## Reload Settings

### `ENABLE_RELOAD`

Enable live reload mode.

- type: `bool`
- default: `False`

### `RELOAD_PATHS`

Watched paths for reload mode.

- type: iterable[str]
- default: `( ".", )`

Use uppercase key `RELOAD_PATHS`.

## Proto Naming Settings

### `SCHEMA_SUFFIX_STRIP`

Suffixes stripped from Pydantic schema names before request/response message naming.

- type: `tuple[str, ...] | str`
- default: `( "Schema", )`

### `REQUEST_SUFFIX`

Suffix for generated request messages.

- type: `str`
- default: `"Request"`

### `RESPONSE_SUFFIX`

Suffix for generated response messages.

- type: `str`
- default: `"Response"`

## Optional Advanced Keys

### `SDK_GENERATORS`

Custom SDK generator mapping (advanced/internal use).

- type: `dict[str, str]`
- default: internal mapping

### `PHP_GRPC_PLUGIN`

Path to `grpc_php_plugin` binary for PHP generation.

- type: `str`
- required only if PHP generation is used

## Recommended Baseline (Dev)

```python
GRPC_EXTRA = {
    "BIND": "0.0.0.0:50051",
    "ENABLE_HEALTH": True,
    "ENABLE_REFLECTION": True,
    "ENABLE_REQUEST_LOGGING": True,
    "ENABLE_RELOAD": True,
    "RELOAD_PATHS": ("app",),
}
```

## Recommended Baseline (Prod)

```python
GRPC_EXTRA = {
    "BIND": "0.0.0.0:50051",
    "ENABLE_HEALTH": True,
    "ENABLE_REFLECTION": False,
    "ENABLE_REQUEST_LOGGING": True,
    "MAX_MSG_MB": 32,
    "AUTH_BACKEND": "path.to.auth.GrpcBearerAuth",
    "ENABLE_RELOAD": False,
}
```
