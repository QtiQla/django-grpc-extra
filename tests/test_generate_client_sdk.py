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
    proto.write_text(
        "\n".join(
            [
                'syntax = "proto3";',
                "package app;",
                "message PingRequest {}",
                "message PingResponse {}",
                "service PingService {",
                "  rpc Ping (PingRequest) returns (PingResponse);",
                "}",
            ]
        ),
        encoding="utf-8",
    )
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
    assert (target / "pyproject.toml").exists()
    assert (target / "src" / "sdk" / "client.py").exists()
    assert (target / "src" / "sdk" / "client_generated.py").exists()
    assert (target / "src" / "sdk" / "helpers.py").exists()
    assert (target / "src" / "sdk" / "models.py").exists()
    assert (target / "src" / "sdk" / "typed_services.py").exists()
    assert (target / "src" / "sdk" / "generated" / "app" / "services.py").exists()
    assert (target / "src" / "sdk" / "generated" / "app" / "models.py").exists()
    assert (target / "src" / "sdk" / "generated" / "app" / "typed_services.py").exists()
    services_py = (target / "src" / "sdk" / "services.py").read_text(encoding="utf-8")
    client_py = (target / "src" / "sdk" / "client.py").read_text(encoding="utf-8")
    generated_client_py = (target / "src" / "sdk" / "client_generated.py").read_text(
        encoding="utf-8"
    )
    typed_services_py = (target / "src" / "sdk" / "typed_services.py").read_text(
        encoding="utf-8"
    )
    app_typed_services_py = (
        target / "src" / "sdk" / "generated" / "app" / "typed_services.py"
    ).read_text(encoding="utf-8")
    app_services_py = (
        target / "src" / "sdk" / "generated" / "app" / "services.py"
    ).read_text(encoding="utf-8")
    init_py = (target / "src" / "sdk" / "__init__.py").read_text(encoding="utf-8")
    helpers_py = (target / "src" / "sdk" / "helpers.py").read_text(encoding="utf-8")
    assert "import importlib" not in services_py
    assert "from .generated.app.services import PingServiceClient" in services_py
    assert (
        "from app.grpc.proto.s_pb2_grpc import PingServiceStub as app_grpc_proto_s_pb2_grpc_PingServiceStub"
        in app_services_py
    )
    assert "class GrpcClient(GeneratedGrpcClient):" in client_py
    assert "def ping(self) -> PingServiceClient:" in generated_client_py
    assert "def typed(self) -> TypedGrpcClient:" in generated_client_py
    assert (
        "from .generated.app.typed_services import TypedPingServiceClient"
        in typed_services_py
    )
    assert (
        "class TypedPingServiceClient(BaseTypedServiceClient):" in app_typed_services_py
    )
    assert "from .helpers import extract_results, message_to_dict" in init_py
    assert "def message_to_dict(message: Any) -> dict[str, Any]:" in helpers_py
    assert "inspect.signature(MessageToDict).parameters" in helpers_py
    assert '"always_print_fields_with_no_presence"' in helpers_py
    assert '"including_default_value_fields"' in helpers_py
    assert "def extract_results(message_or_dict: Any) -> list[Any]:" in helpers_py
    assert any(arg.startswith("--pyi_out=") for arg in calls[0])
    assert calls


def test_python_generator_updates_services_only_for_existing_target(
    monkeypatch, tmp_path
):
    proto = tmp_path / "app" / "grpc" / "proto" / "s.proto"
    proto.parent.mkdir(parents=True)
    proto.write_text(
        "\n".join(
            [
                'syntax = "proto3";',
                "package app;",
                "message PingRequest {}",
                "message PingResponse {}",
                "service PingService {",
                "  rpc Ping (PingRequest) returns (PingResponse);",
                "}",
            ]
        ),
        encoding="utf-8",
    )

    class DummyProtoc:
        @staticmethod
        def main(_args):
            return 0

    monkeypatch.setitem(sys.modules, "grpc_tools", SimpleNamespace(protoc=DummyProtoc))
    target_dir = tmp_path / "sdk"
    runtime_dir = target_dir / "src" / "sdk"
    runtime_dir.mkdir(parents=True)
    (target_dir / "pyproject.toml").write_text("version = '9.9.9'\n", encoding="utf-8")
    (target_dir / "README.md").write_text("custom readme\n", encoding="utf-8")
    (runtime_dir / "client.py").write_text("custom client\n", encoding="utf-8")
    (runtime_dir / "auth.py").write_text("custom auth\n", encoding="utf-8")
    (runtime_dir / "config.py").write_text("custom config\n", encoding="utf-8")
    (runtime_dir / "errors.py").write_text("custom errors\n", encoding="utf-8")
    (runtime_dir / "__init__.py").write_text("custom init\n", encoding="utf-8")
    (runtime_dir / "services.py").write_text("old services\n", encoding="utf-8")
    (runtime_dir / "client_generated.py").write_text(
        "old generated client\n", encoding="utf-8"
    )
    (runtime_dir / "helpers.py").write_text("custom helpers\n", encoding="utf-8")
    (runtime_dir / "models.py").write_text("old models\n", encoding="utf-8")
    (runtime_dir / "typed_services.py").write_text(
        "old typed services\n", encoding="utf-8"
    )

    PythonClientSDKGenerator().generate(
        proto_files=[proto],
        out_dir=tmp_path,
        sdk_name="sdk",
        include_root=tmp_path,
    )

    assert (target_dir / "pyproject.toml").read_text(
        encoding="utf-8"
    ) == "version = '9.9.9'\n"
    assert (target_dir / "README.md").read_text(encoding="utf-8") == "custom readme\n"
    assert (runtime_dir / "client.py").read_text(encoding="utf-8") == "custom client\n"
    assert (runtime_dir / "auth.py").read_text(encoding="utf-8") == "custom auth\n"
    assert (runtime_dir / "config.py").read_text(encoding="utf-8") == "custom config\n"
    assert (runtime_dir / "errors.py").read_text(encoding="utf-8") == "custom errors\n"
    assert (runtime_dir / "__init__.py").read_text(encoding="utf-8") == "custom init\n"
    assert (runtime_dir / "helpers.py").read_text(
        encoding="utf-8"
    ) == "custom helpers\n"
    services_py = (runtime_dir / "services.py").read_text(encoding="utf-8")
    generated_client_py = (runtime_dir / "client_generated.py").read_text(
        encoding="utf-8"
    )
    models_py = (runtime_dir / "models.py").read_text(encoding="utf-8")
    typed_services_py = (runtime_dir / "typed_services.py").read_text(encoding="utf-8")
    assert "old services" not in services_py
    assert "old generated client" not in generated_client_py
    assert "old models" not in models_py
    assert "old typed services" not in typed_services_py
    assert "from .generated.app.services import PingServiceClient" in services_py
    assert "def ping(self) -> PingServiceClient:" in generated_client_py


def test_python_generator_assigns_distinct_stub_aliases_per_service(
    monkeypatch, tmp_path
):
    proto = tmp_path / "app" / "grpc" / "proto" / "s.proto"
    proto.parent.mkdir(parents=True)
    proto.write_text(
        "\n".join(
            [
                'syntax = "proto3";',
                "package app;",
                "message PingRequest {}",
                "message PingResponse {}",
                "message PongRequest {}",
                "message PongResponse {}",
                "service PingService {",
                "  rpc Ping (PingRequest) returns (PingResponse);",
                "}",
                "service PongService {",
                "  rpc Pong (PongRequest) returns (PongResponse);",
                "}",
            ]
        ),
        encoding="utf-8",
    )

    class DummyProtoc:
        @staticmethod
        def main(_args):
            return 0

    monkeypatch.setitem(sys.modules, "grpc_tools", SimpleNamespace(protoc=DummyProtoc))
    target = PythonClientSDKGenerator().generate(
        proto_files=[proto],
        out_dir=tmp_path,
        sdk_name="sdk",
        include_root=tmp_path,
    )
    services_py = (
        target / "src" / "sdk" / "generated" / "app" / "services.py"
    ).read_text(encoding="utf-8")
    assert (
        "from app.grpc.proto.s_pb2_grpc import PingServiceStub as app_grpc_proto_s_pb2_grpc_PingServiceStub"
        in services_py
    )
    assert (
        "from app.grpc.proto.s_pb2_grpc import PongServiceStub as app_grpc_proto_s_pb2_grpc_PongServiceStub"
        in services_py
    )
    assert "class PingServiceClient(BaseServiceClient):" in services_py
    assert "STUB_CLASS = app_grpc_proto_s_pb2_grpc_PingServiceStub" in services_py
    assert "class PongServiceClient(BaseServiceClient):" in services_py
    assert "STUB_CLASS = app_grpc_proto_s_pb2_grpc_PongServiceStub" in services_py


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
    other_conf = SimpleNamespace(label="other", path=str(tmp_path / "other" / "app"))
    monkeypatch.setattr(
        "grpc_extra.management.commands.generate_client_sdk.apps.get_app_configs",
        lambda: [app_conf, other_conf],
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
