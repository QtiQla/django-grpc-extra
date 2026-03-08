from __future__ import annotations

from pydantic import Field

from grpc_extra.model.filtering import ModelFilterSchema


class ExampleFilter(ModelFilterSchema):
    name: str | None = None
    ids: list[int] | None = Field(
        default=None, json_schema_extra={"op": "in", "field": "id"}
    )
    blocked_ids: list[int] | None = Field(
        default=None,
        json_schema_extra={"op": "not_in", "field": "id"},
    )
    min_age: int | None = Field(
        default=None, json_schema_extra={"op": "gte", "field": "age"}
    )


class FakeQuerySet:
    def __init__(self):
        self.last_args = ()
        self.last_kwargs = {}

    def filter(self, *args, **kwargs):
        self.last_args = args
        self.last_kwargs = kwargs
        return self


def test_model_filter_schema_builds_supported_lookups():
    payload = ExampleFilter(
        name="a",
        ids=[1, 2],
        blocked_ids=[3],
        min_age=18,
    )
    q = payload.to_q()
    rendered = str(q)
    assert "name" in rendered
    assert "id__in" in rendered
    assert "age__gte" in rendered
    assert "NOT" in rendered


def test_model_filter_schema_applies_query_to_queryset():
    qs = FakeQuerySet()
    payload = ExampleFilter(name="x")
    payload.filter_queryset(qs)
    assert qs.last_args
    assert not qs.last_kwargs
