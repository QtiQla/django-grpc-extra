from __future__ import annotations

import importlib
from collections.abc import Iterable
from typing import TYPE_CHECKING, Any, cast

if TYPE_CHECKING:
    from django.db.models import Model

    from .registry import MethodMeta


class PermissionError(Exception):
    pass


class BasePermission:
    """Base permission contract for gRPC service and method checks."""

    message = "Permission denied."

    def has_perm(
        self,
        request: Any,
        context: Any,
        service: object,
        method_meta: "MethodMeta",
    ) -> bool:
        return True

    def has_obj_perm(
        self,
        request: Any,
        context: Any,
        service: object,
        method_meta: "MethodMeta",
        obj: Any,
    ) -> bool:
        return True


PermissionLike = BasePermission | type[BasePermission] | str


class AllowAny(BasePermission):
    pass


class IsAuthenticated(BasePermission):
    message = "Authentication required."

    def has_perm(
        self,
        request: Any,
        context: Any,
        service: object,
        method_meta: "MethodMeta",
    ) -> bool:
        user = _resolve_user(context)
        if user is None:
            return False
        authenticated = getattr(user, "is_authenticated", None)
        if authenticated is None:
            return bool(user)
        return bool(authenticated)


class IsAuthenticatedActive(IsAuthenticated):
    message = "Active authenticated user required."

    def has_perm(
        self,
        request: Any,
        context: Any,
        service: object,
        method_meta: "MethodMeta",
    ) -> bool:
        if not super().has_perm(request, context, service, method_meta):
            return False
        user = _resolve_user(context)
        if user is None:
            return False
        is_active = getattr(user, "is_active", None)
        if is_active is None:
            return True
        return bool(is_active)


class IsAuthActive(IsAuthenticatedActive):
    """Alias for compatibility with existing naming habits."""


def _resolve_user(context: Any) -> Any | None:
    user = getattr(context, "user", None)
    if user is not None:
        return user
    return getattr(context, "auth", None)


class DjangoModelPermissions(BasePermission):
    """Permission checker for RPC model methods using Django auth codenames."""

    message = "Model permissions are required."
    perms_map: dict[str, list[str]] = {
        "LIST": ["%(app_label)s.view_%(model_name)s"],
        "STREAM_LIST": ["%(app_label)s.view_%(model_name)s"],
        "DETAIL": ["%(app_label)s.view_%(model_name)s"],
        "GET": ["%(app_label)s.view_%(model_name)s"],
        "CREATE": ["%(app_label)s.add_%(model_name)s"],
        "UPDATE": ["%(app_label)s.change_%(model_name)s"],
        "PATCH": ["%(app_label)s.change_%(model_name)s"],
        "DELETE": ["%(app_label)s.delete_%(model_name)s"],
        "DESTROY": ["%(app_label)s.delete_%(model_name)s"],
    }

    def __init__(self, model: type["Model"] | None = None) -> None:
        self.model = model

    def get_required_permissions(
        self, action: str, model_cls: type["Model"]
    ) -> list[str]:
        kwargs: dict[str, str | None] = {
            "app_label": model_cls._meta.app_label,
            "model_name": model_cls._meta.model_name,
        }
        if action not in self.perms_map:
            raise PermissionError(f"Unsupported permission RPC action: {action}")
        return [perm % kwargs for perm in self.perms_map[action]]

    def has_perm(
        self,
        request: Any,
        context: Any,
        service: object,
        method_meta: "MethodMeta",
    ) -> bool:
        user = _resolve_user(context)
        if user is None:
            return False
        has_perms = getattr(user, "has_perms", None)
        if not callable(has_perms):
            return False
        model_cls = self._resolve_model(service)
        if model_cls is None:
            return True
        action = self._resolve_action(method_meta)
        if action is None:
            return True
        perms = self.get_required_permissions(action, model_cls)
        return bool(has_perms(perms))

    def _resolve_model(self, service: object) -> type["Model"] | None:
        if self.model is not None:
            return self.model
        config = getattr(service, "config", None)
        if config is None:
            return None
        return cast(type["Model"] | None, getattr(config, "model", None))

    def _resolve_action(self, method_meta: "MethodMeta") -> str | None:
        candidate = method_meta.name.replace("-", "_").upper()
        if candidate in self.perms_map:
            return candidate
        fallback = method_meta.handler_name.replace("-", "_").upper()
        if fallback in self.perms_map:
            return fallback
        return None


def resolve_permission(value: PermissionLike) -> BasePermission:
    if isinstance(value, BasePermission):
        return value
    if isinstance(value, str):
        module_path, _, attr = value.rpartition(".")
        if not module_path or not attr:
            raise PermissionError(f"Invalid permission class path: {value}")
        module = importlib.import_module(module_path)
        resolved = getattr(module, attr, None)
        if not isinstance(resolved, type) or not issubclass(resolved, BasePermission):
            raise PermissionError(f"Permission '{value}' is not a BasePermission class")
        return resolved()
    if isinstance(value, type) and issubclass(value, BasePermission):
        return value()
    raise PermissionError("Permission must be instance, class or import path string.")


def resolve_permissions(
    values: Iterable[PermissionLike] | None,
) -> tuple[BasePermission, ...]:
    if values is None:
        return ()
    return tuple(resolve_permission(value) for value in values)
