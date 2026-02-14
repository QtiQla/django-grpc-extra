from __future__ import annotations

from collections.abc import Iterable, Iterator, Mapping
from dataclasses import asdict, is_dataclass
from typing import Any, cast

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
        return dict(payload)

    if isinstance(value, schema):
        return value.model_dump(mode="python", by_alias=True, exclude_none=True)
    if isinstance(value, BaseModel):
        validated = schema.model_validate(value.model_dump(mode="python"))
        return validated.model_dump(mode="python", by_alias=True, exclude_none=True)
    if isinstance(value, Mapping):
        validated = schema.model_validate(dict(value))
        return validated.model_dump(mode="python", by_alias=True, exclude_none=True)
    if is_dataclass(value) and not isinstance(value, type):
        validated = schema.model_validate(asdict(value))
        return validated.model_dump(mode="python", by_alias=True, exclude_none=True)
    if isinstance(value, Model):
        validated = schema.model_validate(value, from_attributes=True)
        return validated.model_dump(mode="python", by_alias=True, exclude_none=True)

    validated = schema.model_validate(value, from_attributes=True)
    return validated.model_dump(mode="python", by_alias=True, exclude_none=True)


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
