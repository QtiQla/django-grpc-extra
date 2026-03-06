from __future__ import annotations

import pytest
from pydantic import BaseModel

from grpc_extra.ordering import Ordering, OrderingError, resolve_ordering_class
from grpc_extra.searching import Searching, SearchingError, resolve_searching_class


class Item(BaseModel):
    name: str
    value: int


def test_ordering_sorts_list_and_supports_desc():
    schema = Ordering.build_request_schema(None)
    ordering = Ordering(ordering_fields=["value"])
    result = ordering.order(
        [{"value": 2}, {"value": 1}],
        schema(ordering="-value"),
    )
    assert [x["value"] for x in result] == [2, 1]


def test_ordering_rejects_invalid_fields():
    schema = Ordering.build_request_schema(None)
    ordering = Ordering(ordering_fields=["value"])
    with pytest.raises(OrderingError):
        ordering.order([{"value": 1}], schema(ordering="name"))


def test_resolve_ordering_class_rejects_instance_with_helpful_message():
    with pytest.raises(OrderingError, match="list_ordering_fields"):
        resolve_ordering_class(Ordering(["name"]))


def test_searching_filters_list_by_terms():
    schema = Searching.build_request_schema(None)
    searching = Searching(search_fields=["name"])
    result = searching.search(
        [{"name": "alpha"}, {"name": "beta"}],
        schema(search="alp"),
    )
    assert len(result) == 1
    assert result[0]["name"] == "alpha"


def test_searching_rejects_missing_fields_on_list_item():
    schema = Searching.build_request_schema(None)
    searching = Searching(search_fields=["name"])
    with pytest.raises(SearchingError):
        searching.search([{"title": "x"}], schema(search="x"))


def test_resolve_searching_class_rejects_instance_with_helpful_message():
    with pytest.raises(SearchingError, match="list_search_fields"):
        resolve_searching_class(Searching(["name"]))
