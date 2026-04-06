from __future__ import annotations

import inspect
from dataclasses import dataclass
from typing import Any

import grpc


def message_to_dict(message: Any) -> Any:
    if message is None:
        return None
    if isinstance(message, dict):
        return dict(message)
    payload = getattr(message, "payload", None)
    if isinstance(payload, dict):
        return dict(payload)
    if hasattr(message, "DESCRIPTOR"):
        from google.protobuf.json_format import MessageToDict

        kwargs: dict[str, Any] = {"preserving_proto_field_name": True}
        params = inspect.signature(MessageToDict).parameters
        if "always_print_fields_with_no_presence" in params:
            kwargs["always_print_fields_with_no_presence"] = True
        elif "including_default_value_fields" in params:
            kwargs["including_default_value_fields"] = True
        return MessageToDict(message, **kwargs)
    return message


@dataclass(frozen=True)
class GrpcTestResponse:
    message: Any
    code: grpc.StatusCode
    details: str = ""
    initial_metadata: tuple[tuple[str, str], ...] = ()
    trailing_metadata: tuple[tuple[str, str], ...] = ()

    @property
    def ok(self) -> bool:
        return bool(self.code == grpc.StatusCode.OK)

    @property
    def data(self) -> Any:
        return message_to_dict(self.message)

    def json(self) -> Any:
        return self.data

    def assert_ok(self) -> "GrpcTestResponse":
        if not self.ok:
            raise AssertionError(
                f"Expected OK response, got {self.code.name}: {self.details}"
            )
        return self
