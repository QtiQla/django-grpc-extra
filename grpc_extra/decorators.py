from __future__ import annotations

from collections.abc import Callable
from typing import Any, Type

from pydantic import BaseModel

from .constants import (
    GRPC_METHOD_META,
    GRPC_ORDERING_META,
    GRPC_PAGINATION_META,
    GRPC_SEARCHING_META,
    GRPC_SERVICE_META,
)
from .ordering import BaseOrdering, get_default_ordering_class, resolve_ordering_class
from .pagination import (
    BasePagination,
    get_default_pagination_class,
    resolve_pagination_class,
)
from .searching import (
    BaseSearching,
    get_default_searching_class,
    resolve_searching_class,
)
from .registry import MethodMeta, ServiceMeta, registry
from .utils import to_upper_camel_case


def grpc_service(
    *,
    name: str | None = None,
    app_label: str | None = None,
    package: str | None = None,
    proto_path: str | None = None,
    description: str | None = None,
    factory: Callable[[], object] | None = None,
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
        meta = ServiceMeta(
            name=service_name,
            app_label=resolved_app_label,
            package=resolved_package,
            proto_path=resolved_proto_path,
            description=description,
            factory=factory,
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
        searching_meta = getattr(method, GRPC_SEARCHING_META, None)
        ordering_meta = getattr(method, GRPC_ORDERING_META, None)
        pagination_class = getattr(method, GRPC_PAGINATION_META, None)
        request_schema_resolved = request_schema
        response_schema_resolved = response_schema
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
            description=description,
            client_streaming=client_streaming,
            server_streaming=server_streaming,
        )
        setattr(method, GRPC_METHOD_META, meta)
        return method

    return decorator


def grpc_pagination(
    pagination_class: type[BasePagination] | str | None = None,
) -> Callable[[Callable], Callable]:
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

    return decorator


def grpc_ordering(
    ordering_class: type[BaseOrdering] | str | None = None,
    **ordering_params: Any,
) -> Callable[[Callable], Callable]:
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
        setattr(method, GRPC_ORDERING_META, (resolved, dict(ordering_params)))
        return method

    return decorator


def grpc_searching(
    searching_class: type[BaseSearching] | str | None = None,
    **searching_params: Any,
) -> Callable[[Callable], Callable]:
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
        setattr(method, GRPC_SEARCHING_META, (resolved, dict(searching_params)))
        return method

    return decorator
