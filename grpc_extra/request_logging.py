from __future__ import annotations

import logging
import time

import grpc


class GrpcRequestLoggingInterceptor(grpc.ServerInterceptor):
    """Logs incoming grpc calls and execution time using Django logging config."""

    def __init__(self, logger_name: str = "grpc_extra") -> None:
        self.logger = logging.getLogger(logger_name)

    def intercept_service(self, continuation, handler_call_details):
        handler = continuation(handler_call_details)
        if handler is None:
            return None

        method = handler_call_details.method

        if handler.unary_unary:

            def unary_unary(request, context):
                return self._run(method, context, handler.unary_unary, request)

            return grpc.unary_unary_rpc_method_handler(
                unary_unary,
                request_deserializer=handler.request_deserializer,
                response_serializer=handler.response_serializer,
            )

        if handler.unary_stream:

            def unary_stream(request, context):
                return self._run(method, context, handler.unary_stream, request)

            return grpc.unary_stream_rpc_method_handler(
                unary_stream,
                request_deserializer=handler.request_deserializer,
                response_serializer=handler.response_serializer,
            )

        if handler.stream_unary:

            def stream_unary(request_iterator, context):
                return self._run(
                    method, context, handler.stream_unary, request_iterator
                )

            return grpc.stream_unary_rpc_method_handler(
                stream_unary,
                request_deserializer=handler.request_deserializer,
                response_serializer=handler.response_serializer,
            )

        if handler.stream_stream:

            def stream_stream(request_iterator, context):
                return self._run(
                    method, context, handler.stream_stream, request_iterator
                )

            return grpc.stream_stream_rpc_method_handler(
                stream_stream,
                request_deserializer=handler.request_deserializer,
                response_serializer=handler.response_serializer,
            )

        return handler

    def _run(self, method: str, context, fn, request_or_iterator):
        started = time.perf_counter()
        self.logger.debug("grpc request started method=%s", method)
        try:
            return fn(request_or_iterator, context)
        finally:
            duration_ms = (time.perf_counter() - started) * 1000
            self.logger.info(
                "grpc request finished method=%s duration_ms=%.2f", method, duration_ms
            )
