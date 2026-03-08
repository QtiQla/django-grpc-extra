from __future__ import annotations

from enum import Enum
from typing import Callable, Self, Type

from django.db.models import Model
from pydantic import AliasChoices, BaseModel, Field, model_validator


class StringEnum(str, Enum):
    """Python 3.10+ compatible string enum base."""


class AllowedEndpoints(StringEnum):
    STREAM_LIST = "stream_list"
    CREATE = "create"
    DETAIL = "detail"
    UPDATE = "update"
    PATCH = "patch"
    DELETE = "delete"
    LIST = "list"


class ModelServiceConfig(BaseModel):
    """Configuration for model-based gRPC CRUD service generation."""

    model: Type[Model]
    allowed_endpoints: list[AllowedEndpoints] = Field(
        default=[
            AllowedEndpoints.STREAM_LIST,
            AllowedEndpoints.CREATE,
            AllowedEndpoints.DETAIL,
            AllowedEndpoints.UPDATE,
            AllowedEndpoints.PATCH,
            AllowedEndpoints.DELETE,
            AllowedEndpoints.LIST,
        ],
    )
    list_schema: Type[BaseModel] | None = None
    list_filter: Type[BaseModel] | None = None
    detail_schema: Type[BaseModel] | None = None
    create_schema: Type[BaseModel] | None = None
    update_schema: Type[BaseModel] | None = None
    patch_schema: Type[BaseModel] | None = None
    lookup_field: str = "id"
    queryset: object | Callable[[], object] | None = None
    detail_queryset: object | Callable[[], object] | None = None
    list_pagination_class: object | None = "default"
    list_ordering_class: object | None = None
    list_ordering_fields: list[str] | str = "__all__"
    list_searching_class: object | None = None
    list_search_fields: list[str] = Field(
        default_factory=list,
        validation_alias=AliasChoices("list_search_fields", "list_searching_fields"),
    )
    permissions: list[object] = Field(default_factory=list)
    endpoint_permissions: dict[AllowedEndpoints, list[object]] = Field(
        default_factory=dict
    )

    @model_validator(mode="after")
    def validate_exists_schemas_by_allowed_endpoints(self) -> Self:
        if not self.allowed_endpoints:
            return self
        required_by_endpoint = {
            AllowedEndpoints.STREAM_LIST: ("list_schema",),
            AllowedEndpoints.LIST: ("list_schema",),
            AllowedEndpoints.DETAIL: ("detail_schema",),
            AllowedEndpoints.CREATE: ("create_schema", "detail_schema"),
            AllowedEndpoints.UPDATE: ("update_schema", "detail_schema"),
            AllowedEndpoints.PATCH: ("patch_schema", "detail_schema"),
            AllowedEndpoints.DELETE: (),
        }
        for endpoint in self.allowed_endpoints:
            for field_name in required_by_endpoint[endpoint]:
                if getattr(self, field_name) is None:
                    raise ValueError(
                        f"Field '{field_name}' is required when endpoint '{endpoint.value}' is enabled."
                    )
        return self
