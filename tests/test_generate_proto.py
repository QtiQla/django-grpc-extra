from __future__ import annotations

from datetime import date, datetime, time
from decimal import Decimal
from enum import Enum
from typing import Optional, Union
from uuid import UUID

import pytest
from pydantic import BaseModel

from grpc_extra.management.commands.generate_proto import (
    Command,
    ProtoBuilder,
    ProtoTypeError,
)
from grpc_extra.registry import MethodMeta, ServiceDefinition, ServiceMeta


class Status(Enum):
    ACTIVE = "active"
    DISABLED = "disabled"


class ChildSchema(BaseModel):
    value: int


class ExampleSchema(BaseModel):
    name: Optional[str]
    tags: list[int]
    data: dict
    child: ChildSchema
    status: Status
    created_at: datetime
    birthday: date
    wakeup: time
    price: Decimal
    trace_id: UUID


def test_build_proto_includes_optional_repeated_and_struct():
    definition = ServiceDefinition(
        service=object,
        meta=ServiceMeta(
            name="ExampleService",
            app_label="example",
            package="example",
            proto_path="grpc/proto/example.proto",
        ),
        methods=[
            MethodMeta(
                name="Get",
                handler_name="Get",
                request_schema=ExampleSchema,
                response_schema=ChildSchema,
            )
        ],
    )

    content = Command()._build_proto([definition])

    assert "package example;" in content
    assert "service ExampleService" in content
    assert (
        "rpc Get (ExampleServiceGetRequest) returns (ExampleServiceGetResponse);"
        in content
    )
    assert "optional string name = 1;" in content
    assert "repeated int64 tags = 2;" in content
    assert "google.protobuf.Struct data = 3;" in content
    assert "google.protobuf.Timestamp created_at = 6;" in content
    assert "google.type.Date birthday = 7;" in content
    assert "google.type.TimeOfDay wakeup = 8;" in content
    assert "string price = 9;" in content
    assert "string trace_id = 10;" in content
    assert "message ExampleServiceGetRequest" in content
    assert "message ExampleServiceGetResponse" in content
    assert 'import "google/protobuf/struct.proto";' in content
    assert 'import "google/protobuf/timestamp.proto";' in content
    assert 'import "google/type/date.proto";' in content
    assert 'import "google/type/timeofday.proto";' in content


def test_optional_list_is_supported_as_repeated_field():
    class ListSchema(BaseModel):
        items: Optional[list[int]]

    builder = ProtoBuilder(package="example")
    builder.register_message(ListSchema)
    items_field = next(
        field for field in builder.messages["ListSchema"] if field.name == "items"
    )
    assert items_field.type_name == "int64"
    assert items_field.repeated is True
    assert items_field.optional is False


def test_union_is_rejected():
    class BadSchema(BaseModel):
        value: Union[int, str]

    builder = ProtoBuilder(package="example")
    with pytest.raises(ProtoTypeError):
        builder.register_message(BadSchema)


def test_list_without_item_type_is_rejected():
    class BadSchema(BaseModel):
        items: list

    builder = ProtoBuilder(package="example")
    with pytest.raises(ProtoTypeError):
        builder.register_message(BadSchema)


def test_optional_struct_and_enum_are_allowed():
    class OptionalSchema(BaseModel):
        meta: Optional[dict]
        status: Optional[Status]

    builder = ProtoBuilder(package="example")
    builder.register_message(OptionalSchema)
    fields = builder.messages["OptionalSchema"]
    meta_field = next(field for field in fields if field.name == "meta")
    status_field = next(field for field in fields if field.name == "status")
    assert meta_field.type_name == "google.protobuf.Struct"
    assert meta_field.optional is True
    assert status_field.type_name == "Status"
    assert status_field.optional is True


def test_schema_suffix_is_stripped_for_request_and_response_names():
    class PingSchema(BaseModel):
        message: str

    definition = ServiceDefinition(
        service=object,
        meta=ServiceMeta(
            name="ExampleService",
            app_label="example",
            package="example",
            proto_path="grpc/proto/example.proto",
        ),
        methods=[
            MethodMeta(
                name="Ping",
                handler_name="ping",
                request_schema=PingSchema,
                response_schema=PingSchema,
            )
        ],
    )

    content = Command()._build_proto([definition])
    assert (
        "rpc Ping (ExampleServicePingRequest) returns (ExampleServicePingResponse);"
        in content
    )
    assert "message ExampleServicePingRequest" in content
    assert "message ExampleServicePingResponse" in content


def test_schema_without_suffix_uses_request_response_names():
    class Ping(BaseModel):
        message: str

    definition = ServiceDefinition(
        service=object,
        meta=ServiceMeta(
            name="ExampleService",
            app_label="example",
            package="example",
            proto_path="grpc/proto/example.proto",
        ),
        methods=[
            MethodMeta(
                name="Ping",
                handler_name="ping",
                request_schema=Ping,
                response_schema=Ping,
            )
        ],
    )

    content = Command()._build_proto([definition])
    assert (
        "rpc Ping (ExampleServicePingRequest) returns (ExampleServicePingResponse);"
        in content
    )
