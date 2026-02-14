from __future__ import annotations

import importlib
from abc import ABC, abstractmethod
from collections.abc import Iterable
from typing import Any

from django.conf import settings as django_settings
from django.db.models import QuerySet
from pydantic import BaseModel, Field, create_model


class PaginationError(Exception):
    pass


class BasePagination(ABC):
    """Base class for gRPC pagination adapters."""

    @classmethod
    @abstractmethod
    def build_request_schema(
        cls, request_schema: type[BaseModel] | None
    ) -> type[BaseModel]:
        raise NotImplementedError

    @classmethod
    @abstractmethod
    def build_response_schema(cls, response_schema: type[BaseModel]) -> type[BaseModel]:
        raise NotImplementedError

    @classmethod
    @abstractmethod
    def paginate(cls, result: Any, request: BaseModel) -> dict[str, Any]:
        raise NotImplementedError


class LimitOffsetPagination(BasePagination):
    """Default limit/offset pagination for unary list endpoints."""

    default_limit = 100
    max_limit = 1000

    @classmethod
    def build_request_schema(
        cls, request_schema: type[BaseModel] | None
    ) -> type[BaseModel]:
        name = (
            f"{request_schema.__name__}WithLimitOffset"
            if request_schema is not None
            else "LimitOffsetRequest"
        )
        if request_schema is None:
            return create_model(
                name,
                limit=(int, Field(default=cls.default_limit, ge=1)),
                offset=(int, Field(default=0, ge=0)),
            )
        return create_model(
            name,
            __base__=request_schema,
            limit=(int, Field(default=cls.default_limit, ge=1)),
            offset=(int, Field(default=0, ge=0)),
        )

    @classmethod
    def build_response_schema(cls, response_schema: type[BaseModel]) -> type[BaseModel]:
        return create_model(
            f"{response_schema.__name__}Paginated",
            count=(int, ...),
            limit=(int, ...),
            offset=(int, ...),
            results=(list[response_schema], ...),  # type: ignore[valid-type]
        )

    @classmethod
    def paginate(cls, result: Any, request: BaseModel) -> dict[str, Any]:
        limit = min(
            max(int(getattr(request, "limit", cls.default_limit)), 1), cls.max_limit
        )
        offset = max(int(getattr(request, "offset", 0)), 0)

        if isinstance(result, QuerySet):
            count = result.count()
            page_items = list(result[offset : offset + limit])
            return {
                "count": count,
                "limit": limit,
                "offset": offset,
                "results": page_items,
            }

        if isinstance(result, Iterable):
            items = list(result)
            count = len(items)
            return {
                "count": count,
                "limit": limit,
                "offset": offset,
                "results": items[offset : offset + limit],
            }

        raise PaginationError(
            f"Result type '{type(result).__name__}' is not paginatable."
        )


def resolve_pagination_class(value: object | None) -> type[BasePagination] | None:
    if value is None:
        return None
    if isinstance(value, str):
        module_path, _, attr = value.rpartition(".")
        if not module_path or not attr:
            raise PaginationError(f"Invalid pagination class path: {value}")
        module = importlib.import_module(module_path)
        resolved = getattr(module, attr, None)
        if resolved is None:
            raise PaginationError(f"Pagination class '{value}' was not found.")
        value = resolved
    if not isinstance(value, type) or not issubclass(value, BasePagination):
        raise PaginationError("Pagination class must inherit BasePagination.")
    return value


def get_default_pagination_class() -> type[BasePagination] | None:
    configured = getattr(django_settings, "GRPC_EXTRA", {}) or {}
    value = configured.get(
        "DEFAULT_PAGINATION_CLASS",
        "grpc_extra.pagination.LimitOffsetPagination",
    )
    return resolve_pagination_class(value)
