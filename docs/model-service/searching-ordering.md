# Model Service Searching and Ordering

This section explains how `ModelService` list endpoints apply searching and ordering.

## Where It Is Configured

In `ModelServiceConfig`:

- `list_searching_class`
- `list_search_fields`
- `list_ordering_class`
- `list_ordering_fields`

Example:

```python
from grpc_extra import (
    AllowedEndpoints,
    ModelService,
    ModelServiceConfig,
    Ordering,
    Searching,
    grpc_service,
)


@grpc_service(app_label="products", package="products")
class ProductService(ModelService):
    config = ModelServiceConfig(
        model=Product,
        allowed_endpoints=[AllowedEndpoints.LIST, AllowedEndpoints.STREAM_LIST],
        list_schema=ProductOut,
        list_filter=ProductFilter,
        list_searching_class=Searching,
        list_search_fields=["sku", "name", "description"],
        list_ordering_class=Ordering,
        list_ordering_fields=["sku", "name", "created_at"],
    )
```

## Runtime Pipeline Order

For `List` and `StreamList`:

1. filtering (`list_filter`)
2. searching
3. ordering
4. pagination (`List` only, if enabled)

This means search/order work on already filtered data.

---

## Searching

`Searching` adds request field:

```json
{"search": "foo"}
```

and applies conditions over configured `list_search_fields`.

### Search field lookup prefixes

Supported prefixes:

- `^field` -> `istartswith`
- `=field` -> `iexact`
- `@field` -> full-text `search`
- `$field` -> `iregex`
- `field` (no prefix) -> `icontains`

Example config:

```python
list_search_fields=[
    "=sku",  # exact
    "name",            # icontains
    "^category_name",  # istartswith
]
```

### QuerySet behavior

For querysets, search builds `Q` conditions and applies `.filter(...)`.

Multi-term search semantics:

- terms are split by spaces/commas
- each term must match at least one search field
- all terms must match (AND between terms)

### List/dict behavior

For list-like payloads, search is applied in-memory against dict keys/object attrs.

If field is missing in list item, `SearchingError` is raised.

---

## Ordering

`Ordering` adds request field:

```json
{"ordering": "name,-created_at"}
```

### Field syntax

- `name` -> ascending
- `-name` -> descending
- multiple terms are comma-separated

### QuerySet behavior

For querysets ordering uses `.order_by(*terms)`.

### List/dict behavior

For in-memory lists, sorting is applied with `itemgetter`/`attrgetter`.

If field is missing on list item, `OrderingError` is raised.

---

## Field Validation Rules

Both searching and ordering validate against configured fields.

### Explicit fields are recommended

`ModelServiceConfig` should set explicit field lists:

- `list_search_fields=[...]`
- `list_ordering_fields=[...]`

This keeps behavior predictable and prevents accidental exposure of unintended fields.

### `__all__` for ordering

Ordering supports `"__all__"` in `Ordering` class behavior, but explicit lists are safer for stable API contracts.

---

## Request Examples

### Search only

```json
{
  "search": "ACME"
}
```

### Order only

```json
{
  "ordering": "-sku"
}
```

### Search + order + pagination

```json
{
  "search": "laptop",
  "ordering": "name,-sku",
  "limit": 50,
  "offset": 0
}
```

---

## Common Errors

## `OrderingError: Invalid ordering fields`

Cause:

- requested field is not in allowed ordering fields

Fix:

1. add field to `list_ordering_fields`
2. or change request payload to allowed fields

## Search returns full list

Possible causes:

- search field list is empty
- search term is empty/whitespace
- custom searching class returns input unchanged

Fix:

1. set explicit `list_search_fields`
2. verify request has non-empty `search`
3. verify custom class implementation

## `SearchingError` for list items

Cause:

- configured search field missing in dict/object items

Fix:

- align list item shape with `list_search_fields`

---

## Custom searching/ordering classes

You can replace default classes:

```python
config = ModelServiceConfig(
    ...,
    list_searching_class=CustomSearching,
    list_search_fields=["field_a", "field_b"],
    list_ordering_class=CustomOrdering,
    list_ordering_fields=["field_a"],
)
```

Keep contract compatibility with base classes:

- class should expose `build_request_schema(...)`
- instance should implement `search(...)` or `order(...)`

---

## Best Practices

1. Keep `list_search_fields` and `list_ordering_fields` explicit and minimal.
2. Use indexed DB fields first for ordering/searching when possible.
3. Avoid expensive regex/full-text lookups unless needed.
4. Validate payloads in client SDK/tooling to reduce invalid requests.
5. For high-volume endpoints, combine optimized queryset + explicit fields + pagination.
