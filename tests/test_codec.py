from __future__ import annotations

import sys
from dataclasses import dataclass
from datetime import date, time
from decimal import Decimal
from types import ModuleType
from uuid import UUID

import pytest
from django.db import models
from google.protobuf import descriptor_pb2, descriptor_pool, message_factory
from pydantic import BaseModel, Field

from grpc_extra.codec import (
    _coerce_google_types_to_python,
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


class DateSchema(BaseModel):
    value: date


class TimeSchema(BaseModel):
    value: time


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


def test_encode_response_coerces_date_values_to_google_type_payload():
    encoded = encode_response_value(
        {"value": date(2026, 4, 3)},
        DateSchema,
        FakePb2,
    )
    assert encoded.payload["value"] == {"year": 2026, "month": 4, "day": 3}


def test_encode_response_coerces_time_values_to_google_type_payload():
    encoded = encode_response_value(
        {"value": time(13, 41, 26, 123456)},
        TimeSchema,
        FakePb2,
    )
    assert encoded.payload["value"] == {
        "hours": 13,
        "minutes": 41,
        "seconds": 26,
        "nanos": 123456000,
    }


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


# --- _coerce_google_types_to_python unit tests ---


class _DateSchema(BaseModel):
    value: date


class _OptionalDateSchema(BaseModel):
    value: date | None = None


class _TimeSchema(BaseModel):
    value: time


class _OptionalTimeSchema(BaseModel):
    value: time | None = None


class _DateTimeComboSchema(BaseModel):
    start_date: date
    start_time: time | None = None
    name: str = ""


class _ListDateSchema(BaseModel):
    dates: list[date]


class _FalsePosSchema(BaseModel):
    # Fields that overlap with TimeOfDay names but are plain ints
    hours: int
    minutes: int


def test_coerce_google_date_all_fields():
    result = _coerce_google_types_to_python(
        {"value": {"year": 2025, "month": 11, "day": 30}}, _DateSchema
    )
    assert result == {"value": date(2025, 11, 30)}


def test_coerce_google_date_missing_day_defaults_to_1():
    # MessageToDict omits zero-value fields — day=1 is the safe default
    result = _coerce_google_types_to_python(
        {"value": {"year": 2025, "month": 1}}, _DateSchema
    )
    assert result == {"value": date(2025, 1, 1)}


def test_coerce_google_date_optional_field():
    result = _coerce_google_types_to_python(
        {"value": {"year": 2026, "month": 6, "day": 1}}, _OptionalDateSchema
    )
    assert result == {"value": date(2026, 6, 1)}


def test_coerce_google_time_all_fields():
    result = _coerce_google_types_to_python(
        {"value": {"hours": 14, "minutes": 30, "seconds": 5, "nanos": 500_000_000}},
        _TimeSchema,
    )
    assert result == {"value": time(14, 30, 5, 500_000)}


def test_coerce_google_time_hours_zero_omitted_by_message_to_dict():
    # hours=0 is omitted by MessageToDict in proto3 — must still be parsed as time
    result = _coerce_google_types_to_python(
        {"value": {"minutes": 30, "seconds": 0}}, _TimeSchema
    )
    assert result == {"value": time(0, 30, 0, 0)}


def test_coerce_google_time_only_seconds():
    result = _coerce_google_types_to_python({"value": {"seconds": 45}}, _TimeSchema)
    assert result == {"value": time(0, 0, 45, 0)}


def test_coerce_google_time_optional_field():
    result = _coerce_google_types_to_python(
        {"value": {"hours": 8, "minutes": 0}}, _OptionalTimeSchema
    )
    assert result == {"value": time(8, 0, 0, 0)}


def test_coerce_google_types_nested_in_dict():
    result = _coerce_google_types_to_python(
        {
            "start_date": {"year": 2025, "month": 11, "day": 30},
            "start_time": {"hours": 9, "minutes": 0},
            "name": "test",
        },
        _DateTimeComboSchema,
    )
    assert result == {
        "start_date": date(2025, 11, 30),
        "start_time": time(9, 0, 0, 0),
        "name": "test",
    }


def test_coerce_google_types_in_list_field():
    result = _coerce_google_types_to_python(
        {
            "dates": [
                {"year": 2025, "month": 1, "day": 15},
                {"year": 2026, "month": 6, "day": 1},
            ]
        },
        _ListDateSchema,
    )
    assert result == {"dates": [date(2025, 1, 15), date(2026, 6, 1)]}


def test_coerce_google_types_unrelated_dict_unchanged():
    payload = {"status": "active", "count": 5}
    result = _coerce_google_types_to_python(payload)
    assert result == {"status": "active", "count": 5}


def test_coerce_no_false_positive_for_time_like_field_names():
    # A message with fields named hours/minutes but typed as int must NOT become time
    result = _coerce_google_types_to_python(
        {"hours": 4, "minutes": 30}, _FalsePosSchema
    )
    assert result == {"hours": 4, "minutes": 30}


# --- Integration through decode_request_value ---


class DateFilterSchema(BaseModel):
    start_date: date
    end_date: date | None = None


class TimeFilterSchema(BaseModel):
    opens_at: time
    closes_at: time | None = None


class DateTimeFilterSchema(BaseModel):
    start_date: date
    start_time: time | None = None


class DateAliasFilterSchema(BaseModel):
    start_date: date = Field(alias="startDate")


class TimeAliasFilterSchema(BaseModel):
    opens_at: time = Field(alias="opensAt")


def test_decode_request_value_coerces_google_date_dict():
    decoded = decode_request_value(
        {"start_date": {"year": 2025, "month": 11, "day": 30}},
        DateFilterSchema,
    )
    assert decoded.start_date == date(2025, 11, 30)
    assert decoded.end_date is None


def test_decode_request_value_coerces_google_time_dict():
    decoded = decode_request_value(
        {"opens_at": {"hours": 8, "minutes": 30}},
        TimeFilterSchema,
    )
    assert decoded.opens_at == time(8, 30, 0)
    assert decoded.closes_at is None


def test_decode_request_value_coerces_time_when_hours_zero():
    # hours=0 omitted by MessageToDict — the framework must handle this
    decoded = decode_request_value(
        {"opens_at": {"minutes": 45}},
        TimeFilterSchema,
    )
    assert decoded.opens_at == time(0, 45, 0)


def test_decode_request_value_coerces_date_and_time_together():
    decoded = decode_request_value(
        {
            "start_date": {"year": 2025, "month": 6, "day": 15},
            "start_time": {"hours": 9, "minutes": 0},
        },
        DateTimeFilterSchema,
    )
    assert decoded.start_date == date(2025, 6, 15)
    assert decoded.start_time == time(9, 0, 0)


def test_decode_request_value_coerces_google_date_dict_for_alias_field():
    decoded = decode_request_value(
        {"startDate": {"year": 2025, "month": 11, "day": 30}},
        DateAliasFilterSchema,
    )
    assert decoded.start_date == date(2025, 11, 30)


def test_decode_request_value_coerces_google_time_dict_for_alias_field():
    decoded = decode_request_value(
        {"opensAt": {"hours": 8, "minutes": 30}},
        TimeAliasFilterSchema,
    )
    assert decoded.opens_at == time(8, 30, 0)


def test_coerce_google_date_invalid_components_raises():
    # November has 30 days — day=31 must raise a clear error, not silently pass
    with pytest.raises(RequestDecodeError, match="Invalid date"):
        _coerce_google_types_to_python(
            {"value": {"year": 2025, "month": 11, "day": 31}}, _DateSchema
        )


def test_coerce_google_time_invalid_components_raises():
    with pytest.raises(RequestDecodeError, match="Invalid time"):
        _coerce_google_types_to_python(
            {"value": {"hours": 25, "minutes": 0}}, _TimeSchema
        )
