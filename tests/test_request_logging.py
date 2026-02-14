from __future__ import annotations

from types import SimpleNamespace

import grpc

from grpc_extra.request_logging import GrpcRequestLoggingInterceptor


class DummyLogger:
    def __init__(self):
        self.debug_calls = []
        self.info_calls = []

    def debug(self, message, *args):
        self.debug_calls.append((message, args))

    def info(self, message, *args):
        self.info_calls.append((message, args))


class DummyDetails:
    method = "/example.Service/Call"


def _handler(kind: str):
    handler = SimpleNamespace(
        unary_unary=None,
        unary_stream=None,
        stream_unary=None,
        stream_stream=None,
        request_deserializer=None,
        response_serializer=None,
    )
    setattr(handler, kind, lambda request, _ctx: request)
    return handler


def test_logging_interceptor_logs_start_and_finish(monkeypatch):
    logger = DummyLogger()
    monkeypatch.setattr(
        "grpc_extra.request_logging.time.perf_counter", iter([1.0, 1.25]).__next__
    )

    interceptor = GrpcRequestLoggingInterceptor(logger_name="grpc_extra")
    interceptor.logger = logger
    result = interceptor._run("M", object(), lambda request, _ctx: request, {"ok": 1})
    assert result == {"ok": 1}
    assert logger.debug_calls
    assert logger.info_calls
    assert "grpc request started" in logger.debug_calls[0][0]
    assert "grpc request finished" in logger.info_calls[0][0]


def test_logging_interceptor_wraps_unary_unary_handler(monkeypatch):
    logger = DummyLogger()
    base_handler = grpc.unary_unary_rpc_method_handler(lambda request, _ctx: request)
    interceptor = GrpcRequestLoggingInterceptor()
    interceptor.logger = logger
    wrapped = interceptor.intercept_service(
        lambda _details: base_handler, DummyDetails()
    )
    assert wrapped.unary_unary({"value": 1}, object()) == {"value": 1}


def test_logging_interceptor_returns_none_when_handler_absent(monkeypatch):
    logger = DummyLogger()
    interceptor = GrpcRequestLoggingInterceptor()
    interceptor.logger = logger
    assert interceptor.intercept_service(lambda _details: None, DummyDetails()) is None


def test_logging_interceptor_wraps_other_handler_types(monkeypatch):
    logger = DummyLogger()
    interceptor = GrpcRequestLoggingInterceptor()
    interceptor.logger = logger

    wrapped_unary_stream = interceptor.intercept_service(
        lambda _details: _handler("unary_stream"), DummyDetails()
    )
    assert list(wrapped_unary_stream.unary_stream([1, 2], object())) == [1, 2]

    wrapped_stream_unary = interceptor.intercept_service(
        lambda _details: _handler("stream_unary"), DummyDetails()
    )
    assert list(wrapped_stream_unary.stream_unary(iter([1, 2]), object())) == [1, 2]

    wrapped_stream_stream = interceptor.intercept_service(
        lambda _details: _handler("stream_stream"), DummyDetails()
    )
    assert list(wrapped_stream_stream.stream_stream(iter([1, 2]), object())) == [1, 2]


def test_logging_interceptor_returns_original_handler_for_unknown_type():
    logger = DummyLogger()
    interceptor = GrpcRequestLoggingInterceptor()
    interceptor.logger = logger
    handler = SimpleNamespace(
        unary_unary=None,
        unary_stream=None,
        stream_unary=None,
        stream_stream=None,
        request_deserializer=None,
        response_serializer=None,
    )
    assert interceptor.intercept_service(lambda _d: handler, DummyDetails()) is handler
