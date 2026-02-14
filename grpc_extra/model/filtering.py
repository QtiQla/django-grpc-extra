from __future__ import annotations

from collections.abc import Iterable
from typing import Any, ClassVar, Literal, cast

from django.db.models import Q
from pydantic import BaseModel

LookupOperator = Literal["exact", "in", "not_in", "lt", "gt", "lte", "gte"]
ExpressionConnector = Literal["AND", "OR", "XOR"]


class ModelFilterSchema(BaseModel):
    """Base class for declarative queryset filters used by ModelService list methods."""

    ignore_none: ClassVar[bool] = True
    expression_connector: ClassVar[ExpressionConnector] = "AND"

    def custom_expression(self) -> Q:
        raise NotImplementedError

    def to_q(self) -> Q:
        try:
            return self.custom_expression()
        except NotImplementedError:
            return self._connect_fields()

    def filter_queryset(self, queryset):
        return queryset.filter(self.to_q())

    def _resolve_field_q(self, field_name: str, field_value) -> Q:
        custom_resolver = getattr(self, f"filter_{field_name}", None)
        if callable(custom_resolver):
            return cast(Q, custom_resolver(field_value))

        field = self.__class__.model_fields[field_name]
        extra_raw = field.json_schema_extra
        extra: dict[str, Any] = extra_raw if isinstance(extra_raw, dict) else {}
        target_field = cast(str, extra.get("field", field_name))
        lookup = cast(str | None, extra.get("lookup"))
        op = cast(LookupOperator, extra.get("op", "exact"))
        exclude = bool(extra.get("exclude", False))

        if lookup is not None:
            lookup_name = f"{target_field}{lookup}" if lookup.startswith("__") else lookup
            q = Q(**{lookup_name: field_value})
            return ~q if exclude else q

        if op == "exact":
            q = Q(**{target_field: field_value})
        elif op == "in":
            values = list(cast(Iterable, field_value))
            q = Q(**{f"{target_field}__in": values})
        elif op == "not_in":
            values = list(cast(Iterable, field_value))
            q = ~Q(**{f"{target_field}__in": values})
        elif op == "lt":
            q = Q(**{f"{target_field}__lt": field_value})
        elif op == "gt":
            q = Q(**{f"{target_field}__gt": field_value})
        elif op == "lte":
            q = Q(**{f"{target_field}__lte": field_value})
        elif op == "gte":
            q = Q(**{f"{target_field}__gte": field_value})
        else:
            raise ValueError(f"Unsupported filter operator '{op}' for field '{field_name}'.")

        return ~q if exclude else q

    def _connect_fields(self) -> Q:
        q = Q()
        connector = self.expression_connector
        for field_name in self.__class__.model_fields:
            filter_value = getattr(self, field_name)
            if filter_value is None and self.ignore_none:
                continue
            field_q = self._resolve_field_q(field_name, filter_value)
            if connector == "OR":
                q = q | field_q
            elif connector == "XOR":
                q = q ^ field_q
            else:
                q = q & field_q
        return q
