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

- service-level: `has_perm` on all methods
- method-level: `has_perm` and `has_obj_perm`
- for `Detail/Get`: service-level `has_obj_perm` is also applied

Built-ins:

- `AllowAny`
- `IsAuthenticated`
- `IsAuthenticatedActive` (`IsAuthActive` alias)
- `DjangoModelPermissions`
