from __future__ import annotations

import pytest
from pydantic import BaseModel

from grpc_extra.decorators import (
    grpc_method,
    grpc_ordering,
    grpc_pagination,
    grpc_searching,
    grpc_service,
)
from grpc_extra.ordering import Ordering
from grpc_extra.pagination import LimitOffsetPagination
from grpc_extra.searching import Searching
from grpc_extra.registry import registry


class RequestSchema(BaseModel):
    value: int


class ResponseSchema(BaseModel):
    value: int


def setup_function():
    registry.clear()


def test_grpc_method_name_is_converted_from_snake_case():
    @grpc_service(app_label="example")
    class UserService:
        @grpc_method(request_schema=RequestSchema, response_schema=ResponseSchema)
        def get_profile(self, request, context):
            return {"value": request.value}

    definition = registry.register(UserService)
    method_meta = next(
        item for item in definition.methods if item.handler_name == "get_profile"
    )
    assert method_meta.name == "GetProfile"
    assert definition.meta.name == "UserService"


def test_explicit_grpc_method_name_is_preserved():
    @grpc_service(name="UsersApi", app_label="example")
    class service:
        @grpc_method(
            name="FetchUser",
            request_schema=RequestSchema,
            response_schema=ResponseSchema,
        )
        def get_user(self, request, context):
            return {"value": request.value}

    definition = registry.register(service)
    method_meta = next(
        item for item in definition.methods if item.handler_name == "get_user"
    )
    assert method_meta.name == "FetchUser"
    assert definition.meta.name == "UsersApi"


def test_grpc_pagination_extends_method_schemas():
    @grpc_service(app_label="example")
    class UserService:
        @grpc_method(request_schema=None, response_schema=ResponseSchema)
        @grpc_pagination(LimitOffsetPagination)
        def list_users(self, request, context):
            return []

    definition = registry.register(UserService)
    method_meta = next(
        item for item in definition.methods if item.handler_name == "list_users"
    )
    assert method_meta.pagination_class is LimitOffsetPagination
    assert method_meta.request_schema is not None
    assert method_meta.response_schema is not None


def test_grpc_pagination_requires_position_under_grpc_method():
    with pytest.raises(ValueError):

        class _Service:
            @grpc_pagination(LimitOffsetPagination)
            @grpc_method(request_schema=None, response_schema=ResponseSchema)
            def list_users(self, request, context):
                return []


def test_grpc_pagination_requires_response_schema():
    with pytest.raises(ValueError):

        class _Service:
            @grpc_method(request_schema=None, response_schema=None)
            @grpc_pagination(LimitOffsetPagination)
            def list_users(self, request, context):
                return []


def test_grpc_pagination_rejects_streaming_methods():
    with pytest.raises(ValueError):

        class _Service:
            @grpc_method(
                request_schema=RequestSchema,
                response_schema=ResponseSchema,
                server_streaming=True,
            )
            @grpc_pagination(LimitOffsetPagination)
            def list_users(self, request, context):
                return []


def test_grpc_search_and_order_extend_request_schema():
    @grpc_service(app_label="example")
    class UserService:
        @grpc_method(request_schema=RequestSchema, response_schema=ResponseSchema)
        @grpc_pagination(LimitOffsetPagination)
        @grpc_ordering(Ordering, ordering_fields=["value"])
        @grpc_searching(Searching, search_fields=["value"])
        def list_users(self, request, context):
            return []

    definition = registry.register(UserService)
    method_meta = next(
        item for item in definition.methods if item.handler_name == "list_users"
    )
    assert method_meta.searching_handler is not None
    assert method_meta.ordering_handler is not None
    assert method_meta.request_schema is not None
    assert "search" in method_meta.request_schema.model_fields
    assert "ordering" in method_meta.request_schema.model_fields
    assert "limit" in method_meta.request_schema.model_fields


def test_grpc_searching_requires_position_under_grpc_method():
    with pytest.raises(ValueError):

        class _Service:
            @grpc_searching(Searching, search_fields=["value"])
            @grpc_method(request_schema=RequestSchema, response_schema=ResponseSchema)
            def list_users(self, request, context):
                return []


def test_grpc_ordering_requires_position_under_grpc_method():
    with pytest.raises(ValueError):

        class _Service:
            @grpc_ordering(Ordering, ordering_fields=["value"])
            @grpc_method(request_schema=RequestSchema, response_schema=ResponseSchema)
            def list_users(self, request, context):
                return []
