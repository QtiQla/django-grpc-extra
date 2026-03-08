# Model Service Filtering

Filtering in `ModelService` is configured through `ModelServiceConfig.list_filter`.

`list_filter` affects request schema for:

- `List`
- `StreamList`

## Two Filtering Modes

1. plain Pydantic schema (exact field matching)
2. `ModelFilterSchema` (operator-based filtering via field metadata)

---

## 1) Plain Pydantic filter schema

Use this when exact equality is enough.

```python
from pydantic import BaseModel


class ProductListFilter(BaseModel):
    category_id: int | None = None
    is_active: bool | None = None
```

Attach in config:

```python
config = ModelServiceConfig(
    model=Product,
    allowed_endpoints=[AllowedEndpoints.LIST],
    list_schema=ProductOut,
    list_filter=ProductListFilter,
)
```

Request example:

```json
{
  "category_id": 10,
  "is_active": true
}
```

Equivalent queryset intent:

```python
Product.objects.filter(category_id=10, is_active=True)
```

---

## 2) `ModelFilterSchema` with operators

Use `ModelFilterSchema` when you need richer filtering (`in`, ranges, etc.).

```python
from pydantic import Field
from grpc_extra import ModelFilterSchema


class ProductListFilter(ModelFilterSchema):
    category_id: int | None = None

    ids: list[int] | None = Field(
        default=None,
        json_schema_extra={"op": "in", "field": "id"},
        description="Filter by product IDs",
    )

    min_price: float | None = Field(
        default=None,
        json_schema_extra={"op": "gte", "field": "price"},
    )

    max_price: float | None = Field(
        default=None,
        json_schema_extra={"op": "lte", "field": "price"},
    )
```

Request example:

```json
{
  "ids": [101, 102, 103],
  "min_price": 10,
  "max_price": 100
}
```

Equivalent queryset intent:

```python
Product.objects.filter(
    id__in=[101, 102, 103],
    price__gte=10,
    price__lte=100,
)
```

---

## Supported operators

Built-in operator set:

- `exact` (default)
- `in`
- `not_in`
- `lt`
- `gt`
- `lte`
- `gte`

If `op` is omitted, `exact` is used.

---

## Operator mapping examples

### `exact` (default)

```python
status: int | None = Field(default=None, json_schema_extra={"field": "status"})
```

Request:

```json
{"status": 2}
```

Intent:

```python
qs.filter(status=2)
```

### `in`

```python
statuses: list[int] | None = Field(
    default=None,
    json_schema_extra={"field": "status", "op": "in"},
)
```

Request:

```json
{"statuses": [1, 2, 3]}
```

Intent:

```python
qs.filter(status__in=[1, 2, 3])
```

### `not_in`

```python
excluded_ids: list[int] | None = Field(
    default=None,
    json_schema_extra={"field": "id", "op": "not_in"},
)
```

Intent:

```python
qs.exclude(id__in=[...])
```

### range (`gt`/`gte`/`lt`/`lte`)

```python
created_from: str | None = Field(
    default=None,
    json_schema_extra={"field": "created_at", "op": "gte"},
)
created_to: str | None = Field(
    default=None,
    json_schema_extra={"field": "created_at", "op": "lte"},
)
```

Intent:

```python
qs.filter(created_at__gte=..., created_at__lte=...)
```

---

## Full `ModelService` example

```python
from pydantic import BaseModel, ConfigDict, Field
from grpc_extra import AllowedEndpoints, ModelFilterSchema, ModelService, ModelServiceConfig, grpc_service


class ItemOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    sku: str
    name: str | None


class ItemFilter(ModelFilterSchema):
    is_active: bool | None = None

    ids: list[int] | None = Field(
        default=None,
        json_schema_extra={"op": "in", "field": "id"},
    )

    min_id: int | None = Field(
        default=None,
        json_schema_extra={"op": "gte", "field": "id"},
    )


@grpc_service(app_label="products", package="products")
class ItemService(ModelService):
    config = ModelServiceConfig(
        model=Item,
        allowed_endpoints=[AllowedEndpoints.LIST, AllowedEndpoints.STREAM_LIST],
        list_schema=ItemOut,
        list_filter=ItemFilter,
    )
```

---

## Filtering + searching/ordering/pagination

List runtime order remains:

1. filtering (from `list_filter`)
2. searching
3. ordering
4. pagination

So `list_filter` narrows base dataset first.

---

## Validation and error behavior

Typical invalid requests return `INVALID_ARGUMENT`:

- wrong field type (e.g. string where `int` expected)
- invalid list element type for `in`
- unknown/invalid operator in custom metadata

---

## Best practices

1. Keep filter schema explicit and small.
2. Use descriptive field names (`min_price`, `created_from`) and map to model fields with `json_schema_extra`.
3. Prefer `ModelFilterSchema` for range and list operations.
4. Add titles/descriptions to fields so generated proto comments are informative.
5. Keep `list_filter` stable to avoid client request-contract churn.
