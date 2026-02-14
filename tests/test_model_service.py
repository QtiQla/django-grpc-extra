from __future__ import annotations

from django.db import models
import pytest
from pydantic import BaseModel, ConfigDict, Field

from grpc_extra import (
    AllowedEndpoints,
    ModelDataHelper,
    ModelFilterSchema,
    ModelService,
    ModelServiceConfig,
    grpc_service,
)
from grpc_extra.constants import GRPC_METHOD_META
from grpc_extra.model.service import ModelServiceBuilder
from grpc_extra.pagination import LimitOffsetPagination
from grpc_extra.registry import registry


class ExampleModel(models.Model):
    name = models.CharField(max_length=100)

    class Meta:
        app_label = "tests"
        managed = False


class ExampleOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str


class ExampleCreate(BaseModel):
    name: str


class ExampleListFilter(ModelFilterSchema):
    name: str | None = None
    ids: list[int] | None = Field(default=None, json_schema_extra={"op": "in", "field": "id"})


def setup_function():
    registry.clear()


def test_model_service_builds_crud_methods_and_registers_metadata():
    @grpc_service(app_label="example_app", package="example_app")
    class ExampleService(ModelService):
        config = ModelServiceConfig(
            model=ExampleModel,
            allowed_endpoints=[
                AllowedEndpoints.LIST,
                AllowedEndpoints.STREAM_LIST,
                AllowedEndpoints.DETAIL,
                AllowedEndpoints.CREATE,
            ],
            list_schema=ExampleOut,
            detail_schema=ExampleOut,
            create_schema=ExampleCreate,
            list_filter=ExampleListFilter,
            list_ordering_class="grpc_extra.ordering.Ordering",
            list_ordering_fields=["name"],
            list_searching_class="grpc_extra.searching.Searching",
            list_search_fields=["name"],
        )

    assert hasattr(ExampleService, "list")
    assert hasattr(ExampleService, "stream_list")
    assert hasattr(ExampleService, "detail")
    assert hasattr(ExampleService, "create")

    list_meta = getattr(ExampleService.list, GRPC_METHOD_META)
    stream_list_meta = getattr(ExampleService.stream_list, GRPC_METHOD_META)
    detail_meta = getattr(ExampleService.detail, GRPC_METHOD_META)
    create_meta = getattr(ExampleService.create, GRPC_METHOD_META)

    assert list_meta.name == "List"
    assert "name" in list_meta.request_schema.model_fields
    assert "limit" in list_meta.request_schema.model_fields
    assert "offset" in list_meta.request_schema.model_fields
    assert list_meta.server_streaming is False
    assert list_meta.pagination_class is LimitOffsetPagination
    assert list_meta.ordering_handler is not None
    assert list_meta.searching_handler is not None
    assert stream_list_meta.name == "StreamList"
    assert "name" in stream_list_meta.request_schema.model_fields
    assert "search" in stream_list_meta.request_schema.model_fields
    assert "ordering" in stream_list_meta.request_schema.model_fields
    assert stream_list_meta.ordering_handler is not None
    assert stream_list_meta.searching_handler is not None
    assert stream_list_meta.server_streaming is True
    assert detail_meta.name == "Detail"
    assert create_meta.name == "Create"

    definition = registry.register(ExampleService)
    method_names = {method.name for method in definition.methods}
    assert {"List", "StreamList", "Detail", "Create"}.issubset(method_names)


def test_model_service_config_does_not_require_delete_schema():
    config = ModelServiceConfig(
        model=ExampleModel,
        allowed_endpoints=[AllowedEndpoints.DELETE],
    )
    assert config.allowed_endpoints == [AllowedEndpoints.DELETE]


def test_model_service_uses_custom_data_helper():
    class CustomHelper(ModelDataHelper):
        def list_objects(self, request):
            return []

        def get_object(self, request):
            return {"id": 1, "name": "custom"}

        def create_object(self, request):
            return {"id": 2, "name": request.name}

        def update_object(self, request):
            return {"id": request.id, "name": request.payload.name}

        def patch_object(self, request):
            return {"id": request.id, "name": request.payload.name}

        def delete_object(self, request):
            return {}

    @grpc_service(app_label="example_app", package="example_app")
    class ExampleService(ModelService):
        data_helper_class = CustomHelper
        config = ModelServiceConfig(
            model=ExampleModel,
            allowed_endpoints=[AllowedEndpoints.CREATE],
            create_schema=ExampleCreate,
            detail_schema=ExampleOut,
        )

    instance = ExampleService()
    request = ExampleCreate(name="item")
    created = instance._create_impl(request, None)
    assert created["name"] == "item"


def test_model_service_list_returns_raw_iterable_for_pagination_layer():
    @grpc_service(app_label="example_app", package="example_app")
    class ExampleService(ModelService):
        config = ModelServiceConfig(
            model=ExampleModel,
            allowed_endpoints=[AllowedEndpoints.LIST],
            list_schema=ExampleOut,
        )

    class FakeObj:
        def __init__(self, id, name):
            self.id = id
            self.name = name

    class FakeHelper(ModelDataHelper):
        def list_objects(self, request):
            return [FakeObj(1, "a"), FakeObj(2, "b")]

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

    instance = ExampleService()
    instance.data_helper_class = FakeHelper
    payload = instance._list_impl(None, None)
    assert len(payload) == 2


def test_model_service_list_can_disable_pagination():
    @grpc_service(app_label="example_app", package="example_app")
    class ExampleService(ModelService):
        config = ModelServiceConfig(
            model=ExampleModel,
            allowed_endpoints=[AllowedEndpoints.LIST],
            list_schema=ExampleOut,
            list_pagination_class=None,
        )

    list_meta = getattr(ExampleService.list, GRPC_METHOD_META)
    assert list_meta.pagination_class is None
    assert "ListSchema" in list_meta.response_schema.__name__


def test_model_service_requires_valid_config_and_helper():
    with pytest.raises(TypeError):

        class _BrokenConfig(ModelService):
            config = object()

    with pytest.raises(TypeError):

        class _BrokenHelper(ModelService):
            data_helper_class = object
            config = ModelServiceConfig(
                model=ExampleModel,
                allowed_endpoints=[],
            )


def test_model_service_without_config_is_allowed():
    class _NoConfig(ModelService):
        pass

    assert _NoConfig is not None


def test_model_builder_does_not_override_existing_handler():
    @grpc_service(app_label="example_app", package="example_app")
    class ExampleService(ModelService):
        config = ModelServiceConfig(
            model=ExampleModel,
            allowed_endpoints=[AllowedEndpoints.LIST],
            list_schema=ExampleOut,
        )

        def list(self, request, context):
            return {"items": []}

    builder = ModelServiceBuilder(ExampleService, ExampleService.config)
    builder.build()
    assert ExampleService.list.__name__ == "list"
