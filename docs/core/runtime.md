# Runtime

This section describes what happens between incoming gRPC request and your service method result.

## High-level Flow

For each RPC call runtime performs:

1. decode incoming pb2 request into Pydantic schema
2. apply service/method permissions
3. call your Python method
4. apply searching/ordering/pagination (if configured)
5. encode method result into outgoing pb2 response
6. map exceptions to gRPC status

## Request Decode

Request decode function:

- input: protobuf message instance
- output: `request_schema` Pydantic model (or raw object if schema is `None`)

### Unary request

```python
@grpc_method(request_schema=PingRequest, response_schema=PingResponse)
def ping(self, request, context):
    # request is PingRequest here
    return {"message": request.message}
```

### Stream request

For `client_streaming=True`, runtime decodes each incoming item lazily.

## Response Encode

Encoder accepts these return types:

- `dict`
- `pydantic.BaseModel`
- dataclass instance
- Django model instance
- generic object with attributes

Then it validates against `response_schema` and constructs pb2 response.

## Supported Method Shapes

All four gRPC shapes are supported:

- unary-unary
- unary-stream
- stream-unary
- stream-stream

## Streaming Rules

- For server-streaming and bidi methods your method must return iterable.
- For stream-unary pagination is not supported.
- For stream responses object permissions are checked per yielded item.

## Search/Order/Pagination Pipeline

For unary list-like responses runtime applies modifiers in this order:

1. searching
2. ordering
3. pagination

This order is used in ModelService list endpoints and decorator-based methods.

## Collection and Wrapper Behavior

### Top-level list response

If you declared:

```python
@grpc_method(response_schema=list[ItemSchema])
```

runtime auto-wraps output into internal schema:

```python
{"items": [...]} 
```

Works with:

- `list`
- `QuerySet`
- iterable objects
- objects exposing `.iterator()`

### Decimal handling

`Decimal` values are coerced to `string` before pb2 construction.

Useful when Django `DecimalField` maps to proto `string`.

## Permissions in Runtime

Checks are executed before/after method call depending on type:

- service-level `has_perm` for all methods
- method-level `has_perm` for all methods
- method-level `has_obj_perm` for object/response checks
- service-level `has_obj_perm` also applies to `Detail/Get`

## Exception Mapping

Default mapping:

- `pydantic.ValidationError` -> `INVALID_ARGUMENT`
- request decode with validation cause -> `INVALID_ARGUMENT`
- `ObjectDoesNotExist` -> `NOT_FOUND`
- `PermissionError` -> `PERMISSION_DENIED`
- `OrderingError` / `SearchingError` -> `INVALID_ARGUMENT`
- `RequestDecodeError` / `ResponseEncodeError` -> `INTERNAL`
- any other exception -> `UNKNOWN`

## Custom Exception Mapper

You can override mapper in settings:

```python
GRPC_EXTRA = {
    "EXCEPTION_MAPPER": "path.to.custom_exception_mapper",
}
```

Mapper contract:

```python
from grpc_extra.exceptions import MappedError


def custom_exception_mapper(exc: Exception) -> MappedError:
    ...
```

`EXCEPTION_MAPPER` must resolve to callable (function/callable object), not class type.

## Runtime Pitfalls

### 1) `invalid wire type`

Usually client descriptor is stale after proto changes.

Fix:

- regenerate proto/pb2
- restart server
- recreate gRPC connection in client tool

### 2) `Failed to encode response`

Most often schema/payload mismatch.

Typical causes:

- wrong field type in returned dict/model
- relation object returned where scalar is expected
- stale proto versus current schema

### 3) Search/order silently not applied

Ensure fields are configured explicitly in decorators/model config.

### 4) Auth backend rejects before token validate

Most often metadata extraction mismatch (header/scheme/value format).

## Performance Notes

- Prefer returning `QuerySet` for large data, let runtime iterate lazily where possible.
- For model-heavy endpoints define `queryset` / `detail_queryset` with `select_related`/`prefetch_related`.
- Keep response schemas tight; avoid expensive nested relations unless needed.
