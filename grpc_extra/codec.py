from __future__ import annotations

from collections.abc import Iterable, Iterator, Mapping
from dataclasses import asdict, is_dataclass
from datetime import date, datetime, time
from decimal import Decimal
from typing import Any, get_args, get_origin, cast
from uuid import UUID

from django.db.models import Model, QuerySet
from pydantic import BaseModel

from .exceptions import RequestDecodeError, ResponseEncodeError


def decode_request_value(value: Any, schema: type[BaseModel] | None) -> Any:
    if schema is None:
        return value
    payload = _to_payload(value)
    try:
        return schema.model_validate(payload)
    except Exception as exc:
        raise RequestDecodeError(f"Failed to decode request: {exc}") from exc


def decode_request_iter(
    request_iter: Iterable[Any], schema: type[BaseModel] | None
) -> Iterator[Any]:
    for item in request_iter:
        yield decode_request_value(item, schema)


def encode_response_value(
    value: Any,
    schema: type[BaseModel] | None,
    response_pb2_cls: type | None,
) -> Any:
    if response_pb2_cls is None:
        return value
    payload = _normalize_response(value, schema)
    try:
        return response_pb2_cls(**payload)
    except Exception as exc:
        raise ResponseEncodeError(f"Failed to encode response: {exc}") from exc


def encode_response_iter(
    values: Iterable[Any],
    schema: type[BaseModel] | None,
    response_pb2_cls: type | None,
) -> Iterator[Any]:
    iterator = getattr(values, "iterator", None)
    if isinstance(values, QuerySet) or callable(iterator):
        iterable: Iterable[Any] = cast(Any, values).iterator()
    else:
        iterable = values
    for item in iterable:
        yield encode_response_value(item, schema, response_pb2_cls)


def _normalize_response(value: Any, schema: type[BaseModel] | None) -> dict[str, Any]:
    if schema is None:
        payload = _to_payload(value)
        if not isinstance(payload, Mapping):
            raise ResponseEncodeError("Response must be mapping-compatible.")
        return cast(dict[str, Any], _coerce_protobuf_compatible(dict(payload)))

    if _is_repeated_items_wrapper_schema(schema) and _is_collection_payload(value):
        validated = schema.model_validate({"items": _materialize_collection(value)})
        return cast(
            dict[str, Any],
            _coerce_protobuf_compatible(
                validated.model_dump(mode="python", by_alias=True, exclude_none=True)
            ),
        )

    if isinstance(value, schema):
        return cast(
            dict[str, Any],
            _coerce_protobuf_compatible(
                value.model_dump(mode="python", by_alias=True, exclude_none=True)
            ),
        )
    if isinstance(value, BaseModel):
        validated = schema.model_validate(value.model_dump(mode="python"))
        return cast(
            dict[str, Any],
            _coerce_protobuf_compatible(
                validated.model_dump(mode="python", by_alias=True, exclude_none=True)
            ),
        )
    if isinstance(value, Mapping):
        validated = schema.model_validate(dict(value))
        return cast(
            dict[str, Any],
            _coerce_protobuf_compatible(
                validated.model_dump(mode="python", by_alias=True, exclude_none=True)
            ),
        )
    if is_dataclass(value) and not isinstance(value, type):
        validated = schema.model_validate(asdict(value))
        return cast(
            dict[str, Any],
            _coerce_protobuf_compatible(
                validated.model_dump(mode="python", by_alias=True, exclude_none=True)
            ),
        )
    if isinstance(value, Model):
        validated = schema.model_validate(value, from_attributes=True)
        return cast(
            dict[str, Any],
            _coerce_protobuf_compatible(
                validated.model_dump(mode="python", by_alias=True, exclude_none=True)
            ),
        )

    validated = schema.model_validate(value, from_attributes=True)
    return cast(
        dict[str, Any],
        _coerce_protobuf_compatible(
            validated.model_dump(mode="python", by_alias=True, exclude_none=True)
        ),
    )


def _to_payload(value: Any) -> Any:
    if isinstance(value, BaseModel):
        return value.model_dump(mode="python", by_alias=True, exclude_none=True)
    if isinstance(value, Mapping):
        return dict(value)
    if is_dataclass(value) and not isinstance(value, type):
        return asdict(value)
    if hasattr(value, "DESCRIPTOR"):
        from google.protobuf.json_format import MessageToDict

        return MessageToDict(
            value,
            preserving_proto_field_name=True,
        )
    return value


def _coerce_protobuf_compatible(value: Any) -> Any:
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, UUID):
        return str(value)
    if isinstance(value, date) and not isinstance(value, datetime):
        return {
            "year": value.year,
            "month": value.month,
            "day": value.day,
        }
    if isinstance(value, time):
        return {
            "hours": value.hour,
            "minutes": value.minute,
            "seconds": value.second,
            "nanos": value.microsecond * 1000,
        }
    if isinstance(value, Mapping):
        return {k: _coerce_protobuf_compatible(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_coerce_protobuf_compatible(v) for v in value]
    if isinstance(value, tuple):
        return tuple(_coerce_protobuf_compatible(v) for v in value)
    return value


def _is_repeated_items_wrapper_schema(schema: type[BaseModel]) -> bool:
    fields = schema.model_fields
    if tuple(fields.keys()) != ("items",):
        return False
    annotation = fields["items"].annotation
    return get_origin(annotation) is list and len(get_args(annotation)) == 1


def _is_collection_payload(value: Any) -> bool:
    if isinstance(value, (str, bytes, bytearray, Mapping, BaseModel)):
        return False
    iterator = getattr(value, "iterator", None)
    if isinstance(value, QuerySet) or callable(iterator):
        return True
    return isinstance(value, Iterable)


def _materialize_collection(value: Any) -> list[Any]:
    iterator = getattr(value, "iterator", None)
    if isinstance(value, QuerySet) or callable(iterator):
        return list(cast(Any, value).iterator())
    return list(cast(Iterable[Any], value))
