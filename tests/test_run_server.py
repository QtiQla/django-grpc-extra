from __future__ import annotations

import importlib
import sys
from types import SimpleNamespace

from django.conf import settings

from grpc_extra.registry import registry


class DummyServer:
    def __init__(self, *args, **kwargs):
        self.args = args
        self.kwargs = kwargs
        self.ports = []
        self.started = False
        self.waited = False

    def add_insecure_port(self, bind):
        self.ports.append(bind)

    def start(self):
        self.started = True

    def wait_for_termination(self):
        self.waited = True

    def stop(self, grace):
        self.stopped = grace


class DummyGrpcModule:
    class ServerInterceptor:
        pass

    def __init__(self):
        self.created = []

    def server(self, *args, **kwargs):
        server = DummyServer(*args, **kwargs)
        self.created.append(server)
        return server


def _configure_settings(**overrides):
    if not settings.configured:
        settings.configure(
            EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend"
        )
    defaults = {
        "BIND": "[::]:50051",
        "MAX_WORKERS": 3,
        "MAX_MSG_MB": 7,
        "ENABLE_HEALTH": False,
        "ENABLE_REFLECTION": False,
        "ENABLE_REQUEST_LOGGING": True,
        "LOGGER_NAME": "grpc_extra",
        "ENABLE_RELOAD": False,
        "RELOAD_PATHS": (".",),
        "AUTH_BACKEND": None,
    }
    defaults.update(overrides)
    settings.GRPC_EXTRA = defaults


def _load_grpc_extra(dummy_grpc):
    sys.modules["grpc"] = dummy_grpc
    if "grpc_extra.auth" in sys.modules:
        importlib.reload(sys.modules["grpc_extra.auth"])
    if "grpc_extra.main" in sys.modules:
        importlib.reload(sys.modules["grpc_extra.main"])
    return importlib.import_module("grpc_extra.main").GrpcExtra


def test_run_server_uses_settings_and_options(monkeypatch):
    dummy_grpc = DummyGrpcModule()
    monkeypatch.setitem(sys.modules, "grpc", dummy_grpc)
    GrpcExtra = _load_grpc_extra(dummy_grpc)

    _configure_settings(BIND="127.0.0.1:5001", MAX_WORKERS=5, MAX_MSG_MB=12)

    registry.clear()
    extra = GrpcExtra()
    monkeypatch.setattr(extra, "apply", lambda server: [])

    extra.run_server(auto_discover=False)

    assert dummy_grpc.created
    server = dummy_grpc.created[0]
    assert server.ports == ["127.0.0.1:5001"]
    assert server.kwargs["options"] == [
        ("grpc.max_send_message_length", 12 * 1024 * 1024),
        ("grpc.max_receive_message_length", 12 * 1024 * 1024),
    ]


def test_run_server_enables_request_logging_interceptor(monkeypatch):
    dummy_grpc = DummyGrpcModule()
    monkeypatch.setitem(sys.modules, "grpc", dummy_grpc)
    GrpcExtra = _load_grpc_extra(dummy_grpc)

    _configure_settings(ENABLE_REQUEST_LOGGING=True)

    registry.clear()
    extra = GrpcExtra()
    monkeypatch.setattr(extra, "apply", lambda server: [])

    extra.run_server(auto_discover=False)

    server = dummy_grpc.created[0]
    assert len(server.kwargs["interceptors"]) == 1


def test_run_server_calls_health_and_reflection(monkeypatch):
    dummy_grpc = DummyGrpcModule()
    monkeypatch.setitem(sys.modules, "grpc", dummy_grpc)
    GrpcExtra = _load_grpc_extra(dummy_grpc)

    _configure_settings(ENABLE_HEALTH=True, ENABLE_REFLECTION=True)

    registry.clear()
    extra = GrpcExtra()
    monkeypatch.setattr(extra, "apply", lambda server: [])

    calls = SimpleNamespace(health=False, reflection=False)

    def _health(server):
        calls.health = True

    def _reflection(server, service_names, enable_health):
        calls.reflection = True

    monkeypatch.setattr(extra, "_add_health", _health)
    monkeypatch.setattr(extra, "_add_reflection", _reflection)

    extra.run_server(auto_discover=False)

    assert calls.health is True
    assert calls.reflection is True


def test_run_server_uses_watchfiles_for_reload(monkeypatch):
    dummy_grpc = DummyGrpcModule()
    monkeypatch.setitem(sys.modules, "grpc", dummy_grpc)
    GrpcExtra = _load_grpc_extra(dummy_grpc)

    _configure_settings(ENABLE_RELOAD=True, RELOAD_PATHS=("app",))

    calls = SimpleNamespace(paths=None, target=None, args=None)

    def _run_process(*paths, target, args):
        calls.paths = paths
        calls.target = target
        calls.args = args

    monkeypatch.setitem(
        sys.modules, "watchfiles", SimpleNamespace(run_process=_run_process)
    )

    extra = GrpcExtra()
    extra.run_server(auto_discover=False)

    assert calls.paths == ("app",)
    assert callable(calls.target)


def test_run_server_handles_keyboard_interrupt_on_wait(monkeypatch):
    class InterruptServer(DummyServer):
        def wait_for_termination(self):
            raise KeyboardInterrupt()

    class InterruptGrpcModule(DummyGrpcModule):
        def server(self, *args, **kwargs):
            server = InterruptServer(*args, **kwargs)
            self.created.append(server)
            return server

    dummy_grpc = InterruptGrpcModule()
    monkeypatch.setitem(sys.modules, "grpc", dummy_grpc)
    GrpcExtra = _load_grpc_extra(dummy_grpc)
    _configure_settings(ENABLE_RELOAD=False)

    registry.clear()
    extra = GrpcExtra()
    monkeypatch.setattr(extra, "apply", lambda server: [])

    extra.run_server(auto_discover=False)

    server = dummy_grpc.created[0]
    assert getattr(server, "stopped", None) == 0
