from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

import grpc
from pydantic import ValidationError

from .ordering import OrderingError
from .searching import SearchingError


class GrpcExtraError(Exception):
    """Base error for grpc_extra runtime conversion and adapter failures."""


class RequestDecodeError(GrpcExtraError):
    """Raised when grpc request payload cannot be decoded into expected schema."""


class ResponseEncodeError(GrpcExtraError):
    """Raised when business result cannot be encoded into grpc response payload."""


@dataclass(frozen=True)
class MappedError:
    code: grpc.StatusCode
    message: str


def default_exception_mapper(exc: Exception) -> MappedError:
    if isinstance(exc, ValidationError):
        return MappedError(grpc.StatusCode.INVALID_ARGUMENT, str(exc))
    if isinstance(exc, RequestDecodeError) and isinstance(
        exc.__cause__, ValidationError
    ):
        return MappedError(grpc.StatusCode.INVALID_ARGUMENT, str(exc.__cause__))
    if isinstance(exc, PermissionError):
        return MappedError(grpc.StatusCode.PERMISSION_DENIED, str(exc))
    if isinstance(exc, (OrderingError, SearchingError)):
        return MappedError(grpc.StatusCode.INVALID_ARGUMENT, str(exc))
    if isinstance(exc, (RequestDecodeError, ResponseEncodeError)):
        return MappedError(grpc.StatusCode.INTERNAL, str(exc))
    return MappedError(grpc.StatusCode.UNKNOWN, str(exc))


def resolve_exception_mapper(
    mapper: Callable[[Exception], MappedError] | None,
) -> Callable[[Exception], MappedError]:
    return mapper or default_exception_mapper
