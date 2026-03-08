# Model Service Pagination

Pagination controls how `List` responses are sliced and wrapped with metadata.

In `django-grpc-extra` pagination can be applied in two places:

- `ModelService` (`list_pagination_class`)
- regular service methods via `@grpc_pagination`

---

## Where It Applies

For `ModelService`:

- `List` (unary) -> pagination supported
- `StreamList` (server streaming) -> pagination is not applied

List pipeline order:

1. filtering
2. searching
3. ordering
4. pagination

Pagination always runs last, so pages are built from already filtered/ordered data.

---

## Default Pagination: `LimitOffsetPagination`

Default class is `LimitOffsetPagination`.

It extends request schema with:

- `limit` (`default=100`, `ge=1`, `le=1000`)
- `offset` (`default=0`, `ge=0`)

It wraps response schema as:

- `count`: total matched rows/items
- `limit`: requested limit
- `offset`: requested offset
- `results`: repeated item schema

Example request:

```json
{
  "limit": 20,
  "offset": 40
}
```

Example response:

```json
{
  "count": 312,
  "limit": 20,
  "offset": 40,
  "results": [
    {"id": 41, "name": "..."},
    {"id": 42, "name": "..."}
  ]
}
```

---

## ModelService Usage

```python
from grpc_extra import (
    AllowedEndpoints,
    LimitOffsetPagination,
    ModelService,
    ModelServiceConfig,
    grpc_service,
)


@grpc_service(app_label="inventory", package="inventory")
class ProductService(ModelService):
    config = ModelServiceConfig(
        model=Product,
        allowed_endpoints=[AllowedEndpoints.LIST],
        list_schema=ProductOut,
        list_pagination_class=LimitOffsetPagination,
    )
```

If `list_pagination_class` is omitted, framework uses `DEFAULT_PAGINATION_CLASS` from settings.

### Disable pagination for List

```python
config = ModelServiceConfig(
    ...,
    list_pagination_class=None,
)
```

---

## Regular Service Usage: `@grpc_pagination`

```python
from grpc_extra import grpc_method, grpc_pagination


@grpc_method(request_schema=None, response_schema=ProductOut)
@grpc_pagination
# also valid: @grpc_pagination()
def list_products(self, request, context):
    return Product.objects.all()
```

Supported forms:

- `@grpc_pagination`
- `@grpc_pagination()`
- `@grpc_pagination(CustomPagination)`

Constraints:

- unary methods only
- must be used with `@grpc_method`
- `response_schema` must be set

---

## Proto Contract (What Clients See)

For limit/offset pagination, generated proto request contains `limit`/`offset` fields and response contains `results` + metadata fields.

This means client code should treat paginated endpoints as object responses, not plain repeated top-level arrays.

If you change pagination class later, proto contract changes. Regenerate stubs and update clients.

---

## Global Default Pagination Class

```python
GRPC_EXTRA = {
    "DEFAULT_PAGINATION_CLASS": "grpc_extra.pagination.LimitOffsetPagination",
}
```

Used by:

- `ModelService` list endpoints (if per-service class is not provided)
- `@grpc_pagination` without explicit class

---

## Custom Pagination Class

Create a class inheriting `BasePagination` and implement three methods:

- `build_request_schema(request_schema)`
- `build_response_schema(response_schema)`
- `paginate(result, request)`

Example:

```python
from pydantic import BaseModel, Field, create_model
from grpc_extra.pagination import BasePagination


class PageNumberPagination(BasePagination):
    @classmethod
    def build_request_schema(cls, request_schema: type[BaseModel] | None) -> type[BaseModel]:
        name = f"{request_schema.__name__}WithPage" if request_schema else "PageRequest"
        if request_schema is None:
            return create_model(
                name,
                page=(int, Field(default=1, ge=1)),
                page_size=(int, Field(default=20, ge=1, le=200)),
            )
        return create_model(
            name,
            __base__=request_schema,
            page=(int, Field(default=1, ge=1)),
            page_size=(int, Field(default=20, ge=1, le=200)),
        )

    @classmethod
    def build_response_schema(cls, response_schema: type[BaseModel]) -> type[BaseModel]:
        return create_model(
            f"{response_schema.__name__}Page",
            total=(int, ...),
            page=(int, ...),
            page_size=(int, ...),
            items=(list[response_schema], ...),
        )

    @classmethod
    def paginate(cls, result, request: BaseModel) -> dict:
        # Must return data matching build_response_schema.
        ...
```

Attach:

- per-service: `list_pagination_class=PageNumberPagination`
- per-method: `@grpc_pagination(PageNumberPagination)`

---

## QuerySet vs List Behavior

Pagination supports both:

- `QuerySet`: efficient `count()` and slicing
- Python `list` / iterable: in-memory slicing

For large datasets, return `QuerySet` whenever possible.

---

## Interaction with Searching and Ordering

Because pagination is final stage:

- search/order changes directly affect page boundaries
- unstable ordering leads to unstable pages

Recommendations:

1. always configure explicit ordering fields
2. sort by indexed and deterministic fields
3. avoid non-deterministic ordering for paginated endpoints

---

## Common Errors

### `INVALID_ARGUMENT` for `limit`/`offset`

Triggered by request validation, for example:

- `limit <= 0`
- `offset < 0`
- wrong type

### Pagination configured on streaming endpoint

Pagination wrappers are unary-oriented and not intended for streaming responses.

### Client parse errors after schema changes

Typical root cause: server proto updated, client stubs stale.

Fix sequence:

1. regenerate proto and stubs
2. restart server
3. refresh API client descriptor/cache

---

## Stability Recommendations

1. Keep one response envelope style per endpoint (do not switch often).
2. Keep max page size conservative.
3. Prefer additive changes over renaming/removing pagination fields.
4. Document defaults (`limit`, `offset`) for client teams.
5. Add tests for first page, middle page, empty tail page, invalid bounds.
