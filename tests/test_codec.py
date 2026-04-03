from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

import sys
from types import ModuleType
from uuid import UUID

import pytest
from django.db import models
from google.protobuf import descriptor_pb2, descriptor_pool, message_factory
from pydantic import BaseModel

from grpc_extra.codec import (
    decode_request_iter,
    decode_request_value,
    encode_response_iter,
    encode_response_value,
)
from grpc_extra.exceptions import RequestDecodeError, ResponseEncodeError


class ItemSchema(BaseModel):
    value: int


class AttrSchema(BaseModel):
    value: int


class DecimalSchema(BaseModel):
    value: Decimal


class UUIDSchema(BaseModel):
    value: UUID


class ItemsSchema(BaseModel):
    items: list[ItemSchema]


class IntChoiceSchema(BaseModel):
    value: int
    label: str


class IntChoiceItemsSchema(BaseModel):
    items: list[IntChoiceSchema]


class FakePb2:
    def __init__(self, **kwargs):
        self.payload = kwargs


@dataclass
class ItemEntity:
    value: int


class IteratorContainer:
    def __init__(self, items):
        self._items = items

    def iterator(self):
        return iter(self._items)


class BrokenPb2:
    def __init__(self, **kwargs):
        raise ValueError("bad")


class CodecModel(models.Model):
    value = models.IntegerField()

    class Meta:
        app_label = "tests"
        managed = False


class AttrObj:
    def __init__(self, value: int):
        self.value = value


class StrictStringPb2:
    def __init__(self, **kwargs):
        value = kwargs.get("value")
        if not isinstance(value, str):
            raise TypeError("value must be string")
        self.payload = kwargs


def _build_choice_items_pb2():
    fd = descriptor_pb2.FileDescriptorProto()
    fd.name = "choice_items.proto"
    fd.package = "tests"

    item_message = fd.message_type.add()
    item_message.name = "IntChoiceSchema"

    value_field = item_message.field.add()
    value_field.name = "value"
    value_field.number = 1
    value_field.label = descriptor_pb2.FieldDescriptorProto.LABEL_OPTIONAL
    value_field.type = descriptor_pb2.FieldDescriptorProto.TYPE_INT64

    label_field = item_message.field.add()
    label_field.name = "label"
    label_field.number = 2
    label_field.label = descriptor_pb2.FieldDescriptorProto.LABEL_OPTIONAL
    label_field.type = descriptor_pb2.FieldDescriptorProto.TYPE_STRING

    response_message = fd.message_type.add()
    response_message.name = "ChoiceItemsResponse"

    items_field = response_message.field.add()
    items_field.name = "items"
    items_field.number = 1
    items_field.label = descriptor_pb2.FieldDescriptorProto.LABEL_REPEATED
    items_field.type = descriptor_pb2.FieldDescriptorProto.TYPE_MESSAGE
    items_field.type_name = ".tests.IntChoiceSchema"

    pool = descriptor_pool.DescriptorPool()
    pool.Add(fd)
    return message_factory.GetMessageClass(
        pool.FindMessageTypeByName("tests.ChoiceItemsResponse")
    )


def test_decode_request_value_to_pydantic():
    value = decode_request_value({"value": 11}, ItemSchema)
    assert isinstance(value, ItemSchema)
    assert value.value == 11


def test_encode_response_value_from_dataclass():
    encoded = encode_response_value(ItemEntity(value=7), ItemSchema, FakePb2)
    assert isinstance(encoded, FakePb2)
    assert encoded.payload == {"value": 7}


def test_encode_response_iter_uses_iterator_method():
    values = IteratorContainer([{"value": 1}, {"value": 2}])
    encoded = list(encode_response_iter(values, ItemSchema, FakePb2))
    assert [item.payload["value"] for item in encoded] == [1, 2]


def test_decode_request_iter_decodes_every_item():
    values = list(decode_request_iter([{"value": 1}, {"value": 2}], ItemSchema))
    assert [x.value for x in values] == [1, 2]


def test_decode_and_encode_raise_wrapped_errors():
    with pytest.raises(RequestDecodeError):
        decode_request_value({"value": "bad"}, ItemSchema)
    with pytest.raises(ResponseEncodeError):
        encode_response_value(123, None, FakePb2)


def test_encode_response_value_without_pb2_returns_raw():
    payload = {"value": 3}
    assert encode_response_value(payload, ItemSchema, None) is payload


def test_encode_response_value_wraps_pb2_constructor_error():
    with pytest.raises(ResponseEncodeError):
        encode_response_value({"value": 1}, ItemSchema, BrokenPb2)


def test_encode_response_value_from_pydantic_and_mapping():
    assert (
        encode_response_value(ItemSchema(value=4), ItemSchema, FakePb2).payload["value"]
        == 4
    )
    assert (
        encode_response_value({"value": 5}, ItemSchema, FakePb2).payload["value"] == 5
    )


def test_decode_request_value_with_schema_none_returns_input():
    value = {"x": 1}
    assert decode_request_value(value, None) is value


def test_decode_request_from_protobuf_like_payload(monkeypatch):
    class PbLike:
        DESCRIPTOR = object()

    google = ModuleType("google")
    protobuf = ModuleType("google.protobuf")
    json_format = ModuleType("google.protobuf.json_format")
    json_format.MessageToDict = lambda value, preserving_proto_field_name: {"value": 8}
    monkeypatch.setitem(sys.modules, "google", google)
    monkeypatch.setitem(sys.modules, "google.protobuf", protobuf)
    monkeypatch.setitem(sys.modules, "google.protobuf.json_format", json_format)
    decoded = decode_request_value(PbLike(), ItemSchema)
    assert decoded.value == 8


def test_decode_request_value_from_dataclass_payload():
    decoded = decode_request_value(ItemEntity(value=9), ItemSchema)
    assert decoded.value == 9


def test_encode_response_value_from_django_model_instance():
    model_instance = CodecModel(value=12)
    encoded = encode_response_value(model_instance, AttrSchema, FakePb2)
    assert encoded.payload["value"] == 12


def test_encode_response_value_from_generic_object_attributes():
    encoded = encode_response_value(AttrObj(13), AttrSchema, FakePb2)
    assert encoded.payload["value"] == 13


def test_encode_response_coerces_decimal_values_to_string():
    encoded = encode_response_value(
        {"value": Decimal("51.5074")},
        DecimalSchema,
        StrictStringPb2,
    )
    assert encoded.payload["value"] == "51.5074"


def test_encode_response_coerces_uuid_values_to_string():
    raw_uuid = UUID("12345678-1234-5678-1234-567812345678")
    encoded = encode_response_value(
        {"value": raw_uuid},
        UUIDSchema,
        StrictStringPb2,
    )
    assert encoded.payload["value"] == "12345678-1234-5678-1234-567812345678"


def test_encode_response_wraps_iterable_for_items_wrapper_schema():
    encoded = encode_response_value(
        [{"value": 1}, {"value": 2}],
        ItemsSchema,
        FakePb2,
    )
    assert encoded.payload["items"] == [{"value": 1}, {"value": 2}]


def test_encode_response_wraps_iterator_container_for_items_wrapper_schema():
    queryset = IteratorContainer([{"value": 3}, {"value": 4}])
    encoded = encode_response_value(
        queryset,
        ItemsSchema,
        FakePb2,
    )
    assert encoded.payload["items"] == [{"value": 3}, {"value": 4}]


def test_encode_response_preserves_all_items_for_repeated_message_wrapper():
    response_pb2_cls = _build_choice_items_pb2()
    encoded = encode_response_value(
        [
            IntChoiceSchema(value=1, label="Active"),
            IntChoiceSchema(value=2, label="Paused"),
            IntChoiceSchema(value=3, label="Unknown"),
        ],
        IntChoiceItemsSchema,
        response_pb2_cls,
    )
    assert len(encoded.items) == 3
    assert [(item.value, item.label) for item in encoded.items] == [
        (1, "Active"),
        (2, "Paused"),
        (3, "Unknown"),
    ]
