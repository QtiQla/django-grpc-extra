from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable, Iterable

from django.conf import settings as django_settings

from .exceptions import MappedError


@dataclass(frozen=True)
class GrpcExtraSettings:
    bind: str = "[::]:50051"
    max_workers: int = 10
    max_msg_mb: int = 32
    enable_health: bool = True
    enable_reflection: bool = False
    auth_backend: str | Callable | None = None
    interceptors: Iterable[object] = field(default_factory=list)
    exception_mapper: Callable[[Exception], MappedError] | None = None
    enable_request_logging: bool = True
    logger_name: str = "grpc_extra"
    default_pagination_class: object | None = (
        "grpc_extra.pagination.LimitOffsetPagination"
    )
    enable_reload: bool = False
    reload_paths: Iterable[str] = field(default_factory=lambda: (".",))


def get_grpc_extra_settings() -> GrpcExtraSettings:
    configured = getattr(django_settings, "GRPC_EXTRA", {}) or {}
    return GrpcExtraSettings(
        bind=configured.get("BIND", GrpcExtraSettings.bind),
        max_workers=configured.get("MAX_WORKERS", GrpcExtraSettings.max_workers),
        max_msg_mb=configured.get("MAX_MSG_MB", GrpcExtraSettings.max_msg_mb),
        enable_health=configured.get("ENABLE_HEALTH", GrpcExtraSettings.enable_health),
        enable_reflection=configured.get(
            "ENABLE_REFLECTION", GrpcExtraSettings.enable_reflection
        ),
        auth_backend=configured.get("AUTH_BACKEND", GrpcExtraSettings.auth_backend),
        interceptors=configured.get("INTERCEPTORS", ()),
        exception_mapper=configured.get("EXCEPTION_MAPPER"),
        enable_request_logging=configured.get(
            "ENABLE_REQUEST_LOGGING", GrpcExtraSettings.enable_request_logging
        ),
        logger_name=configured.get("LOGGER_NAME", GrpcExtraSettings.logger_name),
        default_pagination_class=configured.get(
            "DEFAULT_PAGINATION_CLASS", GrpcExtraSettings.default_pagination_class
        ),
        enable_reload=configured.get("ENABLE_RELOAD", GrpcExtraSettings.enable_reload),
        reload_paths=configured.get("RELOAD_PATHS", (".",)),
    )
