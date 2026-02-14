from __future__ import annotations

import importlib
from typing import Any, Callable, cast

import grpc


class AuthError(Exception):
    pass


def resolve_auth_backend(backend: str | Callable | None) -> Callable | None:
    if backend is None:
        return None
    if callable(backend):
        return backend
    module_path, _, attr = backend.rpartition(".")
    if not module_path or not attr:
        raise AuthError(f"Invalid auth backend path: {backend}")
    module = importlib.import_module(module_path)
    resolved = getattr(module, attr, None)
    if not callable(resolved):
        raise AuthError(f"Auth backend '{backend}' is not callable")
    return cast(Callable[..., Any], resolved)


class AuthInterceptor(grpc.ServerInterceptor):
    def __init__(self, backend: Callable):
        self.backend = backend

    def intercept_service(self, continuation, handler_call_details):
        handler = continuation(handler_call_details)
        if handler is None:
            return None

        method = handler_call_details.method

        def _check(context, request=None):
            result = self.backend(context, method, request)
            if result is False:
                context.abort(grpc.StatusCode.UNAUTHENTICATED, "Unauthorized")

        if handler.unary_unary:

            def unary_unary(request, context):
                _check(context, request)
                return handler.unary_unary(request, context)

            return grpc.unary_unary_rpc_method_handler(
                unary_unary,
                request_deserializer=handler.request_deserializer,
                response_serializer=handler.response_serializer,
            )

        if handler.unary_stream:

            def unary_stream(request, context):
                _check(context, request)
                return handler.unary_stream(request, context)

            return grpc.unary_stream_rpc_method_handler(
                unary_stream,
                request_deserializer=handler.request_deserializer,
                response_serializer=handler.response_serializer,
            )

        if handler.stream_unary:

            def stream_unary(request_iterator, context):
                _check(context)
                return handler.stream_unary(request_iterator, context)

            return grpc.stream_unary_rpc_method_handler(
                stream_unary,
                request_deserializer=handler.request_deserializer,
                response_serializer=handler.response_serializer,
            )

        if handler.stream_stream:

            def stream_stream(request_iterator, context):
                _check(context)
                return handler.stream_stream(request_iterator, context)

            return grpc.stream_stream_rpc_method_handler(
                stream_stream,
                request_deserializer=handler.request_deserializer,
                response_serializer=handler.response_serializer,
            )

        return handler
