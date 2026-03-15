# Model Service Overview

`ModelService` is for CRUD-style endpoints over Django models with minimal boilerplate.

It auto-generates RPC methods from `ModelServiceConfig` and integrates filtering, searching, ordering and pagination.

## Generated Endpoints

Depending on `allowed_endpoints`:

- `List` (unary list)
- `StreamList` (server stream)
- `Detail`
- `Create`
- `Update`
- `Patch`
- `Delete`

## Minimal Example

```python
from pydantic import BaseModel, ConfigDict
from grpc_extra import (
    AllowedEndpoints,
    ModelService,
    ModelServiceConfig,
    grpc_service,
)


class ProductOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    name: str


@grpc_service(app_label="products", package="products")
class ProductService(ModelService):
    config = ModelServiceConfig(
        model=Product,
        allowed_endpoints=[
            AllowedEndpoints.LIST,
            AllowedEndpoints.DETAIL,
            AllowedEndpoints.CREATE,
        ],
        list_schema=ProductOut,
        detail_schema=ProductOut,
        create_schema=ProductOut,
    )
```

## Extended Example (with list customizations)

```python
from grpc_extra import (
    AllowedEndpoints as Endpoints,
    LimitOffsetPagination,
    ModelService,
    ModelServiceConfig,
    Ordering,
    Searching,
    grpc_service,
)


@grpc_service(name="ProductService", app_label="products", package="products")
class ProductService(ModelService):
    config = ModelServiceConfig(
        model=Product,
        allowed_endpoints=[Endpoints.LIST, Endpoints.DETAIL],
        list_schema=ProductListSchema,
        detail_schema=ProductDetailSchema,
        list_pagination_class=LimitOffsetPagination,
        list_ordering_class=Ordering,
        list_ordering_fields=["sku", "name"],
        list_searching_class=Searching,
        list_search_fields=["sku", "name", "description"],
    )
```

Runtime order for list endpoint:

1. searching
2. ordering
3. pagination

## QuerySet Customization

For performance and relation preloading:

- `queryset`: base queryset for list and general operations
- `detail_queryset`: dedicated queryset for detail endpoint

```python
config = ModelServiceConfig(
    model=Product,
    queryset=Product.objects.select_related("category", "brand"),
    detail_queryset=Product.objects.select_related(
        "category",
        "brand",
        "supplier",
        "warehouse",
    ),
    ...
)
```

Why this matters:

- list/detail often need different relation graphs
- avoids N+1 queries
- keeps endpoint-specific performance predictable

## Generated Choice Endpoints

`ModelService` can also generate read-only RPCs for Django `IntegerChoices` and `TextChoices`.

This is useful when the service should expose enum-like reference data for clients, DWH services, forms, or other integrations without hand-writing one method per choice set.

```python
from django.db import models

from grpc_extra import (
    AllowedEndpoints as Endpoints,
    ChoiceEndpointConfig,
    ModelService,
    ModelServiceConfig,
    grpc_service,
)


class ProductStatus(models.IntegerChoices):
    ACTIVE = 1, "Active"
    ARCHIVED = 2, "Archived"


@grpc_service(
    name="ProductService",
    app_label="products",
    package="products",
    permissions=[IsAuthActive],
)
class ProductService(ModelService):
    config = ModelServiceConfig(
        model=Product,
        allowed_endpoints=[Endpoints.LIST, Endpoints.DETAIL],
        list_schema=ProductListSchema,
        detail_schema=ProductDetailSchema,
        choice_endpoints=[
            ChoiceEndpointConfig(
                name="Statuses",
                source=ProductStatus,
                description="List available product statuses.",
            ),
        ],
    )
```

The builder generates:

- python handler: `statuses`
- RPC method: `Statuses`
- request schema: `google.protobuf.Empty`
- response schema: `list[IntChoiceSchema]`

For `TextChoices`, the generated response uses `TextChoiceSchema`.

Available config fields:

- `name`: public RPC method name
- `source`: a Django choices class (or another object exposing `.choices`)
- `description`: optional RPC description
- `permissions`: optional method-level permissions
- `response_schema`: optional custom schema override

### Permission Semantics

- if `permissions` is omitted on `ChoiceEndpointConfig`, the generated RPC inherits service-level permissions
- if `permissions=[...]` is provided, it overrides service-level permissions for that generated RPC

Example: make one choice endpoint public while keeping the rest of the service protected:

```python
choice_endpoints=[
    ChoiceEndpointConfig(
        name="Statuses",
        source=ProductStatus,
        permissions=[AllowAny],
    ),
]
```

## Data Helper

You can replace storage logic with custom helper:

```python
from grpc_extra import ModelDataHelper


class CustomDataHelper(ModelDataHelper):
    def list_objects(self, request):
        return Product.objects.filter(is_deleted=False)

    def get_object(self, request):
        return Product.objects.get(pk=request.id, is_deleted=False)

    def create_object(self, request):
        return Product.objects.create(**request.model_dump())

    def update_object(self, request):
        ...

    def patch_object(self, request):
        ...

    def delete_object(self, request):
        ...
```

Attach it:

```python
@grpc_service(app_label="products", package="products")
class ProductService(ModelService):
    data_helper_class = CustomDataHelper
    config = ModelServiceConfig(...)
```

## Error Semantics

- Missing object in `Detail` -> `NOT_FOUND`
- Validation problems -> `INVALID_ARGUMENT`
- Permission denial -> `PERMISSION_DENIED`

## Permissions in ModelService

Permissions are declared the same way as regular services.

- service-level permissions via `@grpc_service(..., permissions=[...])`
- method-level permissions via generated method metadata or custom methods
- method-level permissions override service-level permissions when declared explicitly

For `Detail`/`Get`, object-level checks are applied on both method-level and service-level permissions only when the method does not override service-level permissions.

## Tips Before Production

- Start with `LIST + DETAIL` and stable schemas first.
- Always define explicit `list_search_fields` and `list_ordering_fields`.
- Use `queryset`/`detail_queryset` from day one to avoid performance regressions.
- Keep schema field types proto-compatible (`Decimal` maps to proto `string`).
