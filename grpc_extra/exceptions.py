from __future__ import annotations

import importlib
import inspect
from collections.abc import Callable
from dataclasses import dataclass
from typing import cast

import grpc
from django.core.exceptions import ObjectDoesNotExist
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
    if isinstance(exc, ObjectDoesNotExist):
        return MappedError(grpc.StatusCode.NOT_FOUND, str(exc))
    if isinstance(exc, PermissionError):
        return MappedError(grpc.StatusCode.PERMISSION_DENIED, str(exc))
    if isinstance(exc, (OrderingError, SearchingError)):
        return MappedError(grpc.StatusCode.INVALID_ARGUMENT, str(exc))
    if isinstance(exc, (RequestDecodeError, ResponseEncodeError)):
        return MappedError(grpc.StatusCode.INTERNAL, str(exc))
    return MappedError(grpc.StatusCode.UNKNOWN, str(exc))


def resolve_exception_mapper(
    mapper: Callable[[Exception], MappedError] | str | None,
) -> Callable[[Exception], MappedError]:
    if mapper is None:
        return default_exception_mapper
    if isinstance(mapper, str):
        module_path, _, attr = mapper.rpartition(".")
        if not module_path or not attr:
            raise ValueError(f"Invalid exception mapper path: {mapper}")
        module = importlib.import_module(module_path)
        resolved = getattr(module, attr, None)
        if not callable(resolved) or inspect.isclass(resolved):
            raise ValueError(f"Exception mapper '{mapper}' is not callable")
        return cast(Callable[[Exception], MappedError], resolved)
    if inspect.isclass(mapper):
        raise ValueError("Exception mapper must be a function/callable, not a class.")
    return mapper
