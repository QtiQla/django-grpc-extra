from __future__ import annotations

import importlib
import logging
import os
from typing import Iterable

import django
from django.apps import apps

from .adapters import ServiceRuntimeAdapter
from .auth import AuthInterceptor, resolve_auth_backend
from .constants import GRPC_SERVICE_META
from .registry import ServiceDefinition, ServiceNotDecoratedError, registry
from .request_logging import GrpcRequestLoggingInterceptor
from .settings import get_grpc_extra_settings
from .utils import pb2_grpc_module_path, pb2_module_path

logger = logging.getLogger("grpc_extra")


def _run_reloaded_server(pattern: str, kwargs: dict) -> None:
    _ensure_django_ready()
    GrpcExtra(pattern=pattern).run_server(reload=False, **kwargs)


def _ensure_django_ready() -> None:
    if apps.ready:
        return
    if not os.environ.get("DJANGO_SETTINGS_MODULE"):
        raise ServiceNotDecoratedError(
            "DJANGO_SETTINGS_MODULE is not set in reload process."
        )
    django.setup()


class GrpcExtra:
    """Entry point for gRPC runtime integration in a Django project.

    `GrpcExtra` is responsible for the full service lifecycle at runtime:

    1. Discover decorated services from Django apps (`auto_discover_services`).
    2. Load generated protobuf modules for each discovered service.
    3. Adapt business methods to gRPC handlers (request/response conversion,
       streaming wrappers, exception mapping).
    4. Register servicers on a gRPC server (`apply`) and optionally run the
       server loop (`run_server`).

    The class expects services to be declared with `@grpc_service` and methods
    with `@grpc_method`. Proto and pb2 modules are resolved using service
    metadata (`app_label`, `proto_path`, `name`) collected by decorators.
    """

    def __init__(self, pattern: str = "{app}.grpc.services") -> None:
        self.pattern = pattern

    def register_service(self, service: type) -> ServiceDefinition:
        return registry.register(service)

    def auto_discover_services(self) -> "GrpcExtra":
        logger.debug("grpc service autodiscovery started pattern=%s", self.pattern)
        for app_conf in apps.get_app_configs():
            module_path = self.pattern.format(
                app=app_conf.name,
                label=app_conf.label,
            )
            module = self._safe_import(module_path)
            if module is None:
                continue
            for obj in self._iter_decorated_services(module):
                self.register_service(obj)
                logger.debug(
                    "grpc service discovered app=%s service=%s",
                    app_conf.label,
                    getattr(obj, "__name__", "<unknown>"),
                )

        logger.debug("grpc service autodiscovery completed")
        return self

    def apply(self, server) -> list[str]:
        """Register all discovered services on the provided gRPC server."""
        registered: list[str] = []
        settings = get_grpc_extra_settings()
        logger.debug("grpc service apply started")
        for definition in registry.all():
            meta = definition.meta
            if not meta.proto_path:
                raise ServiceNotDecoratedError(
                    f"Service '{meta.name}' must define proto_path."
                )
            pb2_grpc_path = pb2_grpc_module_path(meta.app_label, meta.proto_path)
            pb2_path = pb2_module_path(meta.app_label, meta.proto_path)
            try:
                pb2_grpc = importlib.import_module(pb2_grpc_path)
                pb2 = importlib.import_module(pb2_path)
            except ModuleNotFoundError as exc:
                raise ServiceNotDecoratedError(
                    "pb2_grpc module not found. "
                    f"Expected '{pb2_grpc_path}'. "
                    "Generate proto files before starting the server."
                ) from exc

            add_name = f"add_{meta.name}Servicer_to_server"
            add_servicer = getattr(pb2_grpc, add_name, None)
            if not callable(add_servicer):
                raise ServiceNotDecoratedError(
                    f"Servicer registration function '{add_name}' not found "
                    f"in '{pb2_grpc_path}'."
                )

            factory = meta.factory or definition.service
            servicer = factory()
            ServiceRuntimeAdapter(
                definition,
                pb2,
                exception_mapper=settings.exception_mapper,
            ).apply(servicer)
            add_servicer(servicer, server)
            registered.append(definition.meta.name)
            logger.info("grpc service registered service=%s", definition.meta.name)
        logger.debug("grpc service apply completed count=%s", len(registered))
        return registered

    def run_server(
        self,
        *,
        bind: str | None = None,
        max_workers: int | None = None,
        max_msg_mb: int | None = None,
        enable_health: bool | None = None,
        enable_reflection: bool | None = None,
        auth_backend=None,
        interceptors: Iterable[object] | None = None,
        reload: bool | None = None,
        reload_paths: Iterable[str] | None = None,
        auto_discover: bool = True,
    ) -> None:
        """Start gRPC server and optionally restart process on file changes."""
        from concurrent import futures

        import grpc

        settings = get_grpc_extra_settings()
        bind = bind or settings.bind
        max_workers = max_workers or settings.max_workers
        max_msg_mb = max_msg_mb or settings.max_msg_mb
        enable_health = (
            settings.enable_health if enable_health is None else enable_health
        )
        enable_reflection = (
            settings.enable_reflection
            if enable_reflection is None
            else enable_reflection
        )
        reload = settings.enable_reload if reload is None else reload
        reload_paths = (
            tuple(settings.reload_paths)
            if reload_paths is None
            else tuple(reload_paths)
        )
        auth_backend = settings.auth_backend if auth_backend is None else auth_backend
        interceptors = (
            list(settings.interceptors) if interceptors is None else list(interceptors)
        )
        logger_name = settings.logger_name

        if reload:
            if interceptors:
                raise ServiceNotDecoratedError(
                    "Live reload mode does not support runtime interceptor objects. "
                    "Configure importable interceptors in Django settings."
                )
            self._run_with_reload(
                bind=bind,
                max_workers=max_workers,
                max_msg_mb=max_msg_mb,
                enable_health=enable_health,
                enable_reflection=enable_reflection,
                auth_backend=auth_backend,
                reload_paths=reload_paths,
                auto_discover=auto_discover,
            )
            return

        if auto_discover:
            self.auto_discover_services()

        options = [
            ("grpc.max_send_message_length", max_msg_mb * 1024 * 1024),
            ("grpc.max_receive_message_length", max_msg_mb * 1024 * 1024),
        ]

        resolved_backend = resolve_auth_backend(auth_backend)
        if resolved_backend is not None:
            interceptors.append(AuthInterceptor(resolved_backend))
            logger.debug("grpc auth interceptor enabled")
        if settings.enable_request_logging:
            interceptors.append(GrpcRequestLoggingInterceptor(logger_name=logger_name))
            logger.debug(
                "grpc request logging interceptor enabled logger=%s", logger_name
            )

        server = grpc.server(
            futures.ThreadPoolExecutor(max_workers=max_workers),
            options=options,
            interceptors=interceptors,
        )
        self.apply(server)

        service_names = [
            self._qualified_service_name(definition) for definition in registry.all()
        ]
        if enable_health:
            self._add_health(server)
        if enable_reflection:
            self._add_reflection(server, service_names, enable_health=enable_health)

        server.add_insecure_port(bind)
        server.start()
        logger.info("grpc server started bind=%s", bind)
        try:
            server.wait_for_termination()
        except KeyboardInterrupt:
            # Reload workers are stopped via signal; avoid noisy tracebacks.
            logger.debug("grpc server termination requested")
            server.stop(grace=0)

    def _run_with_reload(
        self,
        *,
        bind: str,
        max_workers: int,
        max_msg_mb: int,
        enable_health: bool,
        enable_reflection: bool,
        auth_backend,
        reload_paths: tuple[str, ...],
        auto_discover: bool,
    ) -> None:
        try:
            from watchfiles import run_process
        except ImportError as exc:
            raise ServiceNotDecoratedError(
                "watchfiles is required for live reload mode. "
                "Install `django-grpc-extra[reload]`."
            ) from exc

        kwargs = {
            "bind": bind,
            "max_workers": max_workers,
            "max_msg_mb": max_msg_mb,
            "enable_health": enable_health,
            "enable_reflection": enable_reflection,
            "auth_backend": auth_backend,
            "auto_discover": auto_discover,
        }
        run_process(
            *reload_paths,
            target=_run_reloaded_server,
            args=(self.pattern, kwargs),
        )

    @staticmethod
    def _add_health(server) -> None:
        try:
            from grpc_health.v1 import health, health_pb2_grpc
        except ImportError as exc:
            raise ServiceNotDecoratedError(
                "grpcio-health is required for health checks."
            ) from exc
        health_servicer = health.HealthServicer()
        health_pb2_grpc.add_HealthServicer_to_server(health_servicer, server)

    @staticmethod
    def _add_reflection(
        server, service_names: Iterable[str], *, enable_health: bool
    ) -> None:
        try:
            from grpc_reflection.v1alpha import reflection
        except ImportError as exc:
            raise ServiceNotDecoratedError(
                "grpcio-reflection is required for reflection."
            ) from exc
        names = list(service_names)
        if enable_health:
            names.append("grpc.health.v1.Health")
        names.append(reflection.SERVICE_NAME)
        reflection.enable_server_reflection(names, server)

    @staticmethod
    def _qualified_service_name(definition: ServiceDefinition) -> str:
        package = definition.meta.package
        if package:
            return f"{package}.{definition.meta.name}"
        return definition.meta.name

    @staticmethod
    def _safe_import(module_path: str):
        try:
            return importlib.import_module(module_path)
        except ModuleNotFoundError as exc:
            if exc.name and module_path.startswith(exc.name):
                return None
            if exc.name == module_path:
                return None
            raise

    @staticmethod
    def _iter_decorated_services(module) -> Iterable[type]:
        for attr_name in dir(module):
            obj = getattr(module, attr_name)
            if getattr(obj, GRPC_SERVICE_META, None) is not None:
                yield obj
