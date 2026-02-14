from __future__ import annotations

import builtins
from types import SimpleNamespace

import pytest

from grpc_extra.constants import GRPC_SERVICE_META
from grpc_extra.main import GrpcExtra, _ensure_django_ready, _run_reloaded_server
from grpc_extra.registry import (
    MethodMeta,
    ServiceDefinition,
    ServiceMeta,
    ServiceNotDecoratedError,
    registry,
)


class DummyServer:
    def __init__(self):
        self.registered = []


class DummyPb2:
    DESCRIPTOR = SimpleNamespace(
        services_by_name={
            "ExampleService": SimpleNamespace(
                methods_by_name={
                    "Ping": SimpleNamespace(
                        output_type=SimpleNamespace(name="PingResponse")
                    )
                }
            )
        }
    )
    PingResponse = dict


def setup_function():
    registry.clear()


def test_safe_import_and_iter_decorated_services():
    class Svc:
        pass

    setattr(Svc, GRPC_SERVICE_META, object())
    module = SimpleNamespace(Svc=Svc, Other=object())
    discovered = list(GrpcExtra._iter_decorated_services(module))
    assert discovered == [Svc]
    assert GrpcExtra._safe_import("module.that.does.not.exist") is None


def test_apply_raises_when_proto_path_missing():
    definition = ServiceDefinition(
        service=object,
        meta=ServiceMeta(name="Broken", app_label="example", proto_path=None),
        methods=[],
    )
    registry._services.append(definition)
    with pytest.raises(ServiceNotDecoratedError):
        GrpcExtra().apply(DummyServer())


def test_apply_registers_servicer(monkeypatch):
    class ExampleService:
        def ping(self, request, context):
            return {"ok": True}

    definition = ServiceDefinition(
        service=ExampleService,
        meta=ServiceMeta(
            name="ExampleService",
            app_label="example_app",
            package="example_app",
            proto_path="grpc/proto/example_app.proto",
        ),
        methods=[
            MethodMeta(
                name="Ping",
                handler_name="ping",
                request_schema=None,
                response_schema=None,
            )
        ],
    )
    registry._services.append(definition)

    added = []

    def _add_servicer(servicer, server):
        server.registered.append(servicer)
        added.append(servicer)

    monkeypatch.setattr(
        "grpc_extra.main.importlib.import_module",
        lambda path: (
            SimpleNamespace(add_ExampleServiceServicer_to_server=_add_servicer)
            if path.endswith("_pb2_grpc")
            else DummyPb2
        ),
    )

    server = DummyServer()
    registered = GrpcExtra().apply(server)
    assert registered == ["ExampleService"]
    assert added
    assert hasattr(added[0], "Ping")


def test_apply_raises_when_registration_function_missing(monkeypatch):
    definition = ServiceDefinition(
        service=object,
        meta=ServiceMeta(
            name="ExampleService",
            app_label="example",
            proto_path="grpc/proto/example.proto",
        ),
        methods=[],
    )
    registry._services.append(definition)

    monkeypatch.setattr(
        "grpc_extra.main.importlib.import_module",
        lambda path: SimpleNamespace() if path.endswith("_pb2_grpc") else DummyPb2,
    )
    with pytest.raises(ServiceNotDecoratedError):
        GrpcExtra().apply(DummyServer())


def test_ensure_django_ready_requires_settings_module(monkeypatch):
    monkeypatch.setattr("grpc_extra.main.apps.ready", False)
    monkeypatch.delenv("DJANGO_SETTINGS_MODULE", raising=False)
    with pytest.raises(ServiceNotDecoratedError):
        _ensure_django_ready()


def test_ensure_django_ready_noop_when_apps_ready(monkeypatch):
    called = {"setup": False}
    monkeypatch.setattr("grpc_extra.main.apps.ready", True)
    monkeypatch.setattr(
        "grpc_extra.main.django.setup", lambda: called.update(setup=True)
    )
    _ensure_django_ready()
    assert called["setup"] is False


def test_ensure_django_ready_calls_setup(monkeypatch):
    called = {"setup": False}
    monkeypatch.setattr("grpc_extra.main.apps.ready", False)
    monkeypatch.setenv("DJANGO_SETTINGS_MODULE", "tests.settings")
    monkeypatch.setattr(
        "grpc_extra.main.django.setup", lambda: called.update(setup=True)
    )
    _ensure_django_ready()
    assert called["setup"] is True


def test_run_reloaded_server_invokes_grpc_extra(monkeypatch):
    called = {"ensure": False, "run": False}

    class DummyExtra:
        def __init__(self, pattern):
            assert pattern == "{app}.grpc.services"

        def run_server(self, **kwargs):
            called["run"] = True
            assert kwargs["reload"] is False
            assert kwargs["auto_discover"] is False

    monkeypatch.setattr(
        "grpc_extra.main._ensure_django_ready", lambda: called.update(ensure=True)
    )
    monkeypatch.setattr("grpc_extra.main.GrpcExtra", DummyExtra)
    _run_reloaded_server("{app}.grpc.services", {"auto_discover": False})
    assert called == {"ensure": True, "run": True}


def test_auto_discover_services_registers_discovered_services(monkeypatch):
    class DecoratedService:
        pass

    setattr(
        DecoratedService,
        GRPC_SERVICE_META,
        ServiceMeta(name="DecoratedService", app_label="app"),
    )

    app_conf = SimpleNamespace(name="example_app", label="example", path="/tmp/example")
    extra = GrpcExtra(pattern="{app}.grpc.services")
    monkeypatch.setattr("grpc_extra.main.apps.get_app_configs", lambda: [app_conf])
    monkeypatch.setattr(
        extra,
        "_safe_import",
        lambda module_path: (
            SimpleNamespace(DecoratedService=DecoratedService)
            if module_path == "example_app.grpc.services"
            else None
        ),
    )
    monkeypatch.setattr(
        extra,
        "register_service",
        lambda service: ServiceDefinition(
            service=service,
            meta=getattr(service, GRPC_SERVICE_META),
            methods=[],
        ),
    )
    assert extra.auto_discover_services() is extra


def test_safe_import_reraises_unrelated_module_not_found(monkeypatch):
    def _boom(_path):
        err = ModuleNotFoundError("missing")
        err.name = "another.module"
        raise err

    monkeypatch.setattr("grpc_extra.main.importlib.import_module", _boom)
    with pytest.raises(ModuleNotFoundError):
        GrpcExtra._safe_import("example.module")


def test_run_with_reload_requires_watchfiles(monkeypatch):
    original_import = builtins.__import__

    def _import(name, *args, **kwargs):
        if name == "watchfiles":
            raise ImportError("missing")
        return original_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", _import)
    with pytest.raises(ServiceNotDecoratedError):
        GrpcExtra()._run_with_reload(
            bind="[::]:1",
            max_workers=1,
            max_msg_mb=1,
            enable_health=False,
            enable_reflection=False,
            auth_backend=None,
            reload_paths=("app",),
            auto_discover=False,
        )


def test_add_health_and_reflection_import_errors():
    original_import = builtins.__import__

    def _import(name, *args, **kwargs):
        if name in {"grpc_health.v1", "grpc_reflection.v1alpha"}:
            raise ImportError("missing")
        return original_import(name, *args, **kwargs)

    try:
        builtins.__import__ = _import
        with pytest.raises(ServiceNotDecoratedError):
            GrpcExtra._add_health(object())
        with pytest.raises(ServiceNotDecoratedError):
            GrpcExtra._add_reflection(object(), [], enable_health=False)
    finally:
        builtins.__import__ = original_import


def test_qualified_service_name_without_package():
    definition = ServiceDefinition(
        service=object,
        meta=ServiceMeta(name="ExampleService", app_label="example", package=None),
        methods=[],
    )
    assert GrpcExtra._qualified_service_name(definition) == "ExampleService"


def test_apply_raises_when_pb2_modules_missing(monkeypatch):
    definition = ServiceDefinition(
        service=object,
        meta=ServiceMeta(
            name="ExampleService",
            app_label="example",
            proto_path="grpc/proto/example.proto",
        ),
        methods=[],
    )
    registry._services.append(definition)
    monkeypatch.setattr(
        "grpc_extra.main.importlib.import_module",
        lambda _path: (_ for _ in ()).throw(ModuleNotFoundError("missing")),
    )
    with pytest.raises(ServiceNotDecoratedError):
        GrpcExtra().apply(DummyServer())
