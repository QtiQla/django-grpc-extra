from __future__ import annotations

import argparse
import builtins
import sys
from types import SimpleNamespace

import pytest
from django.core.management.base import CommandError
from pydantic import BaseModel, Field, create_model

from grpc_extra.management.commands.generate_proto import (
    Command,
    ProtoBuilder,
    ProtoTypeError,
)
from grpc_extra.registry import MethodMeta, ServiceDefinition, ServiceMeta


class PingSchema(BaseModel):
    """Ping schema doc."""

    message: str


def _definition() -> ServiceDefinition:
    return ServiceDefinition(
        service=object,
        meta=ServiceMeta(
            name="ExampleService",
            app_label="example_app",
            package="example_app",
            proto_path="grpc/proto/example_app.proto",
            description="Service description",
        ),
        methods=[
            MethodMeta(
                name="Ping",
                handler_name="ping",
                request_schema=PingSchema,
                response_schema=PingSchema,
                description="Method description",
            )
        ],
    )


def test_package_from_and_invalid_kind():
    cmd = Command()
    assert cmd._package_from([_definition()]) == "example_app"
    builder = ProtoBuilder("example_app")
    with pytest.raises(ProtoTypeError):
        cmd._message_name(
            PingSchema,
            builder,
            kind="wrong",
            service_name="ExampleService",
            method_name="Ping",
        )


def test_render_helpers_and_schema_base_name():
    cmd = Command()
    assert cmd._schema_base_name("PingSchema") == "Ping"
    assert cmd._render_imports({"a.proto"}).strip() == 'import "a.proto";'
    assert "enum Status" in cmd._render_enums({"Status": ["ACTIVE"]})
    assert "message Ping" in cmd._render_messages(
        {
            "Ping": [
                SimpleNamespace(
                    repeated=False,
                    optional=False,
                    type_name="string",
                    name="value",
                    number=1,
                )
            ]
        }
    )


def test_render_protos_requires_proto_path():
    cmd = Command()
    broken = ServiceDefinition(
        service=object,
        meta=ServiceMeta(name="Broken", app_label="app", proto_path=None),
        methods=[],
    )
    with pytest.raises(CommandError):
        list(cmd._render_protos("/tmp", [broken]))


def test_compile_protos_uses_grpc_tools(monkeypatch, tmp_path):
    cmd = Command()
    proto = tmp_path / "app" / "grpc" / "proto" / "service.proto"
    proto.parent.mkdir(parents=True)
    proto.write_text('syntax = "proto3";', encoding="utf-8")

    calls = []
    fake_grpc_tools_dir = tmp_path / "fake_grpc_tools"
    (fake_grpc_tools_dir / "_proto").mkdir(parents=True)

    class DummyProtoc:
        @staticmethod
        def main(args):
            calls.append(args)
            return 0

    monkeypatch.setitem(
        __import__("sys").modules,
        "grpc_tools",
        SimpleNamespace(
            protoc=DummyProtoc, __file__=str(fake_grpc_tools_dir / "__init__.py")
        ),
    )
    compiled = cmd._compile_protos(str(proto.parent.parent.parent), [proto], pyi=True)
    assert compiled == 1
    assert "--pyi_out=" in " ".join(calls[0])
    assert any(
        arg.startswith(f"-I{fake_grpc_tools_dir / '_proto'}") for arg in calls[0]
    )


def test_compile_protos_uses_googleapis_include_when_available(monkeypatch, tmp_path):
    cmd = Command()
    proto = tmp_path / "app" / "grpc" / "proto" / "service.proto"
    proto.parent.mkdir(parents=True)
    proto.write_text('syntax = "proto3";', encoding="utf-8")

    calls = []
    fake_grpc_tools_dir = tmp_path / "fake_grpc_tools"
    (fake_grpc_tools_dir / "_proto").mkdir(parents=True)
    fake_site_packages = tmp_path / "site-packages"
    google_type_dir = fake_site_packages / "google" / "type"
    google_type_dir.mkdir(parents=True)
    (google_type_dir / "date.proto").write_text("", encoding="utf-8")
    fake_date_pb2 = google_type_dir / "date_pb2.py"
    fake_date_pb2.write_text("", encoding="utf-8")

    class DummyProtoc:
        @staticmethod
        def main(args):
            calls.append(args)
            return 0

    monkeypatch.setitem(
        sys.modules,
        "grpc_tools",
        SimpleNamespace(
            protoc=DummyProtoc, __file__=str(fake_grpc_tools_dir / "__init__.py")
        ),
    )
    monkeypatch.setattr(
        "grpc_extra.management.commands.generate_proto.importlib.import_module",
        lambda name: (
            SimpleNamespace(__file__=str(fake_date_pb2))
            if name == "google.type.date_pb2"
            else (_ for _ in ()).throw(ImportError())
        ),
    )

    compiled = cmd._compile_protos(str(proto.parent.parent.parent), [proto], pyi=False)
    assert compiled == 1
    assert any(arg.startswith(f"-I{fake_site_packages}") for arg in calls[0])


def test_compile_protos_raises_on_failure(monkeypatch, tmp_path):
    cmd = Command()
    proto = tmp_path / "app" / "grpc" / "proto" / "service.proto"
    proto.parent.mkdir(parents=True)
    proto.write_text('syntax = "proto3";', encoding="utf-8")

    class DummyProtoc:
        @staticmethod
        def main(args):
            return 1

    monkeypatch.setitem(
        __import__("sys").modules, "grpc_tools", SimpleNamespace(protoc=DummyProtoc)
    )
    with pytest.raises(CommandError):
        cmd._compile_protos(str(proto.parent.parent.parent), [proto], pyi=False)


def test_add_arguments_and_apps_by_label_errors(monkeypatch):
    cmd = Command()
    parser = argparse.ArgumentParser()
    cmd.add_arguments(parser)
    args = parser.parse_args([])
    assert hasattr(args, "all")

    monkeypatch.setattr(
        "grpc_extra.management.commands.generate_proto.apps.get_app_config",
        lambda _label: (_ for _ in ()).throw(LookupError()),
    )
    with pytest.raises(CommandError):
        cmd._apps_by_label(["missing"])


def test_package_resolution_variants():
    cmd = Command()
    no_pkg = ServiceDefinition(
        service=object,
        meta=ServiceMeta(
            name="NoPkg", app_label="app", package=None, proto_path="grpc/proto/a.proto"
        ),
        methods=[],
    )
    assert cmd._package_from([no_pkg]) == "grpc"
    with pytest.raises(CommandError):
        cmd._package_from(
            [
                ServiceDefinition(
                    service=object,
                    meta=ServiceMeta(name="A", app_label="a", package="a"),
                    methods=[],
                ),
                ServiceDefinition(
                    service=object,
                    meta=ServiceMeta(name="B", app_label="b", package="b"),
                    methods=[],
                ),
            ]
        )


def test_message_name_for_none_schema_adds_empty_import():
    cmd = Command()
    builder = ProtoBuilder("x")
    assert (
        cmd._message_name(
            None,
            builder,
            kind="request",
            service_name="ExampleService",
            method_name="List",
        )
        == "google.protobuf.Empty"
    )
    assert "google/protobuf/empty.proto" in builder.imports


def test_message_name_uses_service_method_naming():
    cmd = Command()
    builder = ProtoBuilder("x")

    RequestSchema = type("OrderingRequest", (BaseModel,), {"__annotations__": {}})
    assert (
        cmd._message_name(
            RequestSchema,
            builder,
            kind="request",
            service_name="CustomerService",
            method_name="List",
        )
        == "CustomerServiceListRequest"
    )


def test_handle_errors_for_conflicting_flags_and_missing_definitions(monkeypatch):
    cmd = Command()
    with pytest.raises(CommandError):
        cmd.handle(app=["app"], all=True, force=False, no_compile=True, pyi=False)

    monkeypatch.setattr(
        "grpc_extra.management.commands.generate_proto.GrpcExtra.auto_discover_services",
        lambda self: None,
    )
    monkeypatch.setattr(
        "grpc_extra.management.commands.generate_proto.registry.clear", lambda: None
    )
    monkeypatch.setattr(
        "grpc_extra.management.commands.generate_proto.registry.all", lambda: []
    )
    monkeypatch.setattr(
        "grpc_extra.management.commands.generate_proto.apps.get_app_configs", lambda: []
    )
    with pytest.raises(CommandError):
        cmd.handle(app=[], all=True, force=False, no_compile=True, pyi=False)


def test_handle_writes_skips_and_compiles(monkeypatch, tmp_path):
    cmd = Command()
    logs = []
    cmd.stdout = SimpleNamespace(write=lambda msg: logs.append(msg))
    app_conf = SimpleNamespace(label="example_app", path=str(tmp_path / "example_app"))
    definition = _definition()
    proto_abs = tmp_path / "example_app" / "grpc" / "proto" / "example_app.proto"
    proto_abs.parent.mkdir(parents=True, exist_ok=True)
    proto_abs.write_text("existing", encoding="utf-8")

    monkeypatch.setattr(
        "grpc_extra.management.commands.generate_proto.GrpcExtra.auto_discover_services",
        lambda self: None,
    )
    monkeypatch.setattr(
        "grpc_extra.management.commands.generate_proto.registry.clear", lambda: None
    )
    monkeypatch.setattr(
        "grpc_extra.management.commands.generate_proto.registry.all",
        lambda: [definition],
    )
    monkeypatch.setattr(
        "grpc_extra.management.commands.generate_proto.apps.get_app_configs",
        lambda: [app_conf],
    )
    monkeypatch.setattr(
        cmd,
        "_render_protos",
        lambda app_path, defs: [(proto_abs, 'syntax = "proto3";')],
    )
    monkeypatch.setattr(cmd, "_compile_protos", lambda app_path, proto_files, pyi: 1)

    cmd.handle(app=[], all=True, force=False, no_compile=False, pyi=True)
    assert any(line.startswith("skip ") for line in logs)
    assert any("compiled=1" in line for line in logs)

    logs.clear()
    cmd.handle(app=[], all=True, force=True, no_compile=True, pyi=False)
    assert any(line.startswith("write ") for line in logs)
    assert any("compiled=0" in line for line in logs)


def test_compile_protos_raises_when_grpc_tools_missing(monkeypatch, tmp_path):
    cmd = Command()
    proto = tmp_path / "app" / "grpc" / "proto" / "service.proto"
    proto.parent.mkdir(parents=True)
    proto.write_text('syntax = "proto3";', encoding="utf-8")
    monkeypatch.delitem(sys.modules, "grpc_tools", raising=False)
    original_import = builtins.__import__

    def _import(name, *args, **kwargs):
        if name == "grpc_tools":
            raise ImportError("missing")
        return original_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", _import)
    with pytest.raises(CommandError):
        cmd._compile_protos(str(proto.parent.parent.parent), [proto], pyi=False)


def test_proto_builder_message_conflict():
    class A(BaseModel):
        value: int

    class B(BaseModel):
        value: str

    builder = ProtoBuilder("example")
    builder.register_message(A, name="Shared")
    with pytest.raises(ProtoTypeError):
        builder.register_message(B, name="Shared")


def test_proto_builder_reuses_message_name_for_identical_models():
    builder = ProtoBuilder("example")
    model_a = create_model("OrderingRequest", ordering=(str | None, None))
    model_b = create_model("OrderingRequest", ordering=(str | None, None))

    assert (
        builder.register_message(model_a, name="OrderingRequest") == "OrderingRequest"
    )
    assert (
        builder.register_message(model_b, name="OrderingRequest") == "OrderingRequest"
    )


def test_build_proto_includes_descriptions_in_comments():
    class DescribedSchema(BaseModel):
        """Schema description."""

        title: str = Field(description="Field description")

    definition = ServiceDefinition(
        service=object,
        meta=ServiceMeta(
            name="DocService",
            app_label="example",
            package="example",
            proto_path="grpc/proto/example.proto",
            description="Service comment",
        ),
        methods=[
            MethodMeta(
                name="Ping",
                handler_name="ping",
                request_schema=DescribedSchema,
                response_schema=DescribedSchema,
                description="RPC comment",
            )
        ],
    )
    content = Command()._build_proto([definition])
    assert "// Service comment" in content
    assert "// RPC comment" in content
    assert "// Schema description." in content
    assert "// Field description" in content
