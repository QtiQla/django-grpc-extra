# Error Mapping

This page documents default runtime exception-to-gRPC status conversion and practical debugging guidance.

## Default Mapping Table

| Exception type | gRPC status | Typical cause |
|---|---|---|
| `pydantic.ValidationError` | `INVALID_ARGUMENT` | request payload doesn't match schema |
| `RequestDecodeError` with validation cause | `INVALID_ARGUMENT` | pb2 request decoded to invalid Pydantic payload |
| `PermissionError` | `PERMISSION_DENIED` | permission check failed |
| `django.core.exceptions.ObjectDoesNotExist` | `NOT_FOUND` | `Detail/Get` object is missing |
| `OrderingError` / `SearchingError` | `INVALID_ARGUMENT` | invalid ordering/search field/value |
| `RequestDecodeError` / `ResponseEncodeError` | `INTERNAL` | runtime conversion failure |
| any other exception | `UNKNOWN` | unhandled application/runtime error |

## Where Mapping Happens

Runtime catches exceptions inside method wrappers and aborts gRPC context with mapped status + message.

This behavior applies to unary and streaming wrappers.

## Common Error Patterns

## `INVALID_ARGUMENT`

Most common triggers:

- missing required request fields
- wrong field types (`str` instead of `int`, invalid enum value)
- malformed search/order values

What to check:

1. request payload against generated proto schema
2. request Pydantic schema defaults/constraints
3. decorator-provided request augmentation (`search`, `ordering`, `limit`, `offset`)

## `PERMISSION_DENIED`

Most common triggers:

- `has_perm` returned `False`
- `has_obj_perm` returned `False`

What to check:

1. service-level vs method-level permission placement
2. identity attached to `context` in auth backend (`context.user`)
3. object-level checks for `Detail/Get`

## `UNAUTHENTICATED`

Most common triggers:

- auth backend returned `None` or `False`
- token extraction failed (header/scheme/value format)

What to check:

1. metadata key/value in client call
2. backend `scheme`/`header` configuration
3. whitelist logic for public RPC methods (e.g. health)

## `NOT_FOUND`

Most common trigger:

- object lookup in detail endpoint fails

What to check:

1. lookup field (`id`, external key, etc.)
2. queryset filters applied by service/data helper

## `INTERNAL`

Most common triggers:

- response payload doesn't match `response_schema`
- unsupported payload shape for pb2 constructor

What to check:

1. actual method return type
2. nested schema field types
3. decimal/date/time conversions and proto field types

## `UNKNOWN`

Means exception wasn't matched by default mapper.

What to check:

1. server logs with stack trace
2. add custom mapper to classify domain exceptions

## Custom Exception Mapper

You can override mapping globally:

```python
from grpc_extra.exceptions import MappedError
import grpc


def custom_exception_mapper(exc: Exception) -> MappedError:
    if isinstance(exc, DomainConflictError):
        return MappedError(grpc.StatusCode.ALREADY_EXISTS, str(exc))
    return MappedError(grpc.StatusCode.UNKNOWN, str(exc))


GRPC_EXTRA = {
    "EXCEPTION_MAPPER": custom_exception_mapper,
    # or import path string
    # "EXCEPTION_MAPPER": "path.to.custom_exception_mapper",
}
```

Mapper must be callable; class types are not accepted.

## Debugging Checklist

When status is unexpected:

1. reproduce with minimal payload
2. check generated proto is up to date
3. restart server
4. recreate client reflection/descriptor cache
5. inspect server logs with full traceback
6. verify auth + permissions path before business logic

