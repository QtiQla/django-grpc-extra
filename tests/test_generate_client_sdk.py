from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace

import pytest
from django.conf import settings
from django.core.management.base import CommandError

from grpc_extra.management.commands.generate_client_sdk import Command
from grpc_extra.registry import ServiceDefinition, ServiceMeta
from grpc_extra.sdk.generators import (
    BaseClientSDKGenerator,
    PhpClientSDKGenerator,
    PythonClientSDKGenerator,
    SDKGenerationError,
)


class DummyGenerator(BaseClientSDKGenerator):
    language = "dummy"

    def __init__(self):
        self.called_with = None

    def generate(
        self, *, proto_files, out_dir: Path, sdk_name: str, include_root: Path
    ) -> Path:
        self.called_with = (list(proto_files), out_dir, sdk_name, include_root)
        target = out_dir / sdk_name
        target.mkdir(parents=True, exist_ok=True)
        return target


def test_resolve_generator_from_settings():
    settings.GRPC_EXTRA = {
        "SDK_GENERATORS": {
            "dummy": "tests.test_generate_client_sdk.DummyGenerator",
        }
    }
    command = Command()
    generator = command._resolve_generator("dummy")
    assert type(generator).__name__ == "DummyGenerator"


def test_resolve_generator_invalid_language():
    settings.GRPC_EXTRA = {}
    command = Command()
    with pytest.raises(CommandError):
        command._resolve_generator("go")


def test_collect_proto_files_and_include_root(tmp_path):
    app_dir = tmp_path / "app"
    proto = app_dir / "grpc" / "proto" / "example.proto"
    proto.parent.mkdir(parents=True)
    proto.write_text('syntax = "proto3";', encoding="utf-8")

    definition = ServiceDefinition(
        service=object,
        meta=ServiceMeta(
            name="ExampleService",
            app_label="example",
            proto_path="grpc/proto/example.proto",
        ),
        methods=[],
    )
    command = Command()
    app_conf = SimpleNamespace(label="example", path=str(app_dir))
    files = command._collect_proto_files([definition], {"example": app_conf})
    assert files == [proto]
    assert command._include_root([app_conf]) == tmp_path


def test_include_root_rejects_multiple_roots(tmp_path):
    command = Command()
    app_a = SimpleNamespace(path=str(tmp_path / "a" / "app"))
    app_b = SimpleNamespace(path=str(tmp_path / "b" / "app"))
    with pytest.raises(CommandError):
        command._include_root([app_a, app_b])


def test_python_generator_uses_grpc_tools(monkeypatch, tmp_path):
    proto = tmp_path / "app" / "grpc" / "proto" / "s.proto"
    proto.parent.mkdir(parents=True)
    proto.write_text('syntax = "proto3";', encoding="utf-8")
    calls = []

    class DummyProtoc:
        @staticmethod
        def main(args):
            calls.append(args)
            return 0

    monkeypatch.setitem(sys.modules, "grpc_tools", SimpleNamespace(protoc=DummyProtoc))
    target = PythonClientSDKGenerator().generate(
        proto_files=[proto],
        out_dir=tmp_path,
        sdk_name="sdk",
        include_root=tmp_path,
    )
    assert target.exists()
    assert calls


def test_php_generator_requires_plugin(monkeypatch, tmp_path):
    monkeypatch.setattr(
        "grpc_extra.sdk.generators.shutil.which", lambda _bin: "/usr/bin/protoc"
    )
    settings.GRPC_EXTRA = {}
    with pytest.raises(SDKGenerationError):
        PhpClientSDKGenerator().generate(
            proto_files=[],
            out_dir=tmp_path,
            sdk_name="sdk",
            include_root=tmp_path,
        )


def test_handle_runs_generator(monkeypatch, tmp_path):
    command = Command()
    logs: list[str] = []
    command.stdout = SimpleNamespace(write=lambda msg: logs.append(msg))
    generator = DummyGenerator()
    app_conf = SimpleNamespace(label="example", path=str(tmp_path / "app"))
    monkeypatch.setattr(
        "grpc_extra.management.commands.generate_client_sdk.apps.get_app_configs",
        lambda: [app_conf],
    )
    monkeypatch.setattr(
        "grpc_extra.management.commands.generate_client_sdk.registry.clear",
        lambda: None,
    )
    monkeypatch.setattr(
        "grpc_extra.management.commands.generate_client_sdk.GrpcExtra.auto_discover_services",
        lambda self: None,
    )
    monkeypatch.setattr(
        "grpc_extra.management.commands.generate_client_sdk.registry.all",
        lambda: [
            ServiceDefinition(
                service=object,
                meta=ServiceMeta(
                    name="ExampleService",
                    app_label="example",
                    proto_path="grpc/proto/example.proto",
                ),
                methods=[],
            )
        ],
    )
    monkeypatch.setattr(
        command, "_collect_proto_files", lambda defs, app_map: [tmp_path / "x.proto"]
    )
    monkeypatch.setattr(command, "_include_root", lambda app_configs: tmp_path)
    monkeypatch.setattr(command, "_resolve_generator", lambda language: generator)

    command.handle(
        language="dummy",
        out=str(tmp_path),
        name="my-sdk",
        app=[],
        all=True,
        skip_proto=True,
    )
    assert generator.called_with is not None
    assert any("client sdk generated" in msg for msg in logs)
