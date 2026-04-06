from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Callable, Iterable

from .constants import GRPC_METHOD_META, GRPC_SERVICE_META

if TYPE_CHECKING:
    from pydantic import BaseModel

    from .ordering import BaseOrdering
    from .pagination import BasePagination
    from .permissions import BasePermission
    from .searching import BaseSearching


class RegistryError(Exception):
    pass


class ServiceNotDecoratedError(RegistryError):
    pass


@dataclass(frozen=True)
class ServiceMeta:
    name: str
    app_label: str
    package: str | None = None
    proto_path: str | None = None
    description: str | None = None
    factory: Callable[[], object] | None = None
    permissions: tuple["BasePermission", ...] = ()


@dataclass(frozen=True)
class MethodMeta:
    name: str
    handler_name: str
    request_schema: type["BaseModel"] | None = None
    response_schema: type["BaseModel"] | None = None
    pagination_class: type["BasePagination"] | None = None
    ordering_handler: "BaseOrdering | None" = None
    searching_handler: "BaseSearching | None" = None
    description: str | None = None
    client_streaming: bool = False
    server_streaming: bool = False
    permissions: tuple["BasePermission", ...] = ()
    permissions_overridden: bool = False


@dataclass
class ServiceDefinition:
    service: type
    meta: ServiceMeta
    methods: list[MethodMeta] = field(default_factory=list)


class ServiceRegistry:
    def __init__(self) -> None:
        self._services: list[ServiceDefinition] = []

    def register(self, service: type) -> ServiceDefinition:
        meta: ServiceMeta | None = getattr(service, GRPC_SERVICE_META, None)
        if meta is None:
            raise ServiceNotDecoratedError(
                f"Service '{service.__name__}' must be decorated with @grpc_service."
            )

        existing = self._find(service)
        if existing is not None:
            return existing

        methods = self._collect_methods(service)
        definition = ServiceDefinition(service=service, meta=meta, methods=methods)
        self._services.append(definition)
        return definition

    def all(self) -> Iterable[ServiceDefinition]:
        return list(self._services)

    def clear(self) -> None:
        self._services.clear()

    def _find(self, service: type) -> ServiceDefinition | None:
        for definition in self._services:
            if definition.service is service:
                return definition
        return None

    def _collect_methods(self, service: type) -> list[MethodMeta]:
        collected: list[MethodMeta] = []
        for attr_name in dir(service):
            attr = getattr(service, attr_name)
            meta = getattr(attr, GRPC_METHOD_META, None)
            if meta is not None:
                collected.append(meta)
        return collected


registry = ServiceRegistry()
