from __future__ import annotations

from enum import Enum
from typing import Any, Callable, Type

from django.db import models
from django.db.models import Model
from pydantic import AliasChoices, BaseModel, ConfigDict, Field, model_validator
from typing_extensions import Self


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


class IntChoiceSchema(BaseModel):
    value: int
    label: str


class TextChoiceSchema(BaseModel):
    value: str
    label: str


class ChoiceEndpointConfig(BaseModel):
    model_config = ConfigDict(arbitrary_types_allowed=True)

    name: str
    source: type[Any]
    description: str | None = None
    permissions: list[object] = Field(default_factory=list)
    response_schema: Type[BaseModel] | None = None

    @model_validator(mode="after")
    def validate_choice_endpoint(self) -> Self:
        if not self.name.strip():
            raise ValueError("Choice endpoint name cannot be empty.")
        if not hasattr(self.source, "choices"):
            raise ValueError(
                "Choice endpoint source must define a 'choices' attribute."
            )
        if self.response_schema is not None:
            fields = self.response_schema.model_fields
            missing = [field for field in ("value", "label") if field not in fields]
            if missing:
                raise ValueError(
                    "Choice endpoint response_schema must define fields: "
                    + ", ".join(missing)
                )
        return self

    def resolve_response_schema(self) -> Type[BaseModel]:
        if self.response_schema is not None:
            return self.response_schema
        if isinstance(self.source, type) and issubclass(
            self.source, models.IntegerChoices
        ):
            return IntChoiceSchema
        if isinstance(self.source, type) and issubclass(
            self.source, models.TextChoices
        ):
            return TextChoiceSchema
        choices = list(self.source.choices)
        if not choices:
            return TextChoiceSchema
        first_value = choices[0][0]
        if isinstance(first_value, int) and not isinstance(first_value, bool):
            return IntChoiceSchema
        return TextChoiceSchema


class ModelServiceConfig(BaseModel):
    """Configuration for model-based gRPC CRUD service generation."""

    model_config = ConfigDict(arbitrary_types_allowed=True)

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
    choice_endpoints: list[ChoiceEndpointConfig] = Field(default_factory=list)

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
