from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, time
from decimal import Decimal
from pathlib import Path
from types import UnionType
from typing import Iterable, Union, cast, get_args, get_origin
from uuid import UUID

from django.apps import apps
from django.conf import settings as django_settings
from django.core.management.base import BaseCommand, CommandError
from pydantic import BaseModel

from grpc_extra.main import GrpcExtra
from grpc_extra.registry import MethodMeta, ServiceDefinition, registry
from grpc_extra.utils import normalize_proto_path

try:
    from enum import Enum
except ImportError:  # pragma: no cover - stdlib always provides Enum
    Enum = object  # type: ignore[misc,assignment]


@dataclass
class FieldSpec:
    name: str
    number: int
    type_name: str
    repeated: bool = False
    optional: bool = False


class ProtoTypeError(CommandError):
    pass


class ProtoBuilder:
    def __init__(self, package: str) -> None:
        self.package = package
        self.imports: set[str] = set()
        self.messages: dict[str, list[FieldSpec]] = {}
        self._message_models: dict[str, type[BaseModel]] = {}
        self.enums: dict[str, list[str]] = {}

    def register_message(
        self, model: type[BaseModel], *, name: str | None = None
    ) -> str:
        message_name = name or model.__name__
        existing_model = self._message_models.get(message_name)
        if existing_model is not None and existing_model is not model:
            raise ProtoTypeError(
                f"Message name conflict for '{message_name}': "
                f"'{existing_model.__name__}' vs '{model.__name__}'."
            )
        self._message_models[message_name] = model
        if message_name in self.messages:
            return message_name
        fields: list[FieldSpec] = []
        field_number = 1
        for field_name, field in model.model_fields.items():
            type_name, repeated, optional = self._proto_type(field.annotation)
            if optional and repeated:
                raise ProtoTypeError(
                    f"Field '{field_name}' in '{model.__name__}' cannot be Optional[List[T]]."
                )
            field_alias = field.alias or field_name
            fields.append(
                FieldSpec(
                    name=field_alias,
                    number=field_number,
                    type_name=type_name,
                    repeated=repeated,
                    optional=optional,
                )
            )
            field_number += 1
        self.messages[message_name] = fields
        return message_name

    def register_enum(self, enum_cls: type[Enum]) -> None:
        if enum_cls.__name__ in self.enums:
            return
        values = [member.name for member in enum_cls]
        self.enums[enum_cls.__name__] = values

    def _proto_type(self, annotation) -> tuple[str, bool, bool]:
        origin = get_origin(annotation)
        args = get_args(annotation)

        if origin is list:
            if not args:
                raise ProtoTypeError("List[T] must specify item type.")
            item_type, _, _ = self._proto_type(args[0])
            return item_type, True, False

        if origin is dict:
            self.imports.add("google/protobuf/struct.proto")
            return "google.protobuf.Struct", False, False

        if origin in (Union, UnionType):
            non_none = [arg for arg in args if arg is not type(None)]
            if len(non_none) == 1:
                type_name, repeated, _ = self._proto_type(non_none[0])
                return type_name, repeated, True
            raise ProtoTypeError("Union types are not supported in proto generation.")

        if isinstance(annotation, type):
            if issubclass(annotation, BaseModel):
                message_name = self.register_message(annotation)
                return message_name, False, False
            if issubclass(annotation, Enum):
                self.register_enum(annotation)
                return annotation.__name__, False, False
            if annotation is dict:
                self.imports.add("google/protobuf/struct.proto")
                return "google.protobuf.Struct", False, False
            if annotation is str:
                return "string", False, False
            if annotation is int:
                return "int64", False, False
            if annotation is float:
                return "double", False, False
            if annotation is bool:
                return "bool", False, False
            if annotation is bytes:
                return "bytes", False, False
            if annotation is datetime:
                self.imports.add("google/protobuf/timestamp.proto")
                return "google.protobuf.Timestamp", False, False
            if annotation is date:
                self.imports.add("google/type/date.proto")
                return "google.type.Date", False, False
            if annotation is time:
                self.imports.add("google/type/timeofday.proto")
                return "google.type.TimeOfDay", False, False
            if annotation is Decimal:
                return "string", False, False
            if annotation is UUID:
                return "string", False, False
            raise ProtoTypeError(
                f"Unsupported type '{annotation.__name__}' for proto generation."
            )

        raise ProtoTypeError(f"Unsupported type annotation '{annotation}'.")


class Command(BaseCommand):
    help = "Generate .proto files from @grpc_service and @grpc_method metadata."

    def add_arguments(self, parser):
        parser.add_argument(
            "--app",
            action="append",
            default=[],
            help="App label to generate (repeatable).",
        )
        parser.add_argument(
            "--all",
            action="store_true",
            help="Generate for every installed app.",
        )
        parser.add_argument(
            "--force",
            action="store_true",
            help="Overwrite existing proto files.",
        )
        parser.add_argument(
            "--no-compile",
            action="store_true",
            help="Skip pb2/pb2_grpc generation via grpc_tools.",
        )
        parser.add_argument(
            "--pyi",
            action="store_true",
            help="Generate .pyi stubs via grpc_tools (requires --no-compile=false).",
        )

    def handle(self, *args, **options):
        app_labels = options.get("app", [])
        all_flag = options.get("all", False)
        force = options.get("force", False)
        no_compile = options.get("no_compile", False)
        pyi = options.get("pyi", False)

        if not all_flag and not app_labels:
            all_flag = True

        if all_flag and app_labels:
            raise CommandError("Use either --all or --app, not both.")

        registry.clear()
        GrpcExtra().auto_discover_services()

        if all_flag:
            target_configs = list(apps.get_app_configs())
        else:
            target_configs = self._apps_by_label(app_labels)

        definitions = list(registry.all())
        if not definitions:
            raise CommandError("No decorated services found.")

        by_app: dict[str, list[ServiceDefinition]] = {}
        for definition in definitions:
            by_app.setdefault(definition.meta.app_label, []).append(definition)

        created = 0
        skipped = 0
        compiled = 0
        for app_conf in target_configs:
            app_defs = by_app.get(app_conf.label, [])
            proto_files: list[Path] = []
            for path, content in self._render_protos(app_conf.path, app_defs):
                if path.exists() and not force:
                    self.stdout.write(f"skip {path}")
                    skipped += 1
                    proto_files.append(path)
                    continue
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(content, encoding="utf-8")
                self.stdout.write(f"write {path}")
                created += 1
                proto_files.append(path)

            if proto_files and not no_compile:
                compiled += self._compile_protos(app_conf.path, proto_files, pyi=pyi)

        self.stdout.write(
            "proto generation complete. "
            f"created={created} skipped={skipped} compiled={compiled}"
        )

    def _grpc_extra_settings(self) -> dict:
        return getattr(django_settings, "GRPC_EXTRA", {}) or {}

    def _schema_suffix_strip(self) -> tuple[str, ...]:
        configured = self._grpc_extra_settings().get("SCHEMA_SUFFIX_STRIP", ("Schema",))
        if isinstance(configured, str):
            return (configured,)
        return tuple(configured)

    def _request_suffix(self) -> str:
        return cast(str, self._grpc_extra_settings().get("REQUEST_SUFFIX", "Request"))

    def _response_suffix(self) -> str:
        return cast(str, self._grpc_extra_settings().get("RESPONSE_SUFFIX", "Response"))

    def _apps_by_label(self, labels: Iterable[str]) -> list:
        configs = []
        missing = []
        for label in labels:
            try:
                configs.append(apps.get_app_config(label))
            except LookupError:
                missing.append(label)

        if missing:
            raise CommandError(f"Unknown app label(s): {', '.join(missing)}")
        return configs

    def _render_protos(
        self, app_path: str, definitions: list[ServiceDefinition]
    ) -> Iterable[tuple[Path, str]]:
        by_path: dict[str, list[ServiceDefinition]] = {}
        for definition in definitions:
            if not definition.meta.proto_path:
                raise CommandError(
                    f"Service '{definition.meta.name}' must define proto_path."
                )
            proto_path = normalize_proto_path(definition.meta.proto_path)
            by_path.setdefault(proto_path, []).append(definition)

        for proto_path, service_defs in by_path.items():
            if not proto_path:
                continue
            content = self._build_proto(service_defs)
            yield Path(app_path) / proto_path, content

    def _build_proto(self, service_defs: list[ServiceDefinition]) -> str:
        package = self._package_from(service_defs)
        builder = ProtoBuilder(package=package)
        service_blocks = [self._render_service(defn, builder) for defn in service_defs]
        imports = self._render_imports(builder.imports)
        enums = self._render_enums(builder.enums)
        messages = self._render_messages(builder.messages)

        parts = [
            'syntax = "proto3";',
            f"package {package};",
            "",
            imports,
            enums,
            messages,
            "\n\n".join(service_blocks),
            "",
        ]
        return "\n".join(part for part in parts if part)

    def _package_from(self, service_defs: list[ServiceDefinition]) -> str:
        packages = {definition.meta.package for definition in service_defs}
        packages.discard(None)
        if not packages:
            return "grpc"
        if len(packages) > 1:
            raise CommandError("Multiple packages in the same proto file.")
        return cast(str, packages.pop())

    def _render_imports(self, imports: set[str]) -> str:
        if not imports:
            return ""
        return "\n".join(f'import "{path}";' for path in sorted(imports)) + "\n"

    def _render_enums(self, enums: dict[str, list[str]]) -> str:
        if not enums:
            return ""
        blocks = []
        for name, values in enums.items():
            lines = [f"enum {name} {{"] + [
                f"  {value} = {index};" for index, value in enumerate(values)
            ]
            lines.append("}")
            blocks.append("\n".join(lines))
        return "\n\n".join(blocks) + "\n"

    def _render_messages(self, messages: dict[str, list[FieldSpec]]) -> str:
        if not messages:
            return ""
        blocks = []
        for name, fields in messages.items():
            lines = [f"message {name} {{"]
            for field in fields:
                repeated = "repeated " if field.repeated else ""
                optional = "optional " if field.optional and not field.repeated else ""
                lines.append(
                    f"  {optional}{repeated}{field.type_name} {field.name} = {field.number};"
                )
            lines.append("}")
            blocks.append("\n".join(lines))
        return "\n\n".join(blocks) + "\n"

    def _render_service(
        self, definition: ServiceDefinition, builder: ProtoBuilder
    ) -> str:
        lines = [f"service {definition.meta.name} {{"]
        methods = definition.methods or self._fallback_methods(definition.service)
        for method in methods:
            request = self._message_name(
                method.request_schema,
                builder,
                kind="request",
            )
            response = self._message_name(
                method.response_schema,
                builder,
                kind="response",
            )
            req_stream = "stream " if method.client_streaming else ""
            res_stream = "stream " if method.server_streaming else ""
            lines.append(
                f"  rpc {method.name} ({req_stream}{request}) returns ({res_stream}{response});"
            )
        lines.append("}")
        return "\n".join(lines)

    def _message_name(
        self,
        schema: type[BaseModel] | None,
        builder: ProtoBuilder,
        *,
        kind: str,
    ) -> str:
        if schema is None:
            builder.imports.add("google/protobuf/empty.proto")
            return "google.protobuf.Empty"
        if kind not in {"request", "response"}:
            raise ProtoTypeError(f"Unknown schema kind '{kind}'.")
        base = self._schema_base_name(schema.__name__)
        suffix = (
            self._request_suffix() if kind == "request" else self._response_suffix()
        )
        message_name = f"{base}{suffix}"
        return builder.register_message(schema, name=message_name)

    def _schema_base_name(self, schema_name: str) -> str:
        for suffix in self._schema_suffix_strip():
            if suffix and schema_name.endswith(suffix):
                stripped = schema_name[: -len(suffix)]
                if stripped:
                    return stripped
        return schema_name

    def _fallback_methods(self, service: type) -> list[MethodMeta]:
        return []

    def _compile_protos(
        self, app_path: str, proto_files: Iterable[Path], *, pyi: bool
    ) -> int:
        try:
            from grpc_tools import protoc
        except ImportError as exc:
            raise CommandError(
                "grpc_tools is required for pb2 generation. "
                "Install grpcio-tools or use --no-compile."
            ) from exc

        app_root = Path(app_path).parent
        compiled = 0
        for proto_file in proto_files:
            args = [
                "protoc",
                f"-I{app_root}",
                f"--python_out={app_root}",
                f"--grpc_python_out={app_root}",
            ]
            if pyi:
                args.append(f"--pyi_out={app_root}")
            args.append(str(proto_file))
            result = protoc.main(args)
            if result != 0:
                raise CommandError(f"protoc failed for {proto_file}")
            compiled += 1
        return compiled
