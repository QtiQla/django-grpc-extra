from __future__ import annotations

import importlib
import operator
import re
from functools import reduce
from typing import Any, Callable, cast

from django.conf import settings as django_settings
from django.db.models import Q, QuerySet
from django.db.models.constants import LOOKUP_SEP
from pydantic import BaseModel, Field, create_model


def _istartswith(a: str, b: str) -> bool:
    return a.lower().startswith(b.lower())


def _isiexact(a: str, b: str) -> bool:
    return a.lower() == b.lower()


def _isiregex(a: str, b: str) -> bool:
    return bool(re.search(b, a, re.IGNORECASE))


def _isicontains(a: str, b: str) -> bool:
    return b.lower() in a.lower()


class SearchingError(Exception):
    pass


class BaseSearching:
    fields_param_name: str = "search_fields"
    fields_required: bool = True

    @classmethod
    def build_request_schema(
        cls, request_schema: type[BaseModel] | None
    ) -> type[BaseModel]:
        name = (
            f"{request_schema.__name__}WithSearch"
            if request_schema is not None
            else "SearchingRequest"
        )
        if request_schema is None:
            return create_model(name, search=(str | None, Field(default=None)))
        return create_model(
            name,
            __base__=request_schema,
            search=(str | None, Field(default=None)),
        )

    def search(self, items: Any, request: BaseModel) -> Any:
        raise NotImplementedError


class Searching(BaseSearching):
    lookup_prefixes = {
        "^": "istartswith",
        "=": "iexact",
        "@": "search",
        "$": "iregex",
    }
    lookup_prefixes_list = {
        "^": _istartswith,
        "=": _isiexact,
        "$": _isiregex,
    }

    def __init__(self, search_fields: list[str] | None = None) -> None:
        self.search_fields = search_fields or []

    def search(self, items: Any, request: BaseModel) -> Any:
        search_value = cast(str | None, getattr(request, "search", None))
        terms = self._get_search_terms(search_value)
        if not self.search_fields or not terms:
            return items

        if isinstance(items, QuerySet):
            conditions = self._conditions_for_queryset(terms)
            return items.filter(reduce(operator.and_, conditions))

        if isinstance(items, list):
            return self._search_list(items, terms)

        return items

    def _get_search_terms(self, value: str | None) -> list[str]:
        if not value:
            return []
        value = value.replace("\x00", "")
        value = value.replace(",", " ")
        return [term for term in value.split() if term]

    def _construct_search_lookup(self, field_name: str) -> str:
        lookup = self.lookup_prefixes.get(field_name[0])
        if lookup:
            field_name = field_name[1:]
        else:
            lookup = "icontains"
        return LOOKUP_SEP.join([field_name, lookup])

    def _conditions_for_queryset(self, terms: list[str]) -> list[Q]:
        orm_lookups = [
            self._construct_search_lookup(field) for field in self.search_fields
        ]
        conditions: list[Q] = []
        for term in terms:
            queries = [Q(**{lookup: term}) for lookup in orm_lookups]
            conditions.append(reduce(operator.or_, queries))
        return conditions

    def _search_list(self, items: list[Any], terms: list[str]) -> list[Any]:
        lookups = self._construct_list_lookups()
        result: list[Any] = []
        for item in items:
            if self._item_matches(item, lookups, terms):
                result.append(item)
        return result

    def _construct_list_lookups(self) -> dict[str, Callable[[str, str], bool]]:
        def get_lookup(prefix: str) -> Callable[[str, str], bool]:
            return self.lookup_prefixes_list.get(prefix, _isicontains)

        out: dict[str, Callable[[str, str], bool]] = {}
        for field in self.search_fields:
            if self.lookup_prefixes_list.get(field[0]):
                out[field[1:]] = get_lookup(field[0])
            else:
                out[field] = get_lookup(field[0] if field else "")
        return out

    def _item_matches(
        self,
        item: Any,
        lookups: dict[str, Callable[[str, str], bool]],
        terms: list[str],
    ) -> bool:
        is_dict = isinstance(item, dict)
        for term in terms:
            term_match = False
            for field_name, lookup in lookups.items():
                try:
                    raw_value = (
                        item[field_name] if is_dict else getattr(item, field_name)
                    )
                except Exception as exc:
                    raise SearchingError(
                        f"Search field '{field_name}' is not available on list items."
                    ) from exc
                value = str(raw_value)
                if lookup(value, term):
                    term_match = True
                    break
            if not term_match:
                return False
        return True


def resolve_searching_class(value: object | None) -> type[BaseSearching] | None:
    if value is None:
        return None
    if isinstance(value, BaseSearching):
        raise SearchingError(
            "Searching instance is not supported here. "
            "Pass searching class (e.g. Searching) to `list_searching_class` and "
            "pass fields via `list_search_fields`."
        )
    if isinstance(value, str):
        module_path, _, attr = value.rpartition(".")
        if not module_path or not attr:
            raise SearchingError(f"Invalid searching class path: {value}")
        module = importlib.import_module(module_path)
        resolved = getattr(module, attr, None)
        if resolved is None:
            raise SearchingError(f"Searching class '{value}' was not found.")
        value = resolved
    if not isinstance(value, type) or not issubclass(value, BaseSearching):
        raise SearchingError("Searching class must inherit BaseSearching.")
    return value


def get_default_searching_class() -> type[BaseSearching] | None:
    configured = getattr(django_settings, "GRPC_EXTRA", {}) or {}
    value = configured.get("DEFAULT_SEARCHING_CLASS", "grpc_extra.searching.Searching")
    return resolve_searching_class(value)
