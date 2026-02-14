from __future__ import annotations

import argparse

import pytest
from django.conf import settings
from django.core.management.base import CommandError

from grpc_extra.management.commands.run_grpcserver import Command


class DummyInterceptor:
    pass


class BadInterceptor:
    def __init__(self, value):
        self.value = value


def interceptor_factory():
    return DummyInterceptor()


def test_add_arguments_parses_flags():
    command = Command()
    parser = argparse.ArgumentParser()
    command.add_arguments(parser)
    args = parser.parse_args(
        [
            "--bind",
            "127.0.0.1:50051",
            "--max-workers",
            "5",
            "--health",
            "--no-reflection",
            "--reload-path",
            "app",
        ]
    )
    assert args.bind == "127.0.0.1:50051"
    assert args.max_workers == 5
    assert args.health is True
    assert args.reflection is False
    assert args.reload_path == ["app"]


def test_handle_passes_runtime_options(monkeypatch):
    command = Command()
    captured = {}

    class DummyExtra:
        def run_server(self, **kwargs):
            captured.update(kwargs)

    monkeypatch.setattr(
        "grpc_extra.management.commands.run_grpcserver.GrpcExtra",
        lambda: DummyExtra(),
    )
    monkeypatch.setattr(
        command,
        "_resolve_interceptors",
        lambda paths: [DummyInterceptor()],
    )

    command.handle(
        bind="[::]:50052",
        max_workers=7,
        max_msg_mb=16,
        health=True,
        reflection=False,
        auth_backend="path.to.auth",
        interceptor=["a.b.Interceptor"],
        reload=False,
        reload_path=["app", "pkg"],
        discover=False,
        request_logging=None,
        logger_name=None,
    )

    assert captured["bind"] == "[::]:50052"
    assert captured["max_workers"] == 7
    assert captured["max_msg_mb"] == 16
    assert captured["enable_health"] is True
    assert captured["enable_reflection"] is False
    assert captured["reload_paths"] == ["app", "pkg"]
    assert captured["auto_discover"] is False
    assert captured["interceptors"]


def test_resolve_interceptors_supports_class_and_callable():
    command = Command()
    resolved = command._resolve_interceptors(
        [
            "tests.test_run_grpcserver_command.DummyInterceptor",
            "tests.test_run_grpcserver_command.interceptor_factory",
        ]
    )
    assert len(resolved) == 2
    assert type(resolved[0]).__name__ == "DummyInterceptor"
    assert callable(resolved[1])


def test_resolve_interceptors_invalid_path_raises():
    command = Command()
    with pytest.raises(CommandError):
        command._resolve_interceptors(["tests.missing.Unknown"])


def test_resolve_interceptors_non_default_constructor_raises():
    command = Command()
    with pytest.raises(CommandError):
        command._resolve_interceptors(
            ["tests.test_run_grpcserver_command.BadInterceptor"]
        )


def test_override_settings_for_request_logging(monkeypatch):
    command = Command()
    captured = {}
    settings.GRPC_EXTRA = {"ENABLE_REQUEST_LOGGING": False, "LOGGER_NAME": "base"}

    class DummyExtra:
        def run_server(self, **kwargs):
            captured["settings"] = dict(settings.GRPC_EXTRA)

    monkeypatch.setattr(
        "grpc_extra.management.commands.run_grpcserver.GrpcExtra",
        lambda: DummyExtra(),
    )

    command.handle(
        bind=None,
        max_workers=None,
        max_msg_mb=None,
        health=None,
        reflection=None,
        auth_backend=None,
        interceptor=[],
        reload=None,
        reload_path=[],
        discover=True,
        request_logging=True,
        logger_name="custom.grpc",
    )

    assert captured["settings"]["ENABLE_REQUEST_LOGGING"] is True
    assert captured["settings"]["LOGGER_NAME"] == "custom.grpc"
    assert settings.GRPC_EXTRA["ENABLE_REQUEST_LOGGING"] is False
    assert settings.GRPC_EXTRA["LOGGER_NAME"] == "base"
