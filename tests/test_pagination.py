from __future__ import annotations

import pytest
from django.conf import settings
from pydantic import BaseModel

from grpc_extra.pagination import (
    LimitOffsetPagination,
    PaginationError,
    get_default_pagination_class,
    resolve_pagination_class,
)


class ItemSchema(BaseModel):
    value: int


def test_limit_offset_paginate_iterable():
    request_schema = LimitOffsetPagination.build_request_schema(None)
    request = request_schema(limit=2, offset=1)
    payload = LimitOffsetPagination.paginate(
        [{"value": 1}, {"value": 2}, {"value": 3}],
        request,
    )
    assert payload["count"] == 3
    assert payload["limit"] == 2
    assert payload["offset"] == 1
    assert len(payload["results"]) == 2


def test_limit_offset_paginate_rejects_non_iterable():
    request_schema = LimitOffsetPagination.build_request_schema(None)
    request = request_schema(limit=2, offset=0)
    with pytest.raises(PaginationError):
        LimitOffsetPagination.paginate(123, request)


def test_resolve_pagination_class_variants():
    assert resolve_pagination_class(LimitOffsetPagination) is LimitOffsetPagination
    assert (
        resolve_pagination_class("grpc_extra.pagination.LimitOffsetPagination")
        is LimitOffsetPagination
    )
    assert resolve_pagination_class(None) is None
    with pytest.raises(PaginationError):
        resolve_pagination_class("bad")
    with pytest.raises(PaginationError):
        resolve_pagination_class(object)


def test_get_default_pagination_class_from_settings():
    settings.GRPC_EXTRA = {
        "DEFAULT_PAGINATION_CLASS": "grpc_extra.pagination.LimitOffsetPagination"
    }
    assert get_default_pagination_class() is LimitOffsetPagination
