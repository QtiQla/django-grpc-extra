from __future__ import annotations

from types import SimpleNamespace

import grpc
import pytest

from grpc_extra.auth import (
    AuthError,
    AuthInterceptor,
    GrpcAuthBase,
    GrpcBearerAuthBase,
    resolve_auth_backend,
)


class DummyContext:
    def __init__(self):
        self.aborted = None

    def abort(self, code, message):
        self.aborted = (code, message)
        raise RuntimeError("aborted")


class DummyMetadataContext(DummyContext):
    def __init__(self, metadata):
        super().__init__()
        self._metadata = metadata

    def invocation_metadata(self):
        return self._metadata


class DummyDetails:
    method = "/example.Service/Call"


def _make_handler(kind: str):
    handler = SimpleNamespace(
        unary_unary=None,
        unary_stream=None,
        stream_unary=None,
        stream_stream=None,
        request_deserializer=None,
        response_serializer=None,
    )
    setattr(handler, kind, lambda request, _context: request)
    return handler


def _empty_handler():
    return SimpleNamespace(
        unary_unary=None,
        unary_stream=None,
        stream_unary=None,
        stream_stream=None,
        request_deserializer=None,
        response_serializer=None,
    )


def test_resolve_auth_backend_variants():
    def fn(*_args):
        return True

    class BackendClass:
        def __call__(self, *_args):
            return True

    assert resolve_auth_backend(None) is None
    assert resolve_auth_backend(fn) is fn
    assert callable(resolve_auth_backend(BackendClass))
    assert resolve_auth_backend("grpc_extra.auth.resolve_auth_backend")
    assert callable(resolve_auth_backend("tests.test_auth.ResolverBackendClass"))


def test_resolve_auth_backend_errors():
    class BadBackendClass:
        def __init__(self, required):
            self.required = required

        def __call__(self, *_args):
            return True

    with pytest.raises(AuthError):
        resolve_auth_backend("bad-path")
    with pytest.raises(AuthError):
        resolve_auth_backend("grpc_extra.auth.__name__")
    with pytest.raises(AuthError):
        resolve_auth_backend(BadBackendClass)


class ResolverBackendClass:
    def __call__(self, *_args):
        return True


def test_grpc_auth_base_calls_authenticate():
    class SampleAuth(GrpcAuthBase):
        def authenticate(self, context, method: str, request=None):
            return {"context": context, "method": method, "request": request}

    backend = SampleAuth()
    result = backend("ctx", "/svc/method", {"k": "v"})
    assert result == {"context": "ctx", "method": "/svc/method", "request": {"k": "v"}}


def test_grpc_bearer_auth_base_extracts_and_authenticates():
    class SampleBearer(GrpcBearerAuthBase):
        def authenticate(self, context, token: str, method: str, request=None):
            return (context, token, method, request)

    backend = SampleBearer()
    context = DummyMetadataContext([("Authorization", "Bearer abc.def")])
    result = backend(context, "/svc/method", {"x": 1})
    assert result == (context, "abc.def", "/svc/method", {"x": 1})


def test_grpc_bearer_auth_base_returns_none_without_token():
    class SampleBearer(GrpcBearerAuthBase):
        def authenticate(self, context, token: str, method: str, request=None):
            return token

    backend = SampleBearer()
    assert backend(DummyMetadataContext([]), "/svc/method", None) is None
    assert (
        backend(
            DummyMetadataContext([("Authorization", "Basic abc")]), "/svc/method", None
        )
        is None
    )
    assert (
        backend(
            DummyMetadataContext([("Authorization", "Bearer")]), "/svc/method", None
        )
        is None
    )


def test_grpc_bearer_auth_base_is_case_insensitive_for_header_and_scheme():
    class SampleBearer(GrpcBearerAuthBase):
        def authenticate(self, context, token: str, method: str, request=None):
            return token

    backend = SampleBearer()
    assert (
        backend(
            DummyMetadataContext([("authorization", "Bearer abc")]), "/svc/method", None
        )
        == "abc"
    )
    assert (
        backend(
            DummyMetadataContext([("Authorization", "bearer abc")]), "/svc/method", None
        )
        == "abc"
    )


def test_grpc_bearer_auth_base_supports_empty_scheme_raw_token():
    class RawTokenBearer(GrpcBearerAuthBase):
        scheme = ""

        def authenticate(self, context, token: str, method: str, request=None):
            return token

    backend = RawTokenBearer()
    assert (
        backend(
            DummyMetadataContext([("Authorization", "raw.jwt.token")]),
            "/svc/method",
            None,
        )
        == "raw.jwt.token"
    )


def test_grpc_bearer_auth_base_supports_custom_header():
    class ApiKeyBearer(GrpcBearerAuthBase):
        header = "x-api-key"
        scheme = "Token"

        def authenticate(self, context, token: str, method: str, request=None):
            return token

    backend = ApiKeyBearer()
    context = DummyMetadataContext([("x-api-key", "Token custom-key")])
    assert backend(context, "/svc/method", None) == "custom-key"


@pytest.mark.parametrize(
    ("kind", "factory"),
    [
        ("unary_unary", grpc.unary_unary_rpc_method_handler),
        ("unary_stream", grpc.unary_stream_rpc_method_handler),
        ("stream_unary", grpc.stream_unary_rpc_method_handler),
        ("stream_stream", grpc.stream_stream_rpc_method_handler),
    ],
)
def test_auth_interceptor_wraps_all_handler_types(kind, factory):
    interceptor = AuthInterceptor(lambda *_args: True)
    wrapped = interceptor.intercept_service(
        lambda _details: _make_handler(kind), DummyDetails()
    )
    assert wrapped is not None
    assert isinstance(wrapped, type(factory(lambda *_a: None)))


def test_auth_interceptor_aborts_when_backend_returns_false():
    interceptor = AuthInterceptor(lambda *_args: False)
    wrapped = interceptor.intercept_service(
        lambda _details: _make_handler("unary_unary"), DummyDetails()
    )
    context = DummyContext()
    with pytest.raises(RuntimeError):
        wrapped.unary_unary({}, context)
    assert context.aborted == (grpc.StatusCode.UNAUTHENTICATED, "Unauthorized")


def test_auth_interceptor_aborts_when_backend_returns_none():
    interceptor = AuthInterceptor(lambda *_args: None)
    wrapped = interceptor.intercept_service(
        lambda _details: _make_handler("unary_unary"), DummyDetails()
    )
    context = DummyContext()
    with pytest.raises(RuntimeError):
        wrapped.unary_unary({}, context)
    assert context.aborted == (grpc.StatusCode.UNAUTHENTICATED, "Unauthorized")


def test_auth_interceptor_allows_unary_unary_call():
    interceptor = AuthInterceptor(lambda *_args: True)
    wrapped = interceptor.intercept_service(
        lambda _details: _make_handler("unary_unary"), DummyDetails()
    )
    assert wrapped.unary_unary({"ok": 1}, DummyContext()) == {"ok": 1}


def test_auth_interceptor_returns_none_when_no_handler():
    interceptor = AuthInterceptor(lambda *_args: True)
    assert interceptor.intercept_service(lambda _details: None, DummyDetails()) is None


def test_auth_interceptor_executes_stream_variants():
    interceptor = AuthInterceptor(lambda *_args: True)
    context = DummyContext()

    unary_stream = interceptor.intercept_service(
        lambda _d: _make_handler("unary_stream"), DummyDetails()
    )
    assert list(unary_stream.unary_stream([1, 2], context)) == [1, 2]

    stream_unary = interceptor.intercept_service(
        lambda _d: _make_handler("stream_unary"), DummyDetails()
    )
    assert list(stream_unary.stream_unary(iter([1, 2]), context)) == [1, 2]

    stream_stream = interceptor.intercept_service(
        lambda _d: _make_handler("stream_stream"), DummyDetails()
    )
    assert list(stream_stream.stream_stream(iter([1, 2]), context)) == [1, 2]


def test_auth_interceptor_returns_original_handler_for_unknown_type():
    interceptor = AuthInterceptor(lambda *_args: True)
    handler = _empty_handler()
    wrapped = interceptor.intercept_service(lambda _d: handler, DummyDetails())
    assert wrapped is handler
