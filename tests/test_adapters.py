from __future__ import annotations

from types import SimpleNamespace

import grpc
import pytest
from pydantic import BaseModel

from grpc_extra.adapters import ServiceRuntimeAdapter
from grpc_extra.ordering import Ordering
from grpc_extra.pagination import LimitOffsetPagination
from grpc_extra.searching import Searching
from grpc_extra.registry import MethodMeta, ServiceDefinition, ServiceMeta


class RequestSchema(BaseModel):
    value: int


class ResponseSchema(BaseModel):
    value: int


class FakePb2:
    def __init__(self, **kwargs):
        self.payload = kwargs


class FakeAbort(Exception):
    pass


class FakeContext:
    def abort(self, code, message):
        raise FakeAbort((code, message))


def _adapter() -> ServiceRuntimeAdapter:
    definition = ServiceDefinition(
        service=object,
        meta=ServiceMeta(name="EchoService", app_label="echo"),
        methods=[],
    )
    pb2 = SimpleNamespace(DESCRIPTOR=SimpleNamespace(services_by_name={}))
    return ServiceRuntimeAdapter(definition, pb2)


def test_unary_unary_wrapper_converts_request_and_response():
    adapter = _adapter()
    context = FakeContext()
    method_meta = MethodMeta(
        name="Echo",
        handler_name="echo",
        request_schema=RequestSchema,
        response_schema=ResponseSchema,
    )

    def echo(request, _context):
        assert isinstance(request, RequestSchema)
        return {"value": request.value}

    wrapper = adapter._wrap_unary_unary(echo, method_meta, FakePb2)
    result = wrapper({"value": 3}, context)
    assert isinstance(result, FakePb2)
    assert result.payload["value"] == 3


def test_stream_unary_wrapper_supports_iterator_input():
    adapter = _adapter()
    context = FakeContext()
    method_meta = MethodMeta(
        name="Collect",
        handler_name="collect",
        request_schema=RequestSchema,
        response_schema=ResponseSchema,
        client_streaming=True,
    )

    def collect(request_iter, _context):
        return {"value": sum(item.value for item in request_iter)}

    wrapper = adapter._wrap_stream_unary(collect, method_meta, FakePb2)
    result = wrapper(iter([{"value": 1}, {"value": 2}, {"value": 3}]), context)
    assert result.payload["value"] == 6


def test_unary_stream_wrapper_supports_iterable_output():
    adapter = _adapter()
    context = FakeContext()
    method_meta = MethodMeta(
        name="StreamValues",
        handler_name="stream_values",
        request_schema=RequestSchema,
        response_schema=ResponseSchema,
        server_streaming=True,
    )

    def stream_values(_request, _context):
        return [{"value": 1}, {"value": 2}]

    wrapper = adapter._wrap_unary_stream(stream_values, method_meta, FakePb2)
    payloads = [item.payload["value"] for item in wrapper({"value": 1}, context)]
    assert payloads == [1, 2]


def test_validation_error_is_aborted_with_invalid_argument():
    adapter = _adapter()
    context = FakeContext()
    method_meta = MethodMeta(
        name="Echo",
        handler_name="echo",
        request_schema=RequestSchema,
        response_schema=ResponseSchema,
    )

    def echo(_request, _context):
        return {"value": 1}

    wrapper = adapter._wrap_unary_unary(echo, method_meta, FakePb2)
    with pytest.raises(FakeAbort) as exc:
        wrapper({"value": "bad"}, context)

    code, _ = exc.value.args[0]
    assert code == grpc.StatusCode.INVALID_ARGUMENT


def test_unary_unary_wrapper_applies_pagination_before_encoding():
    adapter = _adapter()
    context = FakeContext()
    paged_request = LimitOffsetPagination.build_request_schema(None)
    paged_response = LimitOffsetPagination.build_response_schema(ResponseSchema)
    method_meta = MethodMeta(
        name="List",
        handler_name="list_items",
        request_schema=paged_request,
        response_schema=paged_response,
        pagination_class=LimitOffsetPagination,
    )

    def list_items(_request, _context):
        return [{"value": 1}, {"value": 2}, {"value": 3}]

    wrapper = adapter._wrap_unary_unary(list_items, method_meta, FakePb2)
    result = wrapper(paged_request(limit=2, offset=1), context)
    assert result.payload["count"] == 3
    assert result.payload["limit"] == 2
    assert result.payload["offset"] == 1
    assert len(result.payload["results"]) == 2


def test_stream_stream_wrapper_encodes_all_items():
    adapter = _adapter()
    context = FakeContext()
    method_meta = MethodMeta(
        name="BiDi",
        handler_name="bidi",
        request_schema=RequestSchema,
        response_schema=ResponseSchema,
        client_streaming=True,
        server_streaming=True,
    )

    def bidi(request_iter, _context):
        return [{"value": item.value} for item in request_iter]

    wrapper = adapter._wrap_stream_stream(bidi, method_meta, FakePb2)
    result = list(wrapper(iter([{"value": 1}, {"value": 2}]), context))
    assert [x.payload["value"] for x in result] == [1, 2]


def test_unary_stream_wrapper_requires_iterable():
    adapter = _adapter()
    context = FakeContext()
    method_meta = MethodMeta(
        name="StreamValues",
        handler_name="stream_values",
        request_schema=RequestSchema,
        response_schema=ResponseSchema,
        server_streaming=True,
    )

    def stream_values(_request, _context):
        return 123

    wrapper = adapter._wrap_unary_stream(stream_values, method_meta, FakePb2)
    with pytest.raises(FakeAbort):
        list(wrapper({"value": 1}, context))


def test_apply_skips_unknown_service_or_missing_response_cls():
    definition = ServiceDefinition(
        service=object,
        meta=ServiceMeta(name="EchoService", app_label="echo"),
        methods=[
            MethodMeta(
                name="Echo",
                handler_name="echo",
                request_schema=RequestSchema,
                response_schema=ResponseSchema,
            )
        ],
    )
    pb2 = SimpleNamespace(
        DESCRIPTOR=SimpleNamespace(services_by_name={}),
    )
    adapter = ServiceRuntimeAdapter(definition, pb2)
    servicer = SimpleNamespace(echo=lambda req, ctx: req)
    adapter.apply(servicer)
    assert not hasattr(servicer, "Echo")


def test_apply_skips_missing_method_desc_or_handler(monkeypatch):
    definition = ServiceDefinition(
        service=object,
        meta=ServiceMeta(name="EchoService", app_label="echo"),
        methods=[MethodMeta(name="Missing", handler_name="missing")],
    )
    pb2 = SimpleNamespace(
        DESCRIPTOR=SimpleNamespace(
            services_by_name={
                "EchoService": SimpleNamespace(
                    methods_by_name={
                        "Missing": SimpleNamespace(
                            output_type=SimpleNamespace(name="Resp")
                        )
                    }
                )
            }
        ),
        Resp=FakePb2,
    )
    adapter = ServiceRuntimeAdapter(definition, pb2)
    servicer = SimpleNamespace()
    adapter.apply(servicer)
    assert not hasattr(servicer, "Missing")


def test_apply_skips_missing_method_description_and_response_class():
    definition = ServiceDefinition(
        service=object,
        meta=ServiceMeta(name="EchoService", app_label="echo"),
        methods=[
            MethodMeta(name="Absent", handler_name="echo"),
            MethodMeta(name="Echo", handler_name="echo"),
        ],
    )
    pb2 = SimpleNamespace(
        DESCRIPTOR=SimpleNamespace(
            services_by_name={
                "EchoService": SimpleNamespace(
                    methods_by_name={
                        "Echo": SimpleNamespace(
                            output_type=SimpleNamespace(name="Nope")
                        )
                    }
                )
            }
        )
    )
    adapter = ServiceRuntimeAdapter(definition, pb2)
    servicer = SimpleNamespace(echo=lambda req, ctx: req)
    adapter.apply(servicer)
    assert not hasattr(servicer, "Echo")


def test_encode_stream_aborts_on_encoding_error():
    adapter = _adapter()
    context = FakeContext()
    method_meta = MethodMeta(
        name="StreamValues",
        handler_name="stream_values",
        request_schema=None,
        response_schema=ResponseSchema,
        server_streaming=True,
    )
    with pytest.raises(FakeAbort):
        list(adapter._encode_stream([{"bad": 1}], method_meta, FakePb2, context))


def test_stream_unary_rejects_pagination():
    adapter = _adapter()
    context = FakeContext()
    method_meta = MethodMeta(
        name="Collect",
        handler_name="collect",
        request_schema=RequestSchema,
        response_schema=ResponseSchema,
        client_streaming=True,
        pagination_class=LimitOffsetPagination,
    )

    def collect(_request_iter, _context):
        return {"value": 1}

    wrapper = adapter._wrap_stream_unary(collect, method_meta, FakePb2)
    with pytest.raises(FakeAbort):
        wrapper(iter([{"value": 1}]), context)


def test_stream_stream_requires_iterable_result():
    adapter = _adapter()
    context = FakeContext()
    method_meta = MethodMeta(
        name="BiDi",
        handler_name="bidi",
        request_schema=RequestSchema,
        response_schema=ResponseSchema,
        client_streaming=True,
        server_streaming=True,
    )

    def bidi(_request_iter, _context):
        return 1

    wrapper = adapter._wrap_stream_stream(bidi, method_meta, FakePb2)
    with pytest.raises(FakeAbort):
        list(wrapper(iter([{"value": 1}]), context))


def test_unary_stream_wrapper_applies_searching_and_ordering():
    adapter = _adapter()
    context = FakeContext()
    request_schema = Searching.build_request_schema(RequestSchema)
    request_schema = Ordering.build_request_schema(request_schema)
    method_meta = MethodMeta(
        name="List",
        handler_name="list_items",
        request_schema=request_schema,
        response_schema=ResponseSchema,
        server_streaming=True,
        searching_handler=Searching(search_fields=["value"]),
        ordering_handler=Ordering(ordering_fields=["value"]),
    )

    def list_items(_request, _context):
        return [{"value": 2}, {"value": 1}, {"value": 3}]

    wrapper = adapter._wrap_unary_stream(list_items, method_meta, FakePb2)
    result = list(wrapper(request_schema(search="1", ordering="-value", value=0), context))
    assert [item.payload["value"] for item in result] == [1]
