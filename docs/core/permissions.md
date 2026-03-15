# Permissions

## Base Contract

```python
class BasePermission:
    def has_perm(self, request, context, service, method_meta) -> bool:
        return True

    def has_obj_perm(self, request, context, service, method_meta, obj) -> bool:
        return True
```

## Where to Declare

- service-level: `@grpc_service(..., permissions=[...])`
- method-level: `@grpc_method(..., permissions=[...])` or `@grpc_permissions(...)`

## Runtime Behavior

- service-level permissions act as the default policy for all methods
- if a method does not declare permissions, service-level `has_perm` is applied
- if a method declares permissions explicitly, method-level permissions override service-level permissions
- method-level permissions run both `has_perm` and `has_obj_perm`
- for `Detail/Get`, service-level `has_obj_perm` is also applied only when the method does not override permissions

This means you can keep a strict default policy on the service and open one RPC explicitly:

```python
from pydantic import BaseModel

from grpc_extra import grpc_method, grpc_permissions, grpc_service
from grpc_extra.permissions import AllowAny, IsAuthActive


class StatusSchema(BaseModel):
    value: int
    label: str


@grpc_service(
    name="ProductService",
    app_label="products",
    package="products",
    permissions=[IsAuthActive],
)
class ProductService:
    @grpc_method(name="Statuses", response_schema=list[StatusSchema])
    @grpc_permissions(AllowAny)
    def statuses(self, request, context):
        return [
            {"value": 1, "label": "Active"},
            {"value": 2, "label": "Archived"},
        ]
```

You can also explicitly remove inherited service permissions for a method:

```python
@grpc_method(..., permissions=[])
def health_like_rpc(self, request, context):
    ...
```

Built-ins:

- `AllowAny`
- `IsAuthenticated`
- `IsAuthenticatedActive` (`IsAuthActive` alias)
- `DjangoModelPermissions`
