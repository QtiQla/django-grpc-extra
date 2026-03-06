from __future__ import annotations

import importlib
import inspect
from abc import ABC, abstractmethod
from typing import Any, Callable, cast

import grpc


class AuthError(Exception):
    pass


class GrpcAuthBase(ABC):
    """Base callable auth backend contract for gRPC metadata/context."""

    def __call__(self, context, method: str, request=None) -> Any:
        return self.authenticate(context, method, request)

    @abstractmethod
    def authenticate(self, context, method: str, request=None) -> Any:
        raise NotImplementedError


class GrpcBearerAuthBase(GrpcAuthBase, ABC):
    """Bearer token auth helper for gRPC metadata-based backends."""

    scheme: str = "bearer"
    header: str = "authorization"

    def __call__(self, context, method: str, request=None) -> Any:
        token = self._extract_token(context)
        if not token:
            return None
        return self.authenticate_token(context, token, method, request)

    def authenticate_token(self, context, token: str, method: str, request=None) -> Any:
        # Backward-compatible fallback: subclasses may override `authenticate`
        # with `(context, token, method, request)` signature.
        return cast(Any, self.authenticate)(context, token, method, request)

    def _extract_token(self, context) -> str | None:
        raw_value = self._metadata_value(context, self.header)
        if not raw_value:
            return None
        parts = raw_value.split(" ")
        if not parts:
            return None
        if parts[0].lower() != self.scheme:
            return None
        token = " ".join(parts[1:]).strip()
        if not token:
            return None
        return token

    def _metadata_value(self, context, header: str) -> str | None:
        invocation_metadata = getattr(context, "invocation_metadata", None)
        if not callable(invocation_metadata):
            return None
        for key, value in invocation_metadata() or ():
            if str(key).lower() == header.lower():
                return str(value)
        return None


def resolve_auth_backend(backend: str | Callable | None) -> Callable | None:
    if backend is None:
        return None
    if callable(backend):
        return _normalize_auth_backend_callable(backend)
    module_path, _, attr = backend.rpartition(".")
    if not module_path or not attr:
        raise AuthError(f"Invalid auth backend path: {backend}")
    module = importlib.import_module(module_path)
    resolved = getattr(module, attr, None)
    if not callable(resolved):
        raise AuthError(f"Auth backend '{backend}' is not callable")
    return _normalize_auth_backend_callable(cast(Callable[..., Any], resolved))


def _normalize_auth_backend_callable(backend: Callable[..., Any]) -> Callable[..., Any]:
    if inspect.isclass(backend):
        try:
            instance = backend()
        except TypeError as exc:
            raise AuthError(
                "Auth backend class must be instantiable without constructor arguments."
            ) from exc
        if not callable(instance):
            raise AuthError("Auth backend instance is not callable")
        return cast(Callable[..., Any], instance)
    return backend


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
            if result is False or result is None:
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
