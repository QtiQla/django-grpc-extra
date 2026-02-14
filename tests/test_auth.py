from __future__ import annotations

from types import SimpleNamespace

import grpc
import pytest

from grpc_extra.auth import AuthError, AuthInterceptor, resolve_auth_backend


class DummyContext:
    def __init__(self):
        self.aborted = None

    def abort(self, code, message):
        self.aborted = (code, message)
        raise RuntimeError("aborted")


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

    assert resolve_auth_backend(None) is None
    assert resolve_auth_backend(fn) is fn
    assert resolve_auth_backend("grpc_extra.auth.resolve_auth_backend")


def test_resolve_auth_backend_errors():
    with pytest.raises(AuthError):
        resolve_auth_backend("bad-path")
    with pytest.raises(AuthError):
        resolve_auth_backend("grpc_extra.auth.__name__")


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
