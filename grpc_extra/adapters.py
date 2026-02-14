from __future__ import annotations

from collections.abc import Callable, Iterable, Iterator
from typing import Any, NoReturn

from .codec import (
    decode_request_iter,
    decode_request_value,
    encode_response_iter,
    encode_response_value,
)
from .exceptions import MappedError, resolve_exception_mapper
from .registry import MethodMeta, ServiceDefinition


class ServiceRuntimeAdapter:
    """Adapts business methods to grpc-compatible handlers."""

    def __init__(
        self,
        definition: ServiceDefinition,
        pb2_module,
        *,
        exception_mapper: Callable[[Exception], MappedError] | None = None,
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
            return self._wrap_stream_stream(method, method_meta, response_pb2_cls)
        if method_meta.client_streaming:
            return self._wrap_stream_unary(method, method_meta, response_pb2_cls)
        if method_meta.server_streaming:
            return self._wrap_unary_stream(method, method_meta, response_pb2_cls)
        return self._wrap_unary_unary(method, method_meta, response_pb2_cls)

    def _wrap_unary_unary(
        self,
        method: Callable,
        method_meta: MethodMeta,
        response_pb2_cls: type,
    ) -> Callable:
        def wrapper(request, context):
            try:
                decoded = decode_request_value(request, method_meta.request_schema)
                result = method(decoded, context)
                if method_meta.searching_handler is not None:
                    result = method_meta.searching_handler.search(result, decoded)
                if method_meta.ordering_handler is not None:
                    result = method_meta.ordering_handler.order(result, decoded)
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
    ) -> Callable:
        def wrapper(request, context) -> Iterator[Any]:
            try:
                decoded = decode_request_value(request, method_meta.request_schema)
                result = method(decoded, context)
                if method_meta.searching_handler is not None:
                    result = method_meta.searching_handler.search(result, decoded)
                if method_meta.ordering_handler is not None:
                    result = method_meta.ordering_handler.order(result, decoded)
                if not isinstance(result, Iterable):
                    raise TypeError(
                        f"Method '{method_meta.name}' must return iterable for server streaming."
                    )
                return self._encode_stream(
                    result,
                    method_meta,
                    response_pb2_cls,
                    context,
                )
            except Exception as exc:
                self._abort(context, exc)

        return wrapper

    def _wrap_stream_unary(
        self,
        method: Callable,
        method_meta: MethodMeta,
        response_pb2_cls: type,
    ) -> Callable:
        def wrapper(request_iterator, context):
            try:
                decoded_iter = decode_request_iter(
                    request_iterator, method_meta.request_schema
                )
                result = method(decoded_iter, context)
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
    ) -> Callable:
        def wrapper(request_iterator, context) -> Iterator[Any]:
            try:
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
    ) -> Iterator[Any]:
        try:
            for item in encode_response_iter(
                result, method_meta.response_schema, response_pb2_cls
            ):
                yield item
        except Exception as exc:
            self._abort(context, exc)

    def _abort(self, context, exc: Exception) -> NoReturn:
        mapped = self.exception_mapper(exc)
        context.abort(mapped.code, mapped.message)
        raise RuntimeError("gRPC context.abort returned unexpectedly")
