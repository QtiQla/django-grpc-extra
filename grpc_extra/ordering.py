from __future__ import annotations

import importlib
from collections.abc import Iterable
from operator import attrgetter, itemgetter
from typing import Any, cast

from django.conf import settings as django_settings
from django.db.models import QuerySet
from pydantic import BaseModel, Field, create_model


class OrderingError(Exception):
    pass


class BaseOrdering:
    @classmethod
    def build_request_schema(
        cls, request_schema: type[BaseModel] | None
    ) -> type[BaseModel]:
        name = (
            f"{request_schema.__name__}WithOrdering"
            if request_schema is not None
            else "OrderingRequest"
        )
        if request_schema is None:
            return create_model(name, ordering=(str | None, Field(default=None)))
        return create_model(
            name,
            __base__=request_schema,
            ordering=(str | None, Field(default=None)),
        )

    def order(self, items: Any, request: BaseModel) -> Any:
        raise NotImplementedError


class Ordering(BaseOrdering):
    def __init__(self, ordering_fields: list[str] | str = "__all__") -> None:
        self.ordering_fields = ordering_fields

    def order(self, items: Any, request: BaseModel) -> Any:
        raw_value = cast(str | None, getattr(request, "ordering", None))
        terms = self._parse_terms(raw_value)
        if not terms:
            return items

        valid_fields = set(self._valid_fields(items))
        if valid_fields:
            invalid = [term for term in terms if term.lstrip("-") not in valid_fields]
            if invalid:
                raise OrderingError(f"Invalid ordering fields: {', '.join(invalid)}")

        if isinstance(items, QuerySet):
            return items.order_by(*terms)

        if isinstance(items, list):
            return self._sort_list(items, terms)

        if isinstance(items, Iterable):
            return self._sort_list(list(items), terms)

        raise OrderingError(f"Result type '{type(items).__name__}' is not orderable.")

    def _sort_list(self, items: list[Any], terms: list[str]) -> list[Any]:
        if not items:
            return items
        is_dict = isinstance(items[0], dict)
        for term in reversed(terms):
            field_name = term.lstrip("-")
            reverse = term.startswith("-")
            getter = itemgetter(field_name) if is_dict else attrgetter(field_name)
            try:
                items.sort(key=getter, reverse=reverse)
            except Exception as exc:
                raise OrderingError(
                    f"Ordering field '{field_name}' is not available on list items."
                ) from exc
        return items

    def _parse_terms(self, value: str | None) -> list[str]:
        if not value:
            return []
        return [item.strip() for item in value.split(",") if item.strip()]

    def _valid_fields(self, items: Any) -> list[str]:
        if self.ordering_fields != "__all__":
            return list(cast(list[str], self.ordering_fields))
        if isinstance(items, QuerySet):
            return [str(field.name) for field in items.model._meta.fields] + [
                str(key) for key in items.query.annotations
            ]
        if isinstance(items, list) and items:
            first = items[0]
            if isinstance(first, BaseModel):
                return list(first.__class__.model_fields.keys())
            if isinstance(first, dict):
                return list(first.keys())
            if hasattr(first, "_meta") and hasattr(first._meta, "fields"):
                return [str(field.name) for field in first._meta.fields]
            attrs = [
                name
                for name in dir(first)
                if not name.startswith("_") and not callable(getattr(first, name))
            ]
            return attrs
        return []


def resolve_ordering_class(value: object | None) -> type[BaseOrdering] | None:
    if value is None:
        return None
    if isinstance(value, BaseOrdering):
        raise OrderingError(
            "Ordering instance is not supported here. "
            "Pass ordering class (e.g. Ordering) to `list_ordering_class` and "
            "pass fields via `list_ordering_fields`."
        )
    if isinstance(value, str):
        module_path, _, attr = value.rpartition(".")
        if not module_path or not attr:
            raise OrderingError(f"Invalid ordering class path: {value}")
        module = importlib.import_module(module_path)
        resolved = getattr(module, attr, None)
        if resolved is None:
            raise OrderingError(f"Ordering class '{value}' was not found.")
        value = resolved
    if not isinstance(value, type) or not issubclass(value, BaseOrdering):
        raise OrderingError("Ordering class must inherit BaseOrdering.")
    return value


def get_default_ordering_class() -> type[BaseOrdering] | None:
    configured = getattr(django_settings, "GRPC_EXTRA", {}) or {}
    value = configured.get("DEFAULT_ORDERING_CLASS", "grpc_extra.ordering.Ordering")
    return resolve_ordering_class(value)
