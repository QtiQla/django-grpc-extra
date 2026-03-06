from __future__ import annotations

from abc import ABC, abstractmethod

from django.db.models import QuerySet
from pydantic import BaseModel
from typing import cast

from .filtering import ModelFilterSchema
from .schemas import ModelServiceConfig


class ModelDataHelper(ABC):
    """Abstraction for model CRUD operations used by ModelService."""

    def __init__(self, config: ModelServiceConfig) -> None:
        self.config = config

    @abstractmethod
    def list_objects(self, request: BaseModel | None) -> QuerySet:
        raise NotImplementedError

    @abstractmethod
    def get_object(self, request: BaseModel):
        raise NotImplementedError

    @abstractmethod
    def create_object(self, request: BaseModel):
        raise NotImplementedError

    @abstractmethod
    def update_object(self, request: BaseModel):
        raise NotImplementedError

    @abstractmethod
    def patch_object(self, request: BaseModel):
        raise NotImplementedError

    @abstractmethod
    def delete_object(self, request: BaseModel):
        raise NotImplementedError


class DefaultModelDataHelper(ModelDataHelper):
    """Default CRUD implementation backed by Django ORM."""

    def get_queryset(self) -> QuerySet:
        return self._resolve_queryset(self.config.queryset, option_name="queryset")

    def get_detail_queryset(self) -> QuerySet:
        configured = self.config.detail_queryset
        if configured is None:
            return self.get_queryset()
        return self._resolve_queryset(configured, option_name="detail_queryset")

    def _resolve_queryset(self, configured, *, option_name: str) -> QuerySet:
        if configured is None:
            return self.config.model.objects.all()
        queryset = configured() if callable(configured) else configured
        if queryset is None or not hasattr(queryset, "all"):
            raise TypeError(
                f"ModelServiceConfig.{option_name} must be a QuerySet-like object or callable returning it."
            )
        return cast(QuerySet, queryset.all())

    def get_lookup_value(self, request: BaseModel):
        return getattr(request, self.config.lookup_field)

    def list_objects(self, request: BaseModel | None) -> QuerySet:
        queryset = self.get_queryset()
        filter_schema = self.config.list_filter
        if request is None or filter_schema is None:
            return queryset

        filter_payload = {
            field_name: getattr(request, field_name, None)
            for field_name in filter_schema.model_fields
        }
        filter_request = filter_schema.model_validate(filter_payload)
        if isinstance(filter_request, ModelFilterSchema):
            return cast(QuerySet, filter_request.filter_queryset(queryset))

        filter_kwargs = {
            key: value for key, value in filter_payload.items() if value is not None
        }
        if not filter_kwargs:
            return queryset
        return queryset.filter(**filter_kwargs)

    def get_object(self, request: BaseModel):
        lookup_value = self.get_lookup_value(request)
        return self.get_detail_queryset().get(
            **{self.config.lookup_field: lookup_value}
        )

    def create_object(self, request: BaseModel):
        payload = request.model_dump(mode="python", by_alias=True, exclude_none=True)
        return self.config.model.objects.create(**payload)

    def update_object(self, request: BaseModel):
        instance = self.get_queryset().get(
            **{self.config.lookup_field: self.get_lookup_value(request)}
        )
        payload_model = getattr(request, "payload")
        payload = payload_model.model_dump(
            mode="python",
            by_alias=True,
            exclude_none=True,
            exclude_unset=False,
        )
        for key, value in payload.items():
            setattr(instance, key, value)
        instance.save()
        return instance

    def patch_object(self, request: BaseModel):
        instance = self.get_queryset().get(
            **{self.config.lookup_field: self.get_lookup_value(request)}
        )
        payload_model = getattr(request, "payload")
        payload = payload_model.model_dump(
            mode="python",
            by_alias=True,
            exclude_none=True,
            exclude_unset=True,
        )
        for key, value in payload.items():
            setattr(instance, key, value)
        instance.save()
        return instance

    def delete_object(self, request: BaseModel):
        instance = self.get_queryset().get(
            **{self.config.lookup_field: self.get_lookup_value(request)}
        )
        instance.delete()
        return {}
