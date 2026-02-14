from __future__ import annotations

from types import SimpleNamespace

from django.db import models
from pydantic import BaseModel, Field

from grpc_extra.model.data_helper import DefaultModelDataHelper
from grpc_extra.model.filtering import ModelFilterSchema
from grpc_extra.model.schemas import ModelServiceConfig


class CreateSchema(BaseModel):
    name: str


class PatchPayload(BaseModel):
    name: str | None = None


class UpdateRequest(BaseModel):
    id: int
    payload: PatchPayload


class FakeInstance:
    def __init__(self, **attrs):
        self.deleted = False
        self.saved = False
        for key, value in attrs.items():
            setattr(self, key, value)

    def save(self):
        self.saved = True

    def delete(self):
        self.deleted = True


class FakeQuerySet:
    def __init__(self, instance):
        self.instance = instance
        self.filter_kwargs = None
        self.filter_args = None

    def all(self):
        return self

    def filter(self, *args, **kwargs):
        self.filter_args = args
        self.filter_kwargs = kwargs
        return self

    def get(self, **kwargs):
        if kwargs.get("id") == self.instance.id:
            return self.instance
        raise LookupError


class FakeManager:
    def __init__(self, instance):
        self.instance = instance
        self.created_payload = None

    def all(self):
        return FakeQuerySet(self.instance)

    def create(self, **kwargs):
        self.created_payload = kwargs
        return FakeInstance(id=2, **kwargs)


class FakeModel(models.Model):
    name = models.CharField(max_length=100)

    class Meta:
        app_label = "tests"
        managed = False


class SimpleListFilter(BaseModel):
    name: str | None = None


class AdvancedListFilter(ModelFilterSchema):
    ids: list[int] | None = Field(default=None, json_schema_extra={"op": "in", "field": "id"})


def _helper(list_filter: type[BaseModel] | None = None) -> DefaultModelDataHelper:
    FakeModel.objects = FakeManager(FakeInstance(id=1, name="old"))
    config = ModelServiceConfig(
        model=FakeModel,
        allowed_endpoints=[],
        list_filter=list_filter,
    )
    return DefaultModelDataHelper(config)


def test_default_data_helper_crud_methods():
    helper = _helper()
    created = helper.create_object(CreateSchema(name="new"))
    assert created.name == "new"
    assert helper.get_object(SimpleNamespace(id=1)).name == "old"

    updated = helper.update_object(
        UpdateRequest(id=1, payload=PatchPayload(name="upd"))
    )
    assert updated.name == "upd"
    assert updated.saved is True

    patched = helper.patch_object(
        UpdateRequest(id=1, payload=PatchPayload(name="patch"))
    )
    assert patched.name == "patch"

    result = helper.delete_object(SimpleNamespace(id=1))
    assert result == {}
    assert helper.get_object(SimpleNamespace(id=1)).deleted is True


def test_list_objects_applies_plain_filter_schema_with_exact_filters():
    helper = _helper(list_filter=SimpleListFilter)
    request = SimpleNamespace(name="old", limit=10, offset=0)
    queryset = helper.list_objects(request)
    assert queryset.filter_kwargs == {"name": "old"}


def test_list_objects_applies_model_filter_schema():
    helper = _helper(list_filter=AdvancedListFilter)
    request = SimpleNamespace(ids=[1, 2], limit=10, offset=0)
    queryset = helper.list_objects(request)
    assert queryset.filter_args
