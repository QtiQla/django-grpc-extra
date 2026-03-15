# Core Decorators

This section explains how decorators define runtime behavior, proto generation, and request/response schemas.

## `@grpc_service`

Declares a class as a gRPC service and registers metadata.

```python
from grpc_extra import grpc_service


@grpc_service(
    name="ExampleService",
    app_label="products",
    package="products",
    proto_path="grpc/proto/products.proto",
    permissions=[],
)
class ExampleService:
    pass
```

### Parameters

- `name`: service name in proto (`service <name> { ... }`). Default: class name.
- `app_label`: Django app label used for discovery and proto path resolution.
- `package`: proto package name. Default: `app_label`.
- `proto_path`: target proto path inside app. Default: `grpc/proto/<app_label>.proto`.
- `description`: doc string written as proto comment.
- `factory`: custom service instance factory for runtime.
- `permissions`: service-level permission classes/instances/import paths.

## `@grpc_method`

Declares an RPC endpoint and schema contract.

```python
from pydantic import BaseModel
from grpc_extra import grpc_method


class PingRequest(BaseModel):
    message: str


class PingResponse(BaseModel):
    message: str


class ExampleService:
    @grpc_method(request_schema=PingRequest, response_schema=PingResponse)
    def ping(self, request, context):
        return {"message": f"pong: {request.message}"}
```

### Parameters

- `name`: RPC method name in proto. Default: function name converted to `UpperCamelCase`.
- `request_schema`: Pydantic model for input.
- `response_schema`: Pydantic model for output.
- `description`: comment in proto.
- `client_streaming`: request stream mode.
- `server_streaming`: response stream mode.
- `permissions`: method-level permissions.

### Top-level list response

Unary methods can return list payloads via:

```python
@grpc_method(response_schema=list[ItemSchema])
def list_items(self, request, context):
    return Item.objects.values("id", "name")
```

The framework wraps this into an internal response schema with `items: repeated ItemSchema`.

## `@grpc_pagination`

Adds limit/offset request fields and paginated response schema.

Supported forms:

- `@grpc_pagination`
- `@grpc_pagination()`
- `@grpc_pagination(CustomPaginationClass)`

Example:

```python
from grpc_extra import grpc_method, grpc_pagination


@grpc_method(response_schema=ItemOut)
@grpc_pagination
# or @grpc_pagination()
def list_items(self, request, context):
    return Item.objects.all()
```

### Runtime effect

- Request schema gets `limit` and `offset`.
- Response schema is wrapped by pagination class (default: `count/limit/offset/results`).

### Important constraints

- Must be placed under `@grpc_method`.
- Only for unary methods.
- Requires `response_schema`.

## `@grpc_ordering`

Adds ordering support via request field `ordering`.

Supported forms:

- `@grpc_ordering(ordering_fields=[...])`
- `@grpc_ordering(Ordering, ordering_fields=[...])`
- `@grpc_ordering(CustomOrdering, fields=[...])`

Example:

```python
from grpc_extra import grpc_method, grpc_ordering


@grpc_method(request_schema=ItemFilter, response_schema=ItemOut)
@grpc_ordering(ordering_fields=["name", "sku"])
def list_items(self, request, context):
    return Item.objects.all()
```

### Field requirements

By default, fields are required explicitly.

If no fields are passed, decorator raises `ValueError`.

For custom classes this is configurable via class contract:

```python
from grpc_extra.ordering import BaseOrdering


class CustomOrdering(BaseOrdering):
    fields_param_name = "fields"
    fields_required = True

    def __init__(self, fields):
        self.fields = fields

    def order(self, items, request):
        return items
```

Now decorator can be used as:

```python
@grpc_ordering(CustomOrdering, fields=["name"])
```

## `@grpc_searching`

Adds search support via request field `search`.

Supported forms:

- `@grpc_searching(search_fields=[...])`
- `@grpc_searching(Searching, search_fields=[...])`
- `@grpc_searching(CustomSearching, fields=[...])`

Example:

```python
from grpc_extra import grpc_method, grpc_searching


@grpc_method(request_schema=ItemFilter, response_schema=ItemOut)
@grpc_searching(search_fields=["name", "=sku", "description"])
def list_items(self, request, context):
    return Item.objects.values("id", "name", "sku", "description")
```

Lookup prefixes:

- `^field` -> `istartswith`
- `=field` -> `iexact`
- `@field` -> `search`
- `$field` -> `iregex`
- default -> `icontains`

### Field requirements

Like ordering, fields are explicit by default.

Custom class contract:

```python
from grpc_extra.searching import BaseSearching


class CustomSearching(BaseSearching):
    fields_param_name = "fields"
    fields_required = True

    def __init__(self, fields):
        self.fields = fields

    def search(self, items, request):
        return items
```

## `@grpc_permissions`

Adds method-level permissions.

If method-level permissions are declared explicitly, they override service-level permissions for that RPC.

```python
from grpc_extra import grpc_method, grpc_permissions, grpc_service
from grpc_extra.permissions import AllowAny, IsAuthenticated


@grpc_service(permissions=[IsAuthenticated])
class ExampleService:
    @grpc_method(request_schema=PingRequest, response_schema=PingResponse)
    @grpc_permissions(AllowAny)
    def ping(self, request, context):
        return {"message": "ok"}
```

Must be placed under `@grpc_method`.

## Decorator order

Recommended order (top -> bottom):

```python
@grpc_method(...)
@grpc_pagination
@grpc_ordering(ordering_fields=[...])
@grpc_searching(search_fields=[...])
def list_items(...):
    ...
```

Why:

- `grpc_searching` and `grpc_ordering` extend request schema first
- `grpc_pagination` extends final request/response shape
- `grpc_method` collects resulting metadata

## Full example

```python
from pydantic import BaseModel
from grpc_extra import (
    grpc_service,
    grpc_method,
    grpc_pagination,
    grpc_ordering,
    grpc_searching,
)


class ProductFilter(BaseModel):
    is_active: bool | None = None


class ProductOut(BaseModel):
    id: int
    sku: str
    name: str | None


@grpc_service(name="ProductService", app_label="products", package="products")
class ProductService:
    @grpc_method(name="List", request_schema=ProductFilter, response_schema=ProductOut)
    @grpc_pagination
    @grpc_ordering(ordering_fields=["sku", "name"])
    @grpc_searching(search_fields=["sku", "name"])
    def list(self, request, context):
        qs = Product.objects.all().values("id", "sku", "name")
        if request.is_active is not None:
            qs = qs.filter(is_active=request.is_active)
        return qs
```
