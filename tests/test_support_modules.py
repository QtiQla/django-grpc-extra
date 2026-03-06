from __future__ import annotations

import pytest
from django.core.exceptions import ObjectDoesNotExist
from pydantic import BaseModel, ValidationError

from grpc_extra.decorators import grpc_method, grpc_service
from grpc_extra.apps import GrpcExtraConfig
from grpc_extra.exceptions import (
    MappedError,
    RequestDecodeError,
    ResponseEncodeError,
    default_exception_mapper,
    resolve_exception_mapper,
)
from grpc_extra.registry import ServiceNotDecoratedError, registry
from grpc_extra.schemas import MethodParameter
from grpc_extra.utils import (
    is_upper_camel_case,
    normalize_proto_path,
    pb2_grpc_module_path,
    pb2_module_path,
    proto_path_to_module,
    to_upper_camel_case,
)


class ValueSchema(BaseModel):
    value: int


def sample_exception_mapper(exc: Exception) -> MappedError:
    return MappedError(code=default_exception_mapper(exc).code, message="sample")


def test_utils_string_and_path_helpers():
    assert is_upper_camel_case("PingRequest") is True
    assert is_upper_camel_case("ping_request") is False
    assert to_upper_camel_case("ping_request") == "PingRequest"
    assert normalize_proto_path("\\grpc\\proto\\a") == "grpc/proto/a.proto"
    assert proto_path_to_module("app", "grpc/proto/a.proto") == "app.grpc.proto.a"
    assert pb2_module_path("app", "grpc/proto/a.proto") == "app.grpc.proto.a_pb2"
    assert (
        pb2_grpc_module_path("app", "grpc/proto/a.proto") == "app.grpc.proto.a_pb2_grpc"
    )


def test_method_parameter_and_app_config():
    payload = MethodParameter(method_name="ping", request_schema=ValueSchema).dict()
    assert payload["method_name"] == "ping"
    assert GrpcExtraConfig.name == "grpc_extra"


def test_exception_mapping_defaults_and_custom():
    try:
        ValueSchema(value="bad")
    except ValidationError as exc:
        mapped = default_exception_mapper(exc)
    assert mapped.code.name == "INVALID_ARGUMENT"

    req_err = RequestDecodeError("decode")
    req_err.__cause__ = Exception("x")
    assert default_exception_mapper(req_err).code.name == "INTERNAL"
    assert (
        default_exception_mapper(ResponseEncodeError("encode")).code.name == "INTERNAL"
    )
    assert (
        default_exception_mapper(PermissionError("forbidden")).code.name
        == "PERMISSION_DENIED"
    )
    assert (
        default_exception_mapper(ObjectDoesNotExist("missing")).code.name == "NOT_FOUND"
    )

    def custom(exc):
        return MappedError(code=default_exception_mapper(exc).code, message="custom")

    assert resolve_exception_mapper(custom) is custom
    resolved = resolve_exception_mapper(
        "tests.test_support_modules.sample_exception_mapper"
    )
    assert callable(resolved)
    assert resolved(Exception("x")).message == "sample"
    with pytest.raises(ValueError):
        resolve_exception_mapper("bad-path")
    with pytest.raises(ValueError):
        resolve_exception_mapper("grpc_extra.exceptions.MappedError")


def test_registry_duplicate_and_not_decorated_errors():
    class Plain:
        pass

    registry.clear()
    with pytest.raises(ServiceNotDecoratedError):
        registry.register(Plain)

    @grpc_service(app_label="example")
    class ExampleService:
        @grpc_method(request_schema=ValueSchema, response_schema=ValueSchema)
        def ping(self, request, context):
            return request

    first = registry.register(ExampleService)
    second = registry.register(ExampleService)
    assert first is second
