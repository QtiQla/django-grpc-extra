from __future__ import annotations

import importlib
import re
import shutil
import subprocess
import textwrap
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

from django.conf import settings as django_settings


class SDKGenerationError(Exception):
    pass


class BaseClientSDKGenerator:
    language: str

    def generate(
        self,
        *,
        proto_files: Iterable[Path],
        out_dir: Path,
        sdk_name: str,
        include_root: Path,
    ) -> Path:
        raise NotImplementedError


@dataclass
class RpcMethodSpec:
    name: str
    python_name: str
    request_type: str
    response_type: str
    client_streaming: bool
    server_streaming: bool


@dataclass
class ServiceSpec:
    sdk_app: str
    service_name: str
    python_attr: str
    class_name: str
    stub_module: str
    stub_class: str
    stub_alias: str
    pb2_module: str
    pb2_alias: str
    methods: list[RpcMethodSpec]


@dataclass
class MessageFieldSpec:
    name: str
    annotation: str
    default_expr: str


@dataclass
class MessageSpec:
    sdk_app: str
    pb2_alias: str
    message_name: str
    model_name: str
    fields: list[MessageFieldSpec]


class PythonClientSDKGenerator(BaseClientSDKGenerator):
    language = "python"

    def generate(
        self,
        *,
        proto_files: Iterable[Path],
        out_dir: Path,
        sdk_name: str,
        include_root: Path,
    ) -> Path:
        try:
            import grpc_tools
            from grpc_tools import protoc
        except ImportError as exc:
            raise SDKGenerationError(
                "grpcio-tools is required for Python SDK generation."
            ) from exc

        proto_list = [Path(p) for p in proto_files]
        if not proto_list:
            raise SDKGenerationError(
                "No proto files provided for Python SDK generation."
            )

        target_dir = out_dir / sdk_name
        target_exists = target_dir.exists()
        src_dir = target_dir / "src"
        package_name = self._package_name(sdk_name)
        runtime_dir = src_dir / package_name

        target_dir.mkdir(parents=True, exist_ok=True)
        src_dir.mkdir(parents=True, exist_ok=True)
        runtime_dir.mkdir(parents=True, exist_ok=True)

        grpc_tools_include = self._grpc_tools_include_path(grpc_tools)
        googleapis_include = self._googleapis_include_path()
        for proto_file in proto_list:
            args = [
                "protoc",
                f"-I{include_root}",
                f"--python_out={src_dir}",
                f"--grpc_python_out={src_dir}",
                f"--pyi_out={src_dir}",
            ]
            if grpc_tools_include is not None:
                args.append(f"-I{grpc_tools_include}")
            if googleapis_include is not None:
                args.append(f"-I{googleapis_include}")
            args.append(str(proto_file))
            result = protoc.main(args)
            if result != 0:
                raise SDKGenerationError(f"protoc failed for {proto_file}")
            self._ensure_python_package_tree(src_dir, proto_file, include_root)

        service_specs = self._collect_service_specs(proto_list, include_root)
        message_specs = self._collect_message_specs(proto_list, include_root)
        model_name_map = {
            (spec.pb2_alias, spec.message_name): spec.model_name
            for spec in message_specs
        }
        services_by_app = self._group_services_by_app(service_specs)
        messages_by_app = self._group_messages_by_app(message_specs)

        generated_dir = runtime_dir / "generated"
        generated_dir.mkdir(parents=True, exist_ok=True)
        (generated_dir / "__init__.py").write_text("__all__ = []\n", encoding="utf-8")
        (runtime_dir / "_service_base.py").write_text(
            self._render_service_base(), encoding="utf-8"
        )
        (runtime_dir / "_typed_base.py").write_text(
            self._render_typed_base(), encoding="utf-8"
        )

        all_apps = sorted(set(services_by_app) | set(messages_by_app))
        for app in all_apps:
            app_dir = generated_dir / app
            app_dir.mkdir(parents=True, exist_ok=True)
            (app_dir / "__init__.py").write_text("__all__ = []\n", encoding="utf-8")
            (app_dir / "services.py").write_text(
                self._render_app_services(services_by_app.get(app, [])),
                encoding="utf-8",
            )
            (app_dir / "models.py").write_text(
                self._render_app_models(messages_by_app.get(app, [])),
                encoding="utf-8",
            )
            (app_dir / "typed_services.py").write_text(
                self._render_app_typed_services(
                    services_by_app.get(app, []), model_name_map
                ),
                encoding="utf-8",
            )

        (runtime_dir / "services.py").write_text(
            self._render_services_index(services_by_app), encoding="utf-8"
        )
        (runtime_dir / "models.py").write_text(
            self._render_models_index(messages_by_app), encoding="utf-8"
        )
        (runtime_dir / "typed_services.py").write_text(
            self._render_typed_services_index(services_by_app), encoding="utf-8"
        )
        (runtime_dir / "client_generated.py").write_text(
            self._render_generated_client(service_specs), encoding="utf-8"
        )
        if not target_exists:
            (runtime_dir / "__init__.py").write_text(
                self._render_init(package_name, service_specs), encoding="utf-8"
            )
            (runtime_dir / "auth.py").write_text(self._render_auth(), encoding="utf-8")
            (runtime_dir / "config.py").write_text(
                self._render_config(package_name), encoding="utf-8"
            )
            (runtime_dir / "errors.py").write_text(
                self._render_errors(), encoding="utf-8"
            )
            (runtime_dir / "client.py").write_text(
                self._render_client_wrapper(), encoding="utf-8"
            )
            (runtime_dir / "helpers.py").write_text(
                self._render_helpers(), encoding="utf-8"
            )
        else:
            client_py = runtime_dir / "client.py"
            if not client_py.exists():
                client_py.write_text(self._render_client_wrapper(), encoding="utf-8")
            helpers_py = runtime_dir / "helpers.py"
            if not helpers_py.exists():
                helpers_py.write_text(self._render_helpers(), encoding="utf-8")

        if not target_exists:
            (target_dir / "pyproject.toml").write_text(
                self._render_pyproject(sdk_name, package_name), encoding="utf-8"
            )
            (target_dir / "README.md").write_text(
                self._render_readme(sdk_name, package_name), encoding="utf-8"
            )

        return target_dir

    def _package_name(self, sdk_name: str) -> str:
        sanitized = re.sub(r"[^a-zA-Z0-9]+", "_", sdk_name).strip("_").lower()
        return sanitized or "grpc_client_sdk"

    def _grpc_tools_include_path(self, grpc_tools_module: object) -> Path | None:
        module_file = getattr(grpc_tools_module, "__file__", None)
        if not module_file:
            return None
        include_path = Path(module_file).resolve().parent / "_proto"
        if include_path.exists():
            return include_path
        return None

    def _googleapis_include_path(self) -> Path | None:
        for module_name, proto_rel_path in (
            ("google.type.date_pb2", "google/type/date.proto"),
            ("google.type.timeofday_pb2", "google/type/timeofday.proto"),
        ):
            try:
                module = importlib.import_module(module_name)
            except ImportError:
                continue
            module_file = getattr(module, "__file__", None)
            if not module_file:
                continue
            include_path = Path(module_file).resolve().parents[2]
            if (include_path / proto_rel_path).exists():
                return include_path
        return None

    def _ensure_python_package_tree(
        self,
        src_dir: Path,
        proto_file: Path,
        include_root: Path,
    ) -> None:
        rel = proto_file.relative_to(include_root)
        generated_file = src_dir / f"{rel.with_suffix('')}_pb2.py"
        current = generated_file.parent
        while current != src_dir.parent:
            current.mkdir(parents=True, exist_ok=True)
            init_file = current / "__init__.py"
            if not init_file.exists():
                init_file.touch()
            if current == src_dir:
                break
            current = current.parent

    def _collect_service_specs(
        self,
        proto_files: list[Path],
        include_root: Path,
    ) -> list[ServiceSpec]:
        specs: list[ServiceSpec] = []
        for proto_file in proto_files:
            proto_text = proto_file.read_text(encoding="utf-8")
            rel = proto_file.relative_to(include_root)
            sdk_app = self._sdk_app_name(rel)
            module_base = ".".join(rel.with_suffix("").parts)
            service_blocks = re.finditer(
                r"service\s+(?P<name>\w+)\s*\{(?P<body>.*?)\}",
                proto_text,
                flags=re.DOTALL,
            )
            for block in service_blocks:
                service_name = block.group("name")
                body = block.group("body")
                methods = self._parse_service_methods(body)
                if not methods:
                    continue
                specs.append(
                    ServiceSpec(
                        sdk_app=sdk_app,
                        service_name=service_name,
                        python_attr=self._to_snake(
                            service_name.removesuffix("Service") or service_name
                        ),
                        class_name=f"{service_name}Client",
                        stub_module=f"{module_base}_pb2_grpc",
                        stub_class=f"{service_name}Stub",
                        stub_alias=self._symbol_alias(
                            f"{module_base}_pb2_grpc", f"{service_name}Stub"
                        ),
                        pb2_module=f"{module_base}_pb2",
                        pb2_alias=self._module_alias(f"{module_base}_pb2"),
                        methods=methods,
                    )
                )
        return specs

    def _collect_message_specs(
        self,
        proto_files: list[Path],
        include_root: Path,
    ) -> list[MessageSpec]:
        raw_specs: list[tuple[str, str, str, list[MessageFieldSpec]]] = []
        for proto_file in proto_files:
            proto_text = proto_file.read_text(encoding="utf-8")
            rel = proto_file.relative_to(include_root)
            sdk_app = self._sdk_app_name(rel)
            module_base = ".".join(rel.with_suffix("").parts)
            pb2_alias = self._module_alias(f"{module_base}_pb2")
            for match in re.finditer(
                r"message\s+(?P<name>\w+)\s*\{(?P<body>.*?)\}",
                proto_text,
                flags=re.DOTALL,
            ):
                message_name = match.group("name")
                fields = self._parse_message_fields(match.group("body"), pb2_alias)
                raw_specs.append((sdk_app, pb2_alias, message_name, fields))

        counts: dict[str, int] = {}
        for _, _, message_name, _ in raw_specs:
            counts[message_name] = counts.get(message_name, 0) + 1

        specs: list[MessageSpec] = []
        for sdk_app, pb2_alias, message_name, fields in raw_specs:
            if counts[message_name] == 1:
                model_name = message_name
            else:
                model_name = f"{self._pascal_from_alias(pb2_alias)}_{message_name}"
            specs.append(
                MessageSpec(
                    sdk_app=sdk_app,
                    pb2_alias=pb2_alias,
                    message_name=message_name,
                    model_name=model_name,
                    fields=fields,
                )
            )
        return specs

    def _parse_message_fields(
        self, message_body: str, pb2_alias: str
    ) -> list[MessageFieldSpec]:
        fields: list[MessageFieldSpec] = []
        for raw_line in message_body.splitlines():
            line = raw_line.strip()
            if not line or line.startswith("//"):
                continue
            if "//" in line:
                line = line.split("//", 1)[0].strip()
            if not line.endswith(";"):
                continue
            match = re.match(
                r"(?:(optional|required|repeated)\s+)?(?P<typ>map<[^>]+>|[.\w]+)\s+(?P<name>\w+)\s*=\s*\d+",
                line,
            )
            if not match:
                continue
            label = match.group(1) or ""
            proto_type = match.group("typ")
            field_name = match.group("name")
            annotation, default_expr = self._python_field_type(
                proto_type=proto_type,
                label=label,
                pb2_alias=pb2_alias,
            )
            fields.append(
                MessageFieldSpec(
                    name=field_name,
                    annotation=annotation,
                    default_expr=default_expr,
                )
            )
        return fields

    def _python_field_type(
        self,
        *,
        proto_type: str,
        label: str,
        pb2_alias: str,
    ) -> tuple[str, str]:
        if proto_type.startswith("map<") and proto_type.endswith(">"):
            key_type, value_type = [
                part.strip() for part in proto_type[4:-1].split(",", 1)
            ]
            py_key, _ = self._python_field_type(
                proto_type=key_type, label="", pb2_alias=pb2_alias
            )
            py_value, _ = self._python_field_type(
                proto_type=value_type, label="", pb2_alias=pb2_alias
            )
            return (f"dict[{py_key}, {py_value}]", "Field(default_factory=dict)")

        scalar_map = {
            "double": "float",
            "float": "float",
            "int32": "int",
            "int64": "int",
            "uint32": "int",
            "uint64": "int",
            "sint32": "int",
            "sint64": "int",
            "fixed32": "int",
            "fixed64": "int",
            "sfixed32": "int",
            "sfixed64": "int",
            "bool": "bool",
            "string": "str",
            "bytes": "str",
            "google.protobuf.Timestamp": "datetime",
            "google.protobuf.Empty": "dict[str, Any]",
        }
        message_name = proto_type.split(".")[-1]
        base_type = scalar_map.get(proto_type)
        if base_type is None:
            if "." in proto_type and not proto_type.startswith("google.protobuf."):
                base_type = "Any"
            elif message_name and message_name[0].isupper():
                base_type = message_name
            else:
                base_type = "Any"

        if label == "repeated":
            return (f"list[{base_type}]", "Field(default_factory=list)")
        if label == "optional":
            return (f"{base_type} | None", "None")
        return (base_type, "...")

    def _pascal_from_alias(self, alias: str) -> str:
        parts = [part for part in alias.split("_") if part]
        return "".join(part[:1].upper() + part[1:] for part in parts)

    def _parse_service_methods(self, body: str) -> list[RpcMethodSpec]:
        methods: list[RpcMethodSpec] = []
        for match in re.finditer(
            r"rpc\s+(?P<name>\w+)\s*\("
            r"(?P<req_stream>stream\s+)?(?P<req>[.\w]+)\)\s*returns\s*\("
            r"(?P<res_stream>stream\s+)?(?P<res>[.\w]+)\)",
            body,
        ):
            method_name = match.group("name")
            methods.append(
                RpcMethodSpec(
                    name=method_name,
                    python_name=self._to_snake(method_name),
                    request_type=match.group("req"),
                    response_type=match.group("res"),
                    client_streaming=bool(match.group("req_stream")),
                    server_streaming=bool(match.group("res_stream")),
                )
            )
        return methods

    def _to_snake(self, value: str) -> str:
        first_pass = re.sub("(.)([A-Z][a-z]+)", r"\1_\2", value)
        second_pass = re.sub("([a-z0-9])([A-Z])", r"\1_\2", first_pass)
        return second_pass.lower()

    def _module_alias(self, module_path: str) -> str:
        return re.sub(r"[^a-zA-Z0-9]+", "_", module_path).strip("_")

    def _symbol_alias(self, module_path: str, symbol: str) -> str:
        alias = f"{module_path}.{symbol}"
        return re.sub(r"[^a-zA-Z0-9]+", "_", alias).strip("_")

    def _sdk_app_name(self, rel_proto_path: Path) -> str:
        first = rel_proto_path.parts[0] if rel_proto_path.parts else "default"
        sanitized = re.sub(r"[^a-zA-Z0-9]+", "_", first).strip("_").lower()
        return sanitized or "default"

    def _render_init(self, package_name: str, specs: list[ServiceSpec]) -> str:
        service_exports = [spec.class_name for spec in specs]
        exports = [
            "ClientConfig",
            "GrpcClient",
            "TypedGrpcClient",
            "AuthProvider",
            "StaticTokenAuth",
            "RefreshingTokenAuth",
            "message_to_dict",
            "extract_results",
            *service_exports,
        ]
        lines = [
            "from .auth import AuthProvider, RefreshingTokenAuth, StaticTokenAuth",
            "from .client import GrpcClient",
            "from .config import ClientConfig",
            "from .helpers import extract_results, message_to_dict",
            "from .typed_services import TypedGrpcClient",
            "from .services import " + ", ".join(service_exports)
            if service_exports
            else "",
            "",
            f"__all__ = {exports!r}",
        ]
        return "\n".join(line for line in lines if line)

    def _render_auth(self) -> str:
        return (
            textwrap.dedent(
                """
            from __future__ import annotations

            import threading
            import time
            from collections.abc import Callable, Sequence
            from typing import Protocol


            class AuthProvider(Protocol):
                def get_metadata(self) -> Sequence[tuple[str, str]]:
                    ...


            class StaticTokenAuth:
                def __init__(
                    self,
                    token: str,
                    *,
                    header: str = "authorization",
                    prefix: str = "Bearer",
                ) -> None:
                    self.token = token
                    self.header = header
                    self.prefix = prefix

                def get_metadata(self) -> Sequence[tuple[str, str]]:
                    value = f"{self.prefix} {self.token}".strip()
                    return ((self.header, value),)


            class RefreshingTokenAuth:
                def __init__(
                    self,
                    token_provider: Callable[[], str],
                    *,
                    refresh_interval_sec: float = 300.0,
                    header: str = "authorization",
                    prefix: str = "Bearer",
                ) -> None:
                    self.token_provider = token_provider
                    self.refresh_interval_sec = refresh_interval_sec
                    self.header = header
                    self.prefix = prefix
                    self._token: str | None = None
                    self._expires_at = 0.0
                    self._lock = threading.Lock()

                def get_metadata(self) -> Sequence[tuple[str, str]]:
                    token = self._current_token()
                    value = f"{self.prefix} {token}".strip()
                    return ((self.header, value),)

                def _current_token(self) -> str:
                    now = time.monotonic()
                    if self._token is not None and now < self._expires_at:
                        return self._token
                    with self._lock:
                        now = time.monotonic()
                        if self._token is None or now >= self._expires_at:
                            self._token = self.token_provider()
                            self._expires_at = now + self.refresh_interval_sec
                        return self._token
            """
            ).strip()
            + "\n"
        )

    def _render_config(self, package_name: str) -> str:
        return (
            textwrap.dedent(
                """
            from __future__ import annotations

            from dataclasses import dataclass, field
            from typing import TYPE_CHECKING

            if TYPE_CHECKING:
                from .auth import AuthProvider


            @dataclass(frozen=True)
            class ClientConfig:
                host: str = "localhost:50051"
                secure: bool = False
                timeout: float | None = 10.0
                metadata: tuple[tuple[str, str], ...] = field(default_factory=tuple)
                auth_provider: "AuthProvider | None" = None
                root_certificates: bytes | None = None
            """
            ).strip()
            + "\n"
        )

    def _render_errors(self) -> str:
        return (
            textwrap.dedent(
                """
            from __future__ import annotations

            import grpc


            class SDKError(Exception):
                pass


            class NotFoundError(SDKError):
                pass


            class UnauthorizedError(SDKError):
                pass


            class InvalidArgumentError(SDKError):
                pass


            def map_rpc_error(exc: grpc.RpcError) -> SDKError:
                code = exc.code()
                details = exc.details() if callable(getattr(exc, "details", None)) else str(exc)
                if code == grpc.StatusCode.NOT_FOUND:
                    return NotFoundError(details)
                if code in {grpc.StatusCode.UNAUTHENTICATED, grpc.StatusCode.PERMISSION_DENIED}:
                    return UnauthorizedError(details)
                if code == grpc.StatusCode.INVALID_ARGUMENT:
                    return InvalidArgumentError(details)
                return SDKError(details)
            """
            ).strip()
            + "\n"
        )

    def _group_services_by_app(
        self, specs: list[ServiceSpec]
    ) -> dict[str, list[ServiceSpec]]:
        grouped: dict[str, list[ServiceSpec]] = {}
        for spec in specs:
            grouped.setdefault(spec.sdk_app, []).append(spec)
        return grouped

    def _group_messages_by_app(
        self, specs: list[MessageSpec]
    ) -> dict[str, list[MessageSpec]]:
        grouped: dict[str, list[MessageSpec]] = {}
        for spec in specs:
            grouped.setdefault(spec.sdk_app, []).append(spec)
        return grouped

    def _render_service_base(self) -> str:
        return (
            textwrap.dedent(
                """
            from __future__ import annotations

            from collections.abc import Iterable
            from typing import Any

            import grpc

            from .errors import map_rpc_error


            class BaseServiceClient:
                def __init__(self, grpc_client) -> None:
                    self._grpc_client = grpc_client
                    self._stub = None

                def _get_stub(self):
                    if self._stub is None:
                        self._stub = self.STUB_CLASS(self._grpc_client.channel)
                    return self._stub

                def _resolve_request_class(self, request_type: str):
                    if request_type == "google.protobuf.Empty":
                        from google.protobuf.empty_pb2 import Empty

                        return Empty
                    return getattr(self.PB2_MODULE, request_type.split(".")[-1], None)

                def _coerce_request(self, request_type: str, request: Any):
                    request_cls = self._resolve_request_class(request_type)
                    if request is None:
                        return request_cls() if request_cls is not None else None
                    if request_cls is not None and isinstance(request, request_cls):
                        return request
                    if request_cls is not None and isinstance(request, dict):
                        return request_cls(**request)
                    return request

                def _coerce_stream_request(self, request_type: str, request_iter: Iterable[Any]):
                    for item in request_iter:
                        yield self._coerce_request(request_type, item)

                def _invoke(self, method_name: str, request_type: str, request: Any, *, timeout=None, metadata=None):
                    stub = self._get_stub()
                    method = getattr(stub, method_name)
                    merged_metadata = self._grpc_client._build_metadata(metadata)
                    final_timeout = self._grpc_client.config.timeout if timeout is None else timeout
                    payload = self._coerce_request(request_type, request)
                    try:
                        return method(payload, timeout=final_timeout, metadata=merged_metadata)
                    except grpc.RpcError as exc:
                        raise map_rpc_error(exc) from exc

                def _invoke_stream(self, method_name: str, request_type: str, request_iter: Iterable[Any], *, timeout=None, metadata=None):
                    stub = self._get_stub()
                    method = getattr(stub, method_name)
                    merged_metadata = self._grpc_client._build_metadata(metadata)
                    final_timeout = self._grpc_client.config.timeout if timeout is None else timeout
                    payload = self._coerce_stream_request(request_type, request_iter)
                    try:
                        return method(payload, timeout=final_timeout, metadata=merged_metadata)
                    except grpc.RpcError as exc:
                        raise map_rpc_error(exc) from exc
            """
            ).strip()
            + "\n"
        )

    def _render_app_services(self, specs: list[ServiceSpec]) -> str:
        import_lines: list[str] = [
            "from __future__ import annotations",
            "",
            "from typing import Any",
            "",
            "from ..._service_base import BaseServiceClient",
        ]
        seen_stub_imports: set[tuple[str, str, str]] = set()
        seen_pb2_imports: set[tuple[str, str]] = set()
        for spec in specs:
            stub_import = (spec.stub_module, spec.stub_class, spec.stub_alias)
            if stub_import not in seen_stub_imports:
                import_lines.append(
                    f"from {spec.stub_module} import {spec.stub_class} as {spec.stub_alias}"
                )
                seen_stub_imports.add(stub_import)
            pb2_import = (spec.pb2_module, spec.pb2_alias)
            if pb2_import not in seen_pb2_imports:
                import_lines.append(f"import {spec.pb2_module} as {spec.pb2_alias}")
                seen_pb2_imports.add(pb2_import)
        lines = [*import_lines, "", ""]
        exports: list[str] = []
        for spec in specs:
            if exports:
                lines.extend(["", ""])
            lines.extend(
                [
                    f"class {spec.class_name}(BaseServiceClient):",
                    f"    STUB_CLASS = {spec.stub_alias}",
                    f"    PB2_MODULE = {spec.pb2_alias}",
                ]
            )
            for method in spec.methods:
                request_ref = self._message_ref(method.request_type, spec.pb2_alias)
                response_ref = self._message_ref(method.response_type, spec.pb2_alias)
                if method.client_streaming:
                    return_ref = (
                        f"Iterable[{response_ref}]"
                        if method.server_streaming
                        else response_ref
                    )
                    lines.extend(
                        [
                            "",
                            f"    def {method.python_name}(self, request: Iterable[{request_ref} | dict[str, Any]], *, timeout=None, metadata=None) -> {return_ref}:",
                            f'        return self._invoke_stream("{method.name}", "{method.request_type}", request, timeout=timeout, metadata=metadata)',
                        ]
                    )
                else:
                    return_ref = (
                        f"Iterable[{response_ref}]"
                        if method.server_streaming
                        else response_ref
                    )
                    lines.extend(
                        [
                            "",
                            f"    def {method.python_name}(self, request: {request_ref} | dict[str, Any] | None = None, *, timeout=None, metadata=None) -> {return_ref}:",
                            f'        return self._invoke("{method.name}", "{method.request_type}", request, timeout=timeout, metadata=metadata)',
                        ]
                    )
            exports.append(spec.class_name)
        lines.extend(["", "", f"__all__ = {exports!r}", ""])
        return "\n".join(lines)

    def _render_services_index(self, by_app: dict[str, list[ServiceSpec]]) -> str:
        lines = [
            "from __future__ import annotations",
            "",
            "from ._service_base import BaseServiceClient",
        ]
        for app in sorted(by_app):
            classes = ", ".join(spec.class_name for spec in by_app[app])
            if classes:
                lines.append(f"from .generated.{app}.services import {classes}")
        lines.extend(["", "SERVICE_CLIENTS = {"])
        for app in sorted(by_app):
            for spec in by_app[app]:
                lines.append(f'    "{spec.python_attr}": {spec.class_name},')
        lines.extend(["}", "", ""])
        exports = [spec.class_name for app in sorted(by_app) for spec in by_app[app]]
        lines.append(
            f"__all__ = {[*exports, 'BaseServiceClient', 'SERVICE_CLIENTS']!r}"
        )
        lines.append("")
        return "\n".join(lines)

    def _render_app_models(self, specs: list[MessageSpec]) -> str:
        lines = [
            "from __future__ import annotations",
            "",
            "from datetime import datetime",
            "",
            "from pydantic import BaseModel, ConfigDict, Field",
            "",
            "",
        ]
        exports: list[str] = []
        for spec in specs:
            if exports:
                lines.extend(["", ""])
            lines.extend(
                [
                    f"class {spec.model_name}(BaseModel):",
                    "    model_config = ConfigDict(extra='ignore', populate_by_name=True)",
                ]
            )
            if not spec.fields:
                lines.append("    pass")
            else:
                for field in spec.fields:
                    lines.append(
                        f"    {field.name}: {field.annotation} = {field.default_expr}"
                    )
            exports.append(spec.model_name)
        lines.extend(["", "", f"__all__ = {exports!r}", ""])
        return "\n".join(lines)

    def _render_models_index(self, by_app: dict[str, list[MessageSpec]]) -> str:
        lines = ["from __future__ import annotations", ""]
        exports: list[str] = []
        for app in sorted(by_app):
            classes = ", ".join(spec.model_name for spec in by_app[app])
            if classes:
                lines.append(f"from .generated.{app}.models import {classes}")
                exports.extend(spec.model_name for spec in by_app[app])
        lines.extend(["", "", f"__all__ = {exports!r}", ""])
        return "\n".join(lines)

    def _render_typed_base(self) -> str:
        return (
            textwrap.dedent(
                """
            from __future__ import annotations

            from collections.abc import Iterable
            from typing import Any

            from .helpers import message_to_dict


            class BaseTypedServiceClient:
                def __init__(self, raw_service) -> None:
                    self._raw = raw_service

                def _to_payload(self, request: Any):
                    if request is None:
                        return None
                    if hasattr(request, "model_dump"):
                        return request.model_dump(exclude_none=True, by_alias=True)
                    return request

                def _to_model(self, model_cls, response: Any):
                    if model_cls is Any:
                        return response
                    return model_cls.model_validate(message_to_dict(response))

                def _to_model_stream(self, model_cls, response_stream: Iterable[Any]):
                    for item in response_stream:
                        yield self._to_model(model_cls, item)
            """
            ).strip()
            + "\n"
        )

    def _render_app_typed_services(
        self,
        specs: list[ServiceSpec],
        model_name_map: dict[tuple[str, str], str],
    ) -> str:
        lines = [
            "from __future__ import annotations",
            "",
            "from collections.abc import Iterable",
            "from typing import Any",
            "",
            "from ... import models",
            "from ..._typed_base import BaseTypedServiceClient",
        ]
        raw_classes = ", ".join(spec.class_name for spec in specs)
        if raw_classes:
            lines.append(f"from .services import {raw_classes}")
        lines.extend(["", ""])
        exports: list[str] = []
        for spec in specs:
            typed_class_name = f"Typed{spec.class_name}"
            if exports:
                lines.extend(["", ""])
            lines.extend(
                [
                    f"class {typed_class_name}(BaseTypedServiceClient):",
                    "    def __init__(self, grpc_client) -> None:",
                    f"        super().__init__({spec.class_name}(grpc_client))",
                ]
            )
            for method in spec.methods:
                req_key = (spec.pb2_alias, method.request_type.split(".")[-1])
                res_key = (spec.pb2_alias, method.response_type.split(".")[-1])
                req_model_name = (
                    model_name_map[req_key]
                    if method.request_type != "google.protobuf.Empty"
                    and req_key in model_name_map
                    else "Any"
                )
                if method.response_type == "google.protobuf.Empty":
                    res_model_name = "Any"
                else:
                    res_model_name = model_name_map.get(res_key, "Any")
                request_type_hint = (
                    "None"
                    if method.request_type == "google.protobuf.Empty"
                    else f"models.{req_model_name} | dict[str, Any] | None"
                )
                response_type_hint = (
                    f"Iterable[models.{res_model_name}]"
                    if method.server_streaming and res_model_name != "Any"
                    else (
                        "Iterable[Any]"
                        if method.server_streaming
                        else f"models.{res_model_name}"
                    )
                    if res_model_name != "Any"
                    else ("Iterable[Any]" if method.server_streaming else "Any")
                )
                lines.extend(
                    [
                        "",
                        f"    def {method.python_name}(self, request: {request_type_hint} = None, *, timeout=None, metadata=None) -> {response_type_hint}:",
                        "        payload = self._to_payload(request)",
                        f"        response = self._raw.{method.python_name}(payload, timeout=timeout, metadata=metadata)",
                        f"        model_cls = models.{res_model_name} if '{res_model_name}' != 'Any' else Any",
                        "        if isinstance(response, Iterable) and not isinstance(response, (bytes, str, dict)):",
                        "            return self._to_model_stream(model_cls, response)",
                        "        return self._to_model(model_cls, response)",
                    ]
                )
            exports.append(typed_class_name)
        lines.extend(["", "", f"__all__ = {exports!r}", ""])
        return "\n".join(lines)

    def _render_typed_services_index(self, by_app: dict[str, list[ServiceSpec]]) -> str:
        lines = ["from __future__ import annotations", "", "from typing import Any", ""]
        for app in sorted(by_app):
            classes = ", ".join(f"Typed{spec.class_name}" for spec in by_app[app])
            if classes:
                lines.append(f"from .generated.{app}.typed_services import {classes}")
        lines.extend(
            [
                "",
                "",
                "class TypedGrpcClient:",
                "    def __init__(self, grpc_client) -> None:",
                "        self._grpc_client = grpc_client",
                "        self._cache: dict[str, Any] = {}",
                "",
                "    def service(self, name: str):",
                "        if name not in self._cache:",
                "            cls = TYPED_SERVICE_CLIENTS[name]",
                "            self._cache[name] = cls(self._grpc_client)",
                "        return self._cache[name]",
            ]
        )
        for app in sorted(by_app):
            for spec in by_app[app]:
                typed_name = f"Typed{spec.class_name}"
                lines.extend(
                    [
                        "",
                        "    @property",
                        f"    def {spec.python_attr}(self) -> {typed_name}:",
                        f'        return self.service("{spec.python_attr}")',
                    ]
                )
        lines.extend(["", "", "TYPED_SERVICE_CLIENTS = {"])
        for app in sorted(by_app):
            for spec in by_app[app]:
                lines.append(f'    "{spec.python_attr}": Typed{spec.class_name},')
        lines.extend(["}", "", "__all__ = ['TypedGrpcClient']", ""])
        return "\n".join(lines)

    def _message_ref(self, message_type: str, pb2_alias: str) -> str:
        if message_type == "google.protobuf.Empty":
            return "Any"
        return f"{pb2_alias}.{message_type.split('.')[-1]}"

    def _render_generated_client(self, specs: list[ServiceSpec]) -> str:
        service_imports = ", ".join(spec.class_name for spec in specs)
        services_import_line = (
            f"from .services import SERVICE_CLIENTS, {service_imports}"
            if service_imports
            else "from .services import SERVICE_CLIENTS"
        )
        lines = [
            "from __future__ import annotations",
            "",
            "from typing import Any, cast",
            "",
            "import grpc",
            "",
            "from .config import ClientConfig",
            services_import_line,
            "from .typed_services import TypedGrpcClient",
            "",
            "",
            "class GeneratedGrpcClient:",
            "    def __init__(self, config: ClientConfig | None = None) -> None:",
            "        self.config = config or ClientConfig()",
            "        self._channel = None",
            "        self._service_cache: dict[str, Any] = {}",
            "        self._typed = None",
            "",
            "    @property",
            "    def channel(self):",
            "        if self._channel is None:",
            "            if self.config.secure:",
            "                creds = grpc.ssl_channel_credentials(",
            "                    root_certificates=self.config.root_certificates",
            "                )",
            "                self._channel = grpc.secure_channel(self.config.host, creds)",
            "            else:",
            "                self._channel = grpc.insecure_channel(self.config.host)",
            "        return self._channel",
            "",
            "    def _build_metadata(self, metadata):",
            "        base = list(self.config.metadata)",
            "        auth_provider = self.config.auth_provider",
            "        if auth_provider is not None:",
            "            base.extend(auth_provider.get_metadata())",
            "        if metadata:",
            "            base.extend(list(metadata))",
            "        return tuple(base)",
            "",
            "    def service(self, name: str):",
            "        if name not in self._service_cache:",
            "            service_cls = SERVICE_CLIENTS[name]",
            "            self._service_cache[name] = service_cls(self)",
            "        return self._service_cache[name]",
            "",
            "    @property",
            "    def typed(self) -> TypedGrpcClient:",
            "        if self._typed is None:",
            "            self._typed = TypedGrpcClient(self)",
            "        return self._typed",
        ]
        for spec in specs:
            lines.extend(
                [
                    "",
                    "    @property",
                    f"    def {spec.python_attr}(self) -> {spec.class_name}:",
                    f'        return cast({spec.class_name}, self.service("{spec.python_attr}"))',
                ]
            )
        lines.extend(
            [
                "",
                "    def close(self) -> None:",
                "        if self._channel is not None:",
                "            self._channel.close()",
                "            self._channel = None",
                "",
                "    def __getattr__(self, item: str):",
                "        if item in SERVICE_CLIENTS:",
                "            return self.service(item)",
                "        raise AttributeError(item)",
                "",
            ]
        )
        return "\n".join(lines)

    def _render_client_wrapper(self) -> str:
        return (
            textwrap.dedent(
                """
            from __future__ import annotations

            from .client_generated import GeneratedGrpcClient


            class GrpcClient(GeneratedGrpcClient):
                \"\"\"Customizable SDK client.

                Keep project-specific logic here; generator will not overwrite this file
                when target SDK directory already exists.
                \"\"\"
            """
            ).strip()
            + "\n"
        )

    def _render_helpers(self) -> str:
        return (
            textwrap.dedent(
                """
            from __future__ import annotations

            import inspect
            from typing import Any

            from google.protobuf.json_format import MessageToDict


            def message_to_dict(message: Any) -> dict[str, Any]:
                \"\"\"Convert protobuf message to plain Python dict.\"\"\"
                kwargs: dict[str, Any] = {"preserving_proto_field_name": True}
                params = inspect.signature(MessageToDict).parameters
                if "always_print_fields_with_no_presence" in params:
                    kwargs["always_print_fields_with_no_presence"] = True
                elif "including_default_value_fields" in params:
                    kwargs["including_default_value_fields"] = True
                return MessageToDict(message, **kwargs)


            def extract_results(message_or_dict: Any) -> list[Any]:
                \"\"\"Return paginated `results` list when present, otherwise empty list.\"\"\"
                if isinstance(message_or_dict, dict):
                    payload = message_or_dict
                else:
                    payload = message_to_dict(message_or_dict)
                value = payload.get("results", [])
                return value if isinstance(value, list) else []
            """
            ).strip()
            + "\n"
        )

    def _render_pyproject(self, sdk_name: str, package_name: str) -> str:
        return (
            textwrap.dedent(
                f"""
            [build-system]
            requires = ["setuptools>=68", "wheel"]
            build-backend = "setuptools.build_meta"

            [project]
            name = "{sdk_name}"
            version = "0.1.0"
            description = "Generated gRPC Python SDK"
            readme = "README.md"
            requires-python = ">=3.10"
            dependencies = [
              "grpcio>=1.50",
              "protobuf>=4.25",
              "pydantic>=2.0",
            ]

            [tool.setuptools]
            package-dir = {{"" = "src"}}
            include-package-data = true

            [tool.setuptools.packages.find]
            where = ["src"]
            include = ["*"]
            """
            ).strip()
            + "\n"
        )

    def _render_readme(self, sdk_name: str, package_name: str) -> str:
        return (
            textwrap.dedent(
                f"""
            # {sdk_name}

            Generated Python gRPC SDK.

            This SDK has two access layers:
            - raw protobuf client (`client.<service>.<method>()`)
            - typed client (`client.typed.<service>.<method>()`) based on generated Pydantic models

            ## Quickstart

            ```python
            from {package_name} import (
                ClientConfig,
                GrpcClient,
                StaticTokenAuth,
                message_to_dict,
                extract_results,
            )

            client = GrpcClient(
                ClientConfig(
                    host="localhost:50051",
                    auth_provider=StaticTokenAuth("<token>"),
                )
            )

            # Raw protobuf response
            raw_resp = client.product.list({{"limit": 20}})
            raw_payload = message_to_dict(raw_resp)
            rows = extract_results(raw_resp)  # paginated list helper

            # Typed response (Pydantic models generated from proto)
            typed_resp = client.typed.product.list({{"limit": 20}})
            ```

            ## Generated layout

            ```text
            src/{package_name}/
              client.py                  # custom layer (not overwritten if exists)
              client_generated.py        # regenerated
              helpers.py                 # helper functions (not overwritten if exists)
              services.py                # facade, regenerated
              typed_services.py          # facade, regenerated
              models.py                  # facade, regenerated
              generated/
                <app>/
                  services.py            # regenerated
                  typed_services.py      # regenerated
                  models.py              # regenerated
            ```

            ## Notes

            - `client.py` is safe for custom logic.
            - `helpers.py` is safe for custom additions.
            - files under `generated/` are fully regenerated.
            """
            ).strip()
            + "\n"
        )


class PhpClientSDKGenerator(BaseClientSDKGenerator):
    language = "php"

    def generate(
        self,
        *,
        proto_files: Iterable[Path],
        out_dir: Path,
        sdk_name: str,
        include_root: Path,
    ) -> Path:
        protoc_bin = shutil.which("protoc")
        if not protoc_bin:
            raise SDKGenerationError(
                "protoc is required for PHP SDK generation and was not found in PATH."
            )

        configured = getattr(django_settings, "GRPC_EXTRA", {}) or {}
        plugin_path = configured.get("PHP_GRPC_PLUGIN")
        if not plugin_path:
            raise SDKGenerationError(
                "GRPC_EXTRA['PHP_GRPC_PLUGIN'] must point to grpc_php_plugin."
            )
        plugin = Path(str(plugin_path))
        if not plugin.exists():
            raise SDKGenerationError(f"grpc_php_plugin was not found: {plugin}")

        target_dir = out_dir / sdk_name
        target_dir.mkdir(parents=True, exist_ok=True)

        for proto_file in proto_files:
            args = [
                protoc_bin,
                f"-I{include_root}",
                f"--php_out={target_dir}",
                f"--grpc_out={target_dir}",
                f"--plugin=protoc-gen-grpc={plugin}",
                str(proto_file),
            ]
            completed = subprocess.run(
                args,
                capture_output=True,
                text=True,
                check=False,
            )
            if completed.returncode != 0:
                raise SDKGenerationError(
                    f"protoc failed for {proto_file}: {completed.stderr.strip()}"
                )

        return target_dir
