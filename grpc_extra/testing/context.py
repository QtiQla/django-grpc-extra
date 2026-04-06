from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import grpc


@dataclass(frozen=True)
class AbortedRpcError(Exception):
    code: grpc.StatusCode
    details: str


class TestServicerContext:
    """Lightweight gRPC servicer context for in-process tests."""

    __test__ = False

    def __init__(
        self,
        *,
        metadata: list[tuple[str, str]] | tuple[tuple[str, str], ...] | None = None,
        **attrs: Any,
    ) -> None:
        self._invocation_metadata = tuple(metadata or ())
        self._initial_metadata: tuple[tuple[str, str], ...] = ()
        self._trailing_metadata: tuple[tuple[str, str], ...] = ()
        self._code = grpc.StatusCode.OK
        self._details = ""
        for key, value in attrs.items():
            setattr(self, key, value)

    def invocation_metadata(self) -> tuple[tuple[str, str], ...]:
        return self._invocation_metadata

    def send_initial_metadata(
        self, metadata: list[tuple[str, str]] | tuple[tuple[str, str], ...]
    ) -> None:
        self._initial_metadata = tuple(metadata)

    def set_trailing_metadata(
        self, metadata: list[tuple[str, str]] | tuple[tuple[str, str], ...]
    ) -> None:
        self._trailing_metadata = tuple(metadata)

    def set_code(self, code: grpc.StatusCode) -> None:
        self._code = code

    def set_details(self, details: str) -> None:
        self._details = details

    def code(self) -> grpc.StatusCode:
        return self._code

    def details(self) -> str:
        return self._details

    def initial_metadata(self) -> tuple[tuple[str, str], ...]:
        return self._initial_metadata

    def trailing_metadata(self) -> tuple[tuple[str, str], ...]:
        return self._trailing_metadata

    def abort(self, code: grpc.StatusCode, details: str):
        self._code = code
        self._details = details
        raise AbortedRpcError(code=code, details=details)
