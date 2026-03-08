from __future__ import annotations

from types import SimpleNamespace

import grpc
import pytest
from django.db import models
from pydantic import BaseModel

from grpc_extra.adapters import ServiceRuntimeAdapter
from grpc_extra.permissions import (
    BasePermission,
    DjangoModelPermissions,
    IsAuthenticated,
    IsAuthenticatedActive,
    resolve_permission,
    resolve_permissions,
)
from grpc_extra.registry import MethodMeta, ServiceDefinition, ServiceMeta


class RequestSchema(BaseModel):
    value: int


class ResponseSchema(BaseModel):
    value: int


class FakePb2:
    def __init__(self, **kwargs):
        self.payload = kwargs


class FakeAbort(Exception):
    pass


class FakeContext:
    def __init__(self, user=None):
        self.user = user

    def abort(self, code, message):
        raise FakeAbort((code, message))


class DenyPermission(BasePermission):
    message = "Denied by has_perm"

    def has_perm(self, request, context, service, method_meta) -> bool:
        return False


class DenyObjectPermission(BasePermission):
    message = "Denied by has_obj_perm"

    def has_obj_perm(self, request, context, service, method_meta, obj) -> bool:
        return False


class PermissionModel(models.Model):
    name = models.CharField(max_length=100)

    class Meta:
        app_label = "tests_permissions"
        managed = False


def _adapter(
    *,
    service_permissions: tuple[BasePermission, ...] = (),
) -> ServiceRuntimeAdapter:
    definition = ServiceDefinition(
        service=object,
        meta=ServiceMeta(
            name="EchoService",
            app_label="echo",
            permissions=service_permissions,
        ),
        methods=[],
    )
    pb2 = SimpleNamespace(DESCRIPTOR=SimpleNamespace(services_by_name={}))
    return ServiceRuntimeAdapter(definition, pb2)


def test_service_level_permission_denies_before_method_execution():
    adapter = _adapter(service_permissions=(DenyPermission(),))
    method_meta = MethodMeta(
        name="Echo",
        handler_name="echo",
        request_schema=RequestSchema,
        response_schema=ResponseSchema,
    )
    wrapper = adapter._wrap_unary_unary(
        lambda request, _context: {"value": request.value},
        method_meta,
        FakePb2,
    )

    with pytest.raises(FakeAbort) as exc:
        wrapper({"value": 1}, FakeContext())
    code, message = exc.value.args[0]
    assert code == grpc.StatusCode.PERMISSION_DENIED
    assert "Denied by has_perm" in message


def test_method_object_permission_denies_for_stream_items():
    adapter = _adapter()
    method_meta = MethodMeta(
        name="StreamValues",
        handler_name="stream_values",
        request_schema=RequestSchema,
        response_schema=ResponseSchema,
        server_streaming=True,
        permissions=(DenyObjectPermission(),),
    )
    wrapper = adapter._wrap_unary_stream(
        lambda _request, _context: [{"value": 1}],
        method_meta,
        FakePb2,
    )

    with pytest.raises(FakeAbort) as exc:
        list(wrapper({"value": 1}, FakeContext()))
    code, message = exc.value.args[0]
    assert code == grpc.StatusCode.PERMISSION_DENIED
    assert "Denied by has_obj_perm" in message


def test_service_level_object_permission_applies_to_detail_methods():
    adapter = _adapter(service_permissions=(DenyObjectPermission(),))
    method_meta = MethodMeta(
        name="Detail",
        handler_name="detail",
        request_schema=RequestSchema,
        response_schema=ResponseSchema,
    )
    wrapper = adapter._wrap_unary_unary(
        lambda request, _context: {"value": request.value},
        method_meta,
        FakePb2,
    )

    with pytest.raises(FakeAbort) as exc:
        wrapper({"value": 1}, FakeContext())
    code, message = exc.value.args[0]
    assert code == grpc.StatusCode.PERMISSION_DENIED
    assert "Denied by has_obj_perm" in message


def test_is_authenticated_and_active_permissions():
    anonymous = FakeContext(user=None)
    inactive = FakeContext(
        user=SimpleNamespace(
            is_authenticated=True, is_active=False, has_perms=lambda _: True
        )
    )
    active = FakeContext(
        user=SimpleNamespace(
            is_authenticated=True, is_active=True, has_perms=lambda _: True
        )
    )
    meta = MethodMeta(name="Echo", handler_name="echo")

    assert IsAuthenticated().has_perm(None, anonymous, object(), meta) is False
    assert IsAuthenticatedActive().has_perm(None, inactive, object(), meta) is False
    assert IsAuthenticatedActive().has_perm(None, active, object(), meta) is True


def test_django_model_permissions_maps_model_service_methods():
    captured = {}

    def has_perms(perms):
        captured["perms"] = perms
        return True

    user = SimpleNamespace(is_authenticated=True, has_perms=has_perms)
    context = FakeContext(user=user)
    service = SimpleNamespace(config=SimpleNamespace(model=PermissionModel))
    method_meta = MethodMeta(name="Create", handler_name="create")

    assert (
        DjangoModelPermissions().has_perm(None, context, service, method_meta) is True
    )
    assert captured["perms"] == ["tests_permissions.add_permissionmodel"]


def test_permission_resolution_supports_class_instance_and_import_path():
    resolved_single = resolve_permission("grpc_extra.permissions.IsAuthenticatedActive")
    assert isinstance(resolved_single, IsAuthenticatedActive)
    resolved_many = resolve_permissions([IsAuthenticated, IsAuthenticatedActive()])
    assert len(resolved_many) == 2
    assert isinstance(resolved_many[0], IsAuthenticated)
