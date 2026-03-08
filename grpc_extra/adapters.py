from __future__ import annotations

from collections.abc import Callable, Iterable, Iterator, Mapping
from typing import Any, NoReturn

from .codec import (
    decode_request_iter,
    decode_request_value,
    encode_response_value,
)
from .exceptions import MappedError, resolve_exception_mapper
from .permissions import BasePermission
from .registry import MethodMeta, ServiceDefinition


class ServiceRuntimeAdapter:
    """Adapts business methods to grpc-compatible handlers."""

    def __init__(
        self,
        definition: ServiceDefinition,
        pb2_module,
        *,
        exception_mapper: Callable[[Exception], MappedError] | str | None = None,
    ) -> None:
        self.definition = definition
        self.pb2_module = pb2_module
        self.exception_mapper = resolve_exception_mapper(exception_mapper)

    def apply(self, servicer: object) -> None:
        service_desc = self.pb2_module.DESCRIPTOR.services_by_name.get(
            self.definition.meta.name
        )
        if service_desc is None:
            return

        for method_meta in self.definition.methods:
            method_desc = service_desc.methods_by_name.get(method_meta.name)
            if method_desc is None:
                continue
            response_cls = getattr(self.pb2_module, method_desc.output_type.name, None)
            if response_cls is None:
                continue
            wrapper = self._build_wrapper(servicer, method_meta, response_cls)
            if wrapper is None:
                continue
            setattr(servicer, method_meta.name, wrapper)

    def _build_wrapper(
        self,
        servicer: object,
        method_meta: MethodMeta,
        response_pb2_cls: type,
    ) -> Callable | None:
        method = getattr(servicer, method_meta.handler_name, None)
        if method is None:
            return None
        if method_meta.client_streaming and method_meta.server_streaming:
            return self._wrap_stream_stream(
                method, method_meta, response_pb2_cls, servicer
            )
        if method_meta.client_streaming:
            return self._wrap_stream_unary(
                method, method_meta, response_pb2_cls, servicer
            )
        if method_meta.server_streaming:
            return self._wrap_unary_stream(
                method, method_meta, response_pb2_cls, servicer
            )
        return self._wrap_unary_unary(method, method_meta, response_pb2_cls, servicer)

    def _wrap_unary_unary(
        self,
        method: Callable,
        method_meta: MethodMeta,
        response_pb2_cls: type,
        service: object | None = None,
    ) -> Callable:
        def wrapper(request, context):
            try:
                decoded = decode_request_value(request, method_meta.request_schema)
                self._check_service_permissions(decoded, context, method_meta, service)
                self._check_method_permissions(decoded, context, method_meta, service)
                result = method(decoded, context)
                self._check_obj_permissions(
                    decoded, context, method_meta, service, result
                )
                result = self._apply_searching_ordering(result, decoded, method_meta)
                if method_meta.pagination_class is not None:
                    result = method_meta.pagination_class.paginate(result, decoded)
                return encode_response_value(
                    result, method_meta.response_schema, response_pb2_cls
                )
            except Exception as exc:
                self._abort(context, exc)

        return wrapper

    def _wrap_unary_stream(
        self,
        method: Callable,
        method_meta: MethodMeta,
        response_pb2_cls: type,
        service: object | None = None,
    ) -> Callable:
        def wrapper(request, context) -> Iterator[Any]:
            try:
                decoded = decode_request_value(request, method_meta.request_schema)
                self._check_service_permissions(decoded, context, method_meta, service)
                self._check_method_permissions(decoded, context, method_meta, service)
                result = method(decoded, context)
                result = self._apply_searching_ordering(result, decoded, method_meta)
                if not isinstance(result, Iterable):
                    raise TypeError(
                        f"Method '{method_meta.name}' must return iterable for server streaming."
                    )
                return self._encode_stream(
                    result,
                    method_meta,
                    response_pb2_cls,
                    context,
                    decoded,
                    service,
                )
            except Exception as exc:
                self._abort(context, exc)

        return wrapper

    def _wrap_stream_unary(
        self,
        method: Callable,
        method_meta: MethodMeta,
        response_pb2_cls: type,
        service: object | None = None,
    ) -> Callable:
        def wrapper(request_iterator, context):
            try:
                self._check_service_permissions(None, context, method_meta, service)
                self._check_method_permissions(None, context, method_meta, service)
                decoded_iter = decode_request_iter(
                    request_iterator, method_meta.request_schema
                )
                result = method(decoded_iter, context)
                self._check_obj_permissions(None, context, method_meta, service, result)
                if method_meta.pagination_class is not None:
                    raise TypeError(
                        "Pagination is not supported for stream-unary methods."
                    )
                return encode_response_value(
                    result, method_meta.response_schema, response_pb2_cls
                )
            except Exception as exc:
                self._abort(context, exc)

        return wrapper

    def _wrap_stream_stream(
        self,
        method: Callable,
        method_meta: MethodMeta,
        response_pb2_cls: type,
        service: object | None = None,
    ) -> Callable:
        def wrapper(request_iterator, context) -> Iterator[Any]:
            try:
                self._check_service_permissions(None, context, method_meta, service)
                self._check_method_permissions(None, context, method_meta, service)
                decoded_iter = decode_request_iter(
                    request_iterator, method_meta.request_schema
                )
                result = method(decoded_iter, context)
                if not isinstance(result, Iterable):
                    raise TypeError(
                        f"Method '{method_meta.name}' must return iterable for bidirectional streaming."
                    )
                return self._encode_stream(
                    result,
                    method_meta,
                    response_pb2_cls,
                    context,
                    None,
                    service,
                )
            except Exception as exc:
                self._abort(context, exc)

        return wrapper

    def _encode_stream(
        self,
        result: Iterable[Any],
        method_meta: MethodMeta,
        response_pb2_cls: type,
        context,
        request=None,
        service: object | None = None,
    ) -> Iterator[Any]:
        try:
            for raw_item in result:
                self._check_obj_permissions(
                    request, context, method_meta, service, raw_item
                )
                item = encode_response_value(
                    raw_item, method_meta.response_schema, response_pb2_cls
                )
                yield item
        except Exception as exc:
            self._abort(context, exc)

    def _check_service_permissions(
        self,
        request,
        context,
        method_meta: MethodMeta,
        service: object | None,
    ) -> None:
        permissions = self.definition.meta.permissions
        if not permissions:
            return
        target = service or self.definition.service
        self._run_has_perm(permissions, request, context, target, method_meta)

    def _check_method_permissions(
        self,
        request,
        context,
        method_meta: MethodMeta,
        service: object | None,
    ) -> None:
        permissions = method_meta.permissions
        if not permissions:
            return
        target = service or self.definition.service
        self._run_has_perm(permissions, request, context, target, method_meta)

    def _check_obj_permissions(
        self,
        request,
        context,
        method_meta: MethodMeta,
        service: object | None,
        obj: Any,
    ) -> None:
        target = service or self.definition.service
        method_permissions = method_meta.permissions
        if method_permissions:
            self._run_has_obj_perm(
                method_permissions, request, context, target, method_meta, obj
            )
        if self._is_detail_method(method_meta):
            service_permissions = self.definition.meta.permissions
            if service_permissions:
                self._run_has_obj_perm(
                    service_permissions, request, context, target, method_meta, obj
                )

    def _run_has_perm(
        self,
        permissions: tuple[BasePermission, ...],
        request,
        context,
        service: object,
        method_meta: MethodMeta,
    ) -> None:
        for permission in permissions:
            if not permission.has_perm(request, context, service, method_meta):
                raise PermissionError(
                    getattr(permission, "message", "Permission denied.")
                )

    def _run_has_obj_perm(
        self,
        permissions: tuple[BasePermission, ...],
        request,
        context,
        service: object,
        method_meta: MethodMeta,
        obj: Any,
    ) -> None:
        for permission in permissions:
            if not permission.has_obj_perm(request, context, service, method_meta, obj):
                raise PermissionError(
                    getattr(permission, "message", "Permission denied.")
                )

    def _apply_searching_ordering(self, result, decoded, method_meta: MethodMeta):
        searching_handler = method_meta.searching_handler
        if searching_handler is not None:
            result = self._apply_modifier_to_items(
                result,
                lambda items: searching_handler.search(items, decoded),
            )
        ordering_handler = method_meta.ordering_handler
        if ordering_handler is not None:
            result = self._apply_modifier_to_items(
                result,
                lambda items: ordering_handler.order(items, decoded),
            )
        return result

    def _apply_modifier_to_items(self, result, modifier: Callable[[Any], Any]):
        if isinstance(result, Mapping) and "items" in result:
            payload = dict(result)
            payload["items"] = modifier(payload["items"])
            return payload
        return modifier(result)

    def _is_detail_method(self, method_meta: MethodMeta) -> bool:
        method_name = method_meta.name.replace("-", "_").upper()
        if method_name in {"DETAIL", "GET"}:
            return True
        handler_name = method_meta.handler_name.replace("-", "_").upper()
        return handler_name in {"DETAIL", "GET"}

    def _abort(self, context, exc: Exception) -> NoReturn:
        mapped = self.exception_mapper(exc)
        context.abort(mapped.code, mapped.message)
        raise RuntimeError("gRPC context.abort returned unexpectedly")
