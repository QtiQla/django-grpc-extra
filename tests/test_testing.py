from __future__ import annotations

from types import SimpleNamespace

import grpc
import pytest
from django.db import models
from pydantic import BaseModel, ConfigDict

from grpc_extra import (
    AllowedEndpoints,
    GrpcTestClient,
    IsAuthActive,
    ModelDataHelper,
    ModelService,
    ModelServiceConfig,
    TestServicerContext,
    grpc_method,
    grpc_service,
    make_pb2_module,
)
from grpc_extra.registry import registry


def setup_function():
    registry.clear()


class EchoRequest(BaseModel):
    value: int


class EchoResponse(BaseModel):
    value: int


def test_grpc_test_client_calls_unary_unary_service():
    @grpc_service(app_label="tests", package="tests")
    class EchoService:
        @grpc_method(request_schema=EchoRequest, response_schema=EchoResponse)
        def echo(self, request, context):
            return {"value": request.value}

    pb2 = make_pb2_module("EchoService", {"Echo": "EchoResponse"})
    response = GrpcTestClient().call(
        EchoService,
        "Echo",
        {"value": 7},
        pb2_module=pb2,
    )

    assert response.ok is True
    assert response.code == grpc.StatusCode.OK
    assert response.data == {"value": 7}


def test_grpc_test_client_accepts_pydantic_request():
    @grpc_service(app_label="tests", package="tests")
    class EchoService:
        @grpc_method(request_schema=EchoRequest, response_schema=EchoResponse)
        def echo(self, request, context):
            return {"value": request.value}

    pb2 = make_pb2_module("EchoService", {"Echo": "EchoResponse"})
    response = GrpcTestClient().call(
        EchoService,
        "echo",
        EchoRequest(value=9),
        pb2_module=pb2,
    )

    assert response.assert_ok().data["value"] == 9


def test_grpc_test_client_passes_metadata_to_context():
    seen = {}

    @grpc_service(app_label="tests", package="tests")
    class EchoService:
        @grpc_method(request_schema=EchoRequest, response_schema=EchoResponse)
        def echo(self, request, context):
            seen["metadata"] = dict(context.invocation_metadata())
            return {"value": request.value}

    pb2 = make_pb2_module("EchoService", {"Echo": "EchoResponse"})
    GrpcTestClient().call(
        EchoService,
        "Echo",
        {"value": 1},
        metadata=[("authorization", "Bearer token"), ("x-trace-id", "123")],
        pb2_module=pb2,
    )

    assert seen["metadata"]["authorization"] == "Bearer token"
    assert seen["metadata"]["x-trace-id"] == "123"


def test_grpc_test_client_returns_invalid_argument_for_bad_request():
    @grpc_service(app_label="tests", package="tests")
    class EchoService:
        @grpc_method(request_schema=EchoRequest, response_schema=EchoResponse)
        def echo(self, request, context):
            return {"value": request.value}

    pb2 = make_pb2_module("EchoService", {"Echo": "EchoResponse"})
    response = GrpcTestClient().call(
        EchoService,
        "Echo",
        {"value": "bad"},
        pb2_module=pb2,
    )

    assert response.ok is False
    assert response.code == grpc.StatusCode.INVALID_ARGUMENT


def test_grpc_test_client_returns_permission_denied():
    @grpc_service(app_label="tests", package="tests", permissions=[IsAuthActive])
    class SecureService:
        @grpc_method(request_schema=EchoRequest, response_schema=EchoResponse)
        def echo(self, request, context):
            return {"value": request.value}

    pb2 = make_pb2_module("SecureService", {"Echo": "EchoResponse"})
    response = GrpcTestClient().call(
        SecureService,
        "Echo",
        {"value": 1},
        pb2_module=pb2,
    )

    assert response.code == grpc.StatusCode.PERMISSION_DENIED


def test_grpc_test_client_auth_backend_can_authorize_request():
    @grpc_service(app_label="tests", package="tests", permissions=[IsAuthActive])
    class SecureService:
        @grpc_method(request_schema=EchoRequest, response_schema=EchoResponse)
        def echo(self, request, context):
            return {"value": request.value}

    def auth_backend(context, _method, _request):
        context.user = SimpleNamespace(is_authenticated=True, is_active=True)
        return context.user

    pb2 = make_pb2_module("SecureService", {"Echo": "EchoResponse"})
    response = GrpcTestClient(auth_backend=auth_backend).call(
        SecureService,
        "Echo",
        {"value": 3},
        pb2_module=pb2,
    )

    assert response.assert_ok().data["value"] == 3


def test_grpc_test_client_auth_backend_can_reject_request():
    @grpc_service(app_label="tests", package="tests")
    class EchoService:
        @grpc_method(request_schema=EchoRequest, response_schema=EchoResponse)
        def echo(self, request, context):
            return {"value": request.value}

    pb2 = make_pb2_module("EchoService", {"Echo": "EchoResponse"})
    response = GrpcTestClient(auth_backend=lambda *_args: None).call(
        EchoService,
        "Echo",
        {"value": 3},
        pb2_module=pb2,
    )

    assert response.code == grpc.StatusCode.UNAUTHENTICATED
    assert response.details == "Unauthorized"


def test_grpc_test_client_rejects_streaming_methods():
    @grpc_service(app_label="tests", package="tests")
    class StreamService:
        @grpc_method(
            request_schema=EchoRequest,
            response_schema=EchoResponse,
            server_streaming=True,
        )
        def stream_values(self, request, context):
            return [{"value": request.value}]

    pb2 = make_pb2_module("StreamService", {"StreamValues": "EchoResponse"})
    with pytest.raises(NotImplementedError):
        GrpcTestClient().call(
            StreamService,
            "StreamValues",
            {"value": 1},
            pb2_module=pb2,
        )


class ExampleModel(models.Model):
    name = models.CharField(max_length=100)

    class Meta:
        app_label = "tests"
        managed = False


class ExampleOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str


def test_grpc_test_client_supports_model_service_list_pagination():
    class FakeObj:
        def __init__(self, id, name):
            self.id = id
            self.name = name

    class FakeHelper(ModelDataHelper):
        def list_objects(self, request):
            return [FakeObj(1, "one"), FakeObj(2, "two"), FakeObj(3, "three")]

        def get_object(self, request):
            return None

        def create_object(self, request):
            return None

        def update_object(self, request):
            return None

        def patch_object(self, request):
            return None

        def delete_object(self, request):
            return {}

    @grpc_service(app_label="tests", package="tests")
    class ExampleService(ModelService):
        data_helper_class = FakeHelper
        config = ModelServiceConfig(
            model=ExampleModel,
            allowed_endpoints=[AllowedEndpoints.LIST],
            list_schema=ExampleOut,
        )

    list_meta = ExampleService.list.__grpc_method_meta__
    pb2 = make_pb2_module(
        "ExampleService", {"List": list_meta.response_schema.__name__}
    )
    response = GrpcTestClient().call(
        ExampleService,
        "List",
        {"limit": 2, "offset": 1},
        pb2_module=pb2,
    )

    assert response.assert_ok().data["count"] == 3
    assert response.data["limit"] == 2
    assert response.data["offset"] == 1
    assert len(response.data["results"]) == 2


def test_grpc_test_client_can_use_prebuilt_context():
    @grpc_service(app_label="tests", package="tests")
    class EchoService:
        @grpc_method(request_schema=EchoRequest, response_schema=EchoResponse)
        def echo(self, request, context):
            return {"value": request.value + getattr(context, "bonus", 0)}

    pb2 = make_pb2_module("EchoService", {"Echo": "EchoResponse"})
    context = TestServicerContext(bonus=5)
    response = GrpcTestClient().call(
        EchoService,
        "Echo",
        {"value": 4},
        context=context,
        pb2_module=pb2,
    )

    assert response.assert_ok().data["value"] == 9
