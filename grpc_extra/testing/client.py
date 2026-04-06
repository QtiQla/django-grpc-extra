from __future__ import annotations

import importlib
from typing import Any, Callable, cast

import grpc

from ..adapters import ServiceRuntimeAdapter
from ..exceptions import resolve_exception_mapper
from ..registry import MethodMeta, ServiceDefinition, registry
from ..utils import pb2_module_path
from .context import AbortedRpcError, TestServicerContext
from .response import GrpcTestResponse


class GrpcTestClient:
    """In-process unary-unary client for integration-style service tests."""

    def __init__(
        self,
        *,
        exception_mapper: Callable | str | None = None,
        auth_backend: Callable | None = None,
    ) -> None:
        self.exception_mapper = resolve_exception_mapper(exception_mapper)
        self.auth_backend = auth_backend

    def call(
        self,
        service: type | object | ServiceDefinition,
        method: str,
        request: Any = None,
        *,
        metadata: list[tuple[str, str]] | tuple[tuple[str, str], ...] | None = None,
        context: TestServicerContext | None = None,
        pb2_module: Any | None = None,
        auth_backend: Callable | None = None,
    ) -> GrpcTestResponse:
        definition, service_instance = self._resolve_service(service)
        method_meta = self._resolve_method(definition, method)
        if method_meta.client_streaming or method_meta.server_streaming:
            raise NotImplementedError(
                "GrpcTestClient MVP supports only unary-unary methods."
            )

        resolved_pb2 = pb2_module or self._load_pb2_module(definition)
        response_cls = self._response_pb2_cls(definition, method_meta, resolved_pb2)
        adapter = ServiceRuntimeAdapter(
            definition,
            resolved_pb2,
            exception_mapper=self.exception_mapper,
        )
        wrapper = adapter._build_wrapper(service_instance, method_meta, response_cls)
        if wrapper is None:
            raise ValueError(
                f"Unable to build wrapper for method '{method_meta.name}' on '{definition.meta.name}'."
            )

        ctx = context or TestServicerContext(metadata=metadata)
        backend = auth_backend or self.auth_backend
        method_path = self._method_path(definition, method_meta)

        try:
            if backend is not None:
                auth_result = backend(ctx, method_path, request)
                if auth_result is False or auth_result is None:
                    ctx.abort(grpc.StatusCode.UNAUTHENTICATED, "Unauthorized")
            message = wrapper(request, ctx)
        except AbortedRpcError:
            return GrpcTestResponse(
                message=None,
                code=ctx.code(),
                details=ctx.details(),
                initial_metadata=ctx.initial_metadata(),
                trailing_metadata=ctx.trailing_metadata(),
            )

        return GrpcTestResponse(
            message=message,
            code=ctx.code(),
            details=ctx.details(),
            initial_metadata=ctx.initial_metadata(),
            trailing_metadata=ctx.trailing_metadata(),
        )

    def _resolve_service(
        self, service: type | object | ServiceDefinition
    ) -> tuple[ServiceDefinition, object]:
        if isinstance(service, ServiceDefinition):
            definition = service
            factory = definition.meta.factory or definition.service
            return definition, factory()
        if isinstance(service, type):
            definition = registry.register(service)
            factory = definition.meta.factory or definition.service
            return definition, factory()
        definition = registry.register(type(service))
        return definition, service

    def _resolve_method(
        self,
        definition: ServiceDefinition,
        method: str,
    ) -> MethodMeta:
        lowered = method.lower()
        for method_meta in definition.methods:
            if (
                method_meta.name == method
                or method_meta.handler_name == method
                or method_meta.name.lower() == lowered
                or method_meta.handler_name.lower() == lowered
            ):
                return method_meta
        raise ValueError(
            f"Method '{method}' is not registered on service '{definition.meta.name}'."
        )

    def _load_pb2_module(self, definition: ServiceDefinition):
        proto_path = definition.meta.proto_path
        if not proto_path:
            raise ValueError(
                f"Service '{definition.meta.name}' does not define proto_path."
            )
        module_path = pb2_module_path(definition.meta.app_label, proto_path)
        return importlib.import_module(module_path)

    def _response_pb2_cls(
        self,
        definition: ServiceDefinition,
        method_meta: MethodMeta,
        pb2_module: Any,
    ) -> type:
        service_desc = pb2_module.DESCRIPTOR.services_by_name.get(definition.meta.name)
        if service_desc is None:
            raise ValueError(
                f"Service '{definition.meta.name}' not found in pb2 module '{pb2_module.__name__}'."
            )
        method_desc = service_desc.methods_by_name.get(method_meta.name)
        if method_desc is None:
            raise ValueError(
                f"Method '{method_meta.name}' not found in service '{definition.meta.name}'."
            )
        response_name = method_desc.output_type.name
        response_cls = getattr(pb2_module, response_name, None)
        if response_cls is None:
            raise ValueError(
                f"Response message '{response_name}' not found in pb2 module '{pb2_module.__name__}'."
            )
        return cast(type, response_cls)

    def _method_path(
        self, definition: ServiceDefinition, method_meta: MethodMeta
    ) -> str:
        package = definition.meta.package or definition.meta.app_label
        if package:
            return f"/{package}.{definition.meta.name}/{method_meta.name}"
        return f"/{definition.meta.name}/{method_meta.name}"
