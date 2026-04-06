from __future__ import annotations

import inspect
from collections.abc import Callable, Iterable
from typing import Any, Type, get_args, get_origin

from pydantic import BaseModel, create_model

from .constants import (
    GRPC_METHOD_META,
    GRPC_ORDERING_META,
    GRPC_PAGINATION_META,
    GRPC_PERMISSIONS_META,
    GRPC_SEARCHING_META,
    GRPC_SERVICE_META,
)
from .ordering import BaseOrdering, get_default_ordering_class, resolve_ordering_class
from .pagination import (
    BasePagination,
    get_default_pagination_class,
    resolve_pagination_class,
)
from .permissions import PermissionLike, resolve_permissions
from .registry import MethodMeta, ServiceMeta, registry
from .searching import (
    BaseSearching,
    get_default_searching_class,
    resolve_searching_class,
)
from .utils import to_upper_camel_case


def grpc_service(
    *,
    name: str | None = None,
    app_label: str | None = None,
    package: str | None = None,
    proto_path: str | None = None,
    description: str | None = None,
    factory: Callable[[], object] | None = None,
    permissions: Iterable[PermissionLike] | None = None,
) -> Callable[[Type], Type]:
    """Declare a class as a gRPC service and register its metadata.

    The decorator stores service metadata on the class and registers it in the
    global registry so it can be discovered by proto generation and server setup.

    Args:
        name: Public gRPC service name. Defaults to class name.
        app_label: Django app label used to resolve proto module paths.
        package: Proto package name. Defaults to app label.
        proto_path: Path to the proto file relative to app root.
        description: Optional service description for documentation.
        factory: Optional callable used to create the servicer instance.
    """

    def decorator(service_cls: Type) -> Type:
        service_name = name or service_cls.__name__
        resolved_app_label = app_label or service_cls.__module__.split(".")[0]
        resolved_package = package or resolved_app_label
        resolved_proto_path = proto_path or f"grpc/proto/{resolved_app_label}.proto"
        resolved_description = description or inspect.getdoc(service_cls)
        meta = ServiceMeta(
            name=service_name,
            app_label=resolved_app_label,
            package=resolved_package,
            proto_path=resolved_proto_path,
            description=resolved_description,
            factory=factory,
            permissions=resolve_permissions(permissions),
        )
        setattr(service_cls, GRPC_SERVICE_META, meta)
        registry.register(service_cls)
        return service_cls

    return decorator


def grpc_method(
    *,
    name: str | None = None,
    request_schema: Type[BaseModel] | None = None,
    response_schema: Type[BaseModel] | None = None,
    description: str | None = None,
    client_streaming: bool = False,
    server_streaming: bool = False,
    permissions: Iterable[PermissionLike] | None = None,
) -> Callable[[Callable], Callable]:
    """Declare a method as an RPC endpoint and attach generation metadata.

    Args:
        name: RPC method name. Defaults to function name converted to
            UpperCamelCase.
        request_schema: Pydantic model for request message generation.
        response_schema: Pydantic model for response message generation.
        description: Optional method description for documentation.
        client_streaming: Whether request is a stream.
        server_streaming: Whether response is a stream.
    """

    def decorator(method: Callable) -> Callable:
        method_name = name or to_upper_camel_case(method.__name__)
        resolved_description = description or inspect.getdoc(method)
        searching_meta = getattr(method, GRPC_SEARCHING_META, None)
        ordering_meta = getattr(method, GRPC_ORDERING_META, None)
        pagination_class = getattr(method, GRPC_PAGINATION_META, None)
        has_method_permission_meta = hasattr(method, GRPC_PERMISSIONS_META)
        permissions_meta = getattr(method, GRPC_PERMISSIONS_META, ())
        permissions_overridden = has_method_permission_meta or permissions is not None
        request_schema_resolved = _resolve_top_level_collection_schema(
            request_schema, direction="request"
        )
        response_schema_resolved = _resolve_top_level_collection_schema(
            response_schema, direction="response"
        )
        searching_handler = None
        ordering_handler = None

        if searching_meta is not None:
            searching_class, searching_params = searching_meta
            searching_handler = searching_class(**searching_params)
            request_schema_resolved = searching_handler.build_request_schema(
                request_schema_resolved
            )
        if ordering_meta is not None:
            ordering_class, ordering_params = ordering_meta
            ordering_handler = ordering_class(**ordering_params)
            request_schema_resolved = ordering_handler.build_request_schema(
                request_schema_resolved
            )

        if pagination_class is not None:
            if client_streaming or server_streaming:
                raise ValueError(
                    "grpc_pagination can be used only with unary endpoints."
                )
            if response_schema_resolved is None:
                raise ValueError(
                    "grpc_pagination requires `response_schema` in grpc_method."
                )
            request_schema_resolved = pagination_class.build_request_schema(
                request_schema_resolved
            )
            response_schema_resolved = pagination_class.build_response_schema(
                response_schema_resolved
            )
        meta = MethodMeta(
            name=method_name,
            handler_name=method.__name__,
            request_schema=request_schema_resolved,
            response_schema=response_schema_resolved,
            pagination_class=pagination_class,
            ordering_handler=ordering_handler,
            searching_handler=searching_handler,
            description=resolved_description,
            client_streaming=client_streaming,
            server_streaming=server_streaming,
            permissions=(
                resolve_permissions(permissions_meta) + resolve_permissions(permissions)
            ),
            permissions_overridden=permissions_overridden,
        )
        setattr(method, GRPC_METHOD_META, meta)
        return method

    return decorator


def _resolve_top_level_collection_schema(
    schema: Type[BaseModel] | None | Any,
    *,
    direction: str,
) -> Type[BaseModel] | None:
    if schema is None:
        return None
    origin = get_origin(schema)
    args = get_args(schema)
    if origin is not list:
        return schema
    if len(args) != 1:
        raise ValueError("List[T] schema must define exactly one item type.")
    item_schema = args[0]
    if not isinstance(item_schema, type) or not issubclass(item_schema, BaseModel):
        raise ValueError("List[T] schema requires T to be a Pydantic model.")
    wrapper_name = f"{item_schema.__name__}List{direction.title()}Schema"
    item_list_type = list[item_schema]  # type: ignore[valid-type]
    return create_model(wrapper_name, items=(item_list_type, ...))


def grpc_pagination(
    pagination_class: Callable | type[BasePagination] | str | None = None,
) -> Callable[[Callable], Callable] | Callable:
    """Attach pagination behavior to a grpc method.

    This decorator must be placed under `@grpc_method`.
    """

    def decorator(method: Callable) -> Callable:
        if getattr(method, GRPC_METHOD_META, None) is not None:
            raise ValueError("grpc_pagination must be placed under @grpc_method.")
        resolved = (
            get_default_pagination_class()
            if pagination_class is None
            else resolve_pagination_class(pagination_class)
        )
        setattr(method, GRPC_PAGINATION_META, resolved)
        return method

    if callable(pagination_class) and not inspect.isclass(pagination_class):
        method = pagination_class
        pagination_class = None
        return decorator(method)
    return decorator


def grpc_ordering(
    ordering_class: Callable | type[BaseOrdering] | str | None = None,
    **ordering_params: Any,
) -> Callable[[Callable], Callable] | Callable:
    """Attach ordering behavior to a grpc method."""

    def decorator(method: Callable) -> Callable:
        if getattr(method, GRPC_METHOD_META, None) is not None:
            raise ValueError("grpc_ordering must be placed under @grpc_method.")
        resolved = (
            get_default_ordering_class()
            if ordering_class is None
            else resolve_ordering_class(ordering_class)
        )
        if resolved is None:
            raise ValueError("Ordering class cannot be None.")
        params = _resolve_modifier_fields_params(
            ordering_params,
            resolved=resolved,
            legacy_fields_key="ordering_fields",
            decorator_name="grpc_ordering",
        )
        setattr(method, GRPC_ORDERING_META, (resolved, params))
        return method

    if callable(ordering_class) and not inspect.isclass(ordering_class):
        method = ordering_class
        ordering_class = None
        return decorator(method)
    return decorator


def grpc_searching(
    searching_class: Callable | type[BaseSearching] | str | None = None,
    **searching_params: Any,
) -> Callable[[Callable], Callable] | Callable:
    """Attach searching behavior to a grpc method."""

    def decorator(method: Callable) -> Callable:
        if getattr(method, GRPC_METHOD_META, None) is not None:
            raise ValueError("grpc_searching must be placed under @grpc_method.")
        resolved = (
            get_default_searching_class()
            if searching_class is None
            else resolve_searching_class(searching_class)
        )
        if resolved is None:
            raise ValueError("Searching class cannot be None.")
        params = _resolve_modifier_fields_params(
            searching_params,
            resolved=resolved,
            legacy_fields_key="search_fields",
            decorator_name="grpc_searching",
        )
        setattr(method, GRPC_SEARCHING_META, (resolved, params))
        return method

    if callable(searching_class) and not inspect.isclass(searching_class):
        method = searching_class
        searching_class = None
        return decorator(method)
    return decorator


def _has_explicit_fields(value: Any) -> bool:
    if value is None:
        return False
    if isinstance(value, str):
        return bool(value.strip())
    if isinstance(value, Iterable):
        return any(True for _ in value)
    return False


def _resolve_modifier_fields_params(
    raw_params: dict[str, Any],
    *,
    resolved: type[BaseOrdering] | type[BaseSearching],
    legacy_fields_key: str,
    decorator_name: str,
) -> dict[str, Any]:
    params = dict(raw_params)
    fields_param_name = getattr(resolved, "fields_param_name", legacy_fields_key)
    fields_required = bool(getattr(resolved, "fields_required", True))

    alias_keys = {"fields", legacy_fields_key, fields_param_name}
    present_alias_keys = [key for key in alias_keys if key in params]
    if len(present_alias_keys) > 1:
        raise ValueError(
            f"{decorator_name} received multiple field parameter aliases: "
            f"{', '.join(sorted(present_alias_keys))}. "
            "Use only one of them."
        )

    fields_value = None
    if "fields" in params:
        fields_value = params.pop("fields")
    elif legacy_fields_key in params and legacy_fields_key != fields_param_name:
        fields_value = params.pop(legacy_fields_key)
    elif fields_param_name in params:
        fields_value = params[fields_param_name]
    elif legacy_fields_key in params:
        fields_value = params[legacy_fields_key]

    if fields_required and not _has_explicit_fields(fields_value):
        raise ValueError(
            f"{decorator_name} requires fields for {resolved.__name__} "
            f"(expected parameter: '{fields_param_name}')."
        )

    if fields_value is not None and fields_param_name not in params:
        params[fields_param_name] = fields_value

    return params


def grpc_permissions(*permissions: PermissionLike) -> Callable[[Callable], Callable]:
    """Attach permission classes to a grpc method."""

    def decorator(method: Callable) -> Callable:
        if getattr(method, GRPC_METHOD_META, None) is not None:
            raise ValueError("grpc_permissions must be placed under @grpc_method.")
        current = tuple(getattr(method, GRPC_PERMISSIONS_META, ()))
        setattr(method, GRPC_PERMISSIONS_META, current + tuple(permissions))
        return method

    return decorator
