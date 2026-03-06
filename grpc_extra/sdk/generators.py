from __future__ import annotations

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
    service_name: str
    python_attr: str
    class_name: str
    stub_module: str
    stub_class: str
    stub_alias: str
    pb2_module: str
    pb2_alias: str
    methods: list[RpcMethodSpec]


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
            args.append(str(proto_file))
            result = protoc.main(args)
            if result != 0:
                raise SDKGenerationError(f"protoc failed for {proto_file}")
            self._ensure_python_package_tree(src_dir, proto_file, include_root)

        service_specs = self._collect_service_specs(proto_list, include_root)

        (runtime_dir / "__init__.py").write_text(
            self._render_init(package_name, service_specs), encoding="utf-8"
        )
        (runtime_dir / "auth.py").write_text(self._render_auth(), encoding="utf-8")
        (runtime_dir / "config.py").write_text(
            self._render_config(package_name), encoding="utf-8"
        )
        (runtime_dir / "errors.py").write_text(self._render_errors(), encoding="utf-8")
        (runtime_dir / "services.py").write_text(
            self._render_services(service_specs), encoding="utf-8"
        )
        (runtime_dir / "client.py").write_text(
            self._render_client(service_specs), encoding="utf-8"
        )

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
                        service_name=service_name,
                        python_attr=self._to_snake(
                            service_name.removesuffix("Service") or service_name
                        ),
                        class_name=f"{service_name}Client",
                        stub_module=f"{module_base}_pb2_grpc",
                        stub_class=f"{service_name}Stub",
                        stub_alias=self._module_alias(f"{module_base}_pb2_grpc"),
                        pb2_module=f"{module_base}_pb2",
                        pb2_alias=self._module_alias(f"{module_base}_pb2"),
                        methods=methods,
                    )
                )
        return specs

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

    def _render_init(self, package_name: str, specs: list[ServiceSpec]) -> str:
        service_exports = [spec.class_name for spec in specs]
        exports = [
            "ClientConfig",
            "GrpcClient",
            "AuthProvider",
            "StaticTokenAuth",
            "RefreshingTokenAuth",
            *service_exports,
        ]
        lines = [
            "from .auth import AuthProvider, RefreshingTokenAuth, StaticTokenAuth",
            "from .client import GrpcClient",
            "from .config import ClientConfig",
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

    def _render_services(self, specs: list[ServiceSpec]) -> str:
        import_lines: list[str] = []
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

        lines = [
            "from __future__ import annotations",
            "",
            "from collections.abc import Iterable",
            "from typing import Any",
            "",
            "import grpc",
            "",
            "from .errors import map_rpc_error",
            *import_lines,
            "",
            "",
            "class BaseServiceClient:",
            "    def __init__(self, grpc_client) -> None:",
            "        self._grpc_client = grpc_client",
            "        self._stub = None",
            "",
            "    def _get_stub(self):",
            "        if self._stub is None:",
            "            self._stub = self.STUB_CLASS(self._grpc_client.channel)",
            "        return self._stub",
            "",
            "    def _resolve_request_class(self, request_type: str):",
            '        if request_type == "google.protobuf.Empty":',
            "            from google.protobuf.empty_pb2 import Empty",
            "",
            "            return Empty",
            '        return getattr(self.PB2_MODULE, request_type.split(".")[-1], None)',
            "",
            "    def _coerce_request(self, request_type: str, request: Any):",
            "        request_cls = self._resolve_request_class(request_type)",
            "        if request is None:",
            "            return request_cls() if request_cls is not None else None",
            "        if request_cls is not None and isinstance(request, request_cls):",
            "            return request",
            "        if request_cls is not None and isinstance(request, dict):",
            "            return request_cls(**request)",
            "        return request",
            "",
            "    def _coerce_stream_request(self, request_type: str, request_iter: Iterable[Any]):",
            "        for item in request_iter:",
            "            yield self._coerce_request(request_type, item)",
            "",
            "    def _invoke(self, method_name: str, request_type: str, request: Any, *, timeout=None, metadata=None):",
            "        stub = self._get_stub()",
            "        method = getattr(stub, method_name)",
            "        merged_metadata = self._grpc_client._build_metadata(metadata)",
            "        final_timeout = self._grpc_client.config.timeout if timeout is None else timeout",
            "        payload = self._coerce_request(request_type, request)",
            "        try:",
            "            return method(payload, timeout=final_timeout, metadata=merged_metadata)",
            "        except grpc.RpcError as exc:",
            "            raise map_rpc_error(exc) from exc",
            "",
            "    def _invoke_stream(self, method_name: str, request_type: str, request_iter: Iterable[Any], *, timeout=None, metadata=None):",
            "        stub = self._get_stub()",
            "        method = getattr(stub, method_name)",
            "        merged_metadata = self._grpc_client._build_metadata(metadata)",
            "        final_timeout = self._grpc_client.config.timeout if timeout is None else timeout",
            "        payload = self._coerce_stream_request(request_type, request_iter)",
            "        try:",
            "            return method(payload, timeout=final_timeout, metadata=merged_metadata)",
            "        except grpc.RpcError as exc:",
            "            raise map_rpc_error(exc) from exc",
            "",
        ]

        alias_entries: list[str] = []
        client_entries: list[str] = []

        for spec in specs:
            lines.extend(
                [
                    "",
                    f"class {spec.class_name}(BaseServiceClient):",
                    f"    STUB_CLASS = {spec.stub_alias}",
                    f"    PB2_MODULE = {spec.pb2_alias}",
                ]
            )
            for method in spec.methods:
                if method.client_streaming:
                    lines.extend(
                        [
                            "",
                            f"    def {method.python_name}(self, request: Iterable[Any], *, timeout=None, metadata=None):",
                            f'        return self._invoke_stream("{method.name}", "{method.request_type}", request, timeout=timeout, metadata=metadata)',
                        ]
                    )
                else:
                    lines.extend(
                        [
                            "",
                            f"    def {method.python_name}(self, request: Any = None, *, timeout=None, metadata=None):",
                            f'        return self._invoke("{method.name}", "{method.request_type}", request, timeout=timeout, metadata=metadata)',
                        ]
                    )

            alias_entries.append(f'    "{spec.python_attr}": {spec.class_name},')
            client_entries.append(spec.class_name)

        lines.extend(
            [
                "",
                "SERVICE_CLIENTS = {",
                *alias_entries,
                "}",
                "",
                f"__all__ = {[*client_entries, 'BaseServiceClient', 'SERVICE_CLIENTS']!r}",
            ]
        )

        return "\n".join(lines) + "\n"

    def _render_client(self, specs: list[ServiceSpec]) -> str:
        return (
            textwrap.dedent(
                """
            from __future__ import annotations

            from typing import Any

            import grpc

            from .config import ClientConfig
            from .services import SERVICE_CLIENTS


            class GrpcClient:
                def __init__(self, config: ClientConfig | None = None) -> None:
                    self.config = config or ClientConfig()
                    self._channel = None
                    self._service_cache: dict[str, Any] = {}

                @property
                def channel(self):
                    if self._channel is None:
                        if self.config.secure:
                            creds = grpc.ssl_channel_credentials(
                                root_certificates=self.config.root_certificates
                            )
                            self._channel = grpc.secure_channel(self.config.host, creds)
                        else:
                            self._channel = grpc.insecure_channel(self.config.host)
                    return self._channel

                def _build_metadata(self, metadata):
                    base = list(self.config.metadata)
                    auth_provider = self.config.auth_provider
                    if auth_provider is not None:
                        base.extend(auth_provider.get_metadata())
                    if metadata:
                        base.extend(list(metadata))
                    return tuple(base)

                def service(self, name: str):
                    if name not in self._service_cache:
                        service_cls = SERVICE_CLIENTS[name]
                        self._service_cache[name] = service_cls(self)
                    return self._service_cache[name]

                def close(self) -> None:
                    if self._channel is not None:
                        self._channel.close()
                        self._channel = None

                def __getattr__(self, item: str):
                    if item in SERVICE_CLIENTS:
                        return self.service(item)
                    raise AttributeError(item)
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

            ## Quickstart

            ```python
            from {package_name} import ClientConfig, GrpcClient, StaticTokenAuth

            client = GrpcClient(
                ClientConfig(
                    host="localhost:50051",
                    auth_provider=StaticTokenAuth("<token>"),
                )
            )

            # Example service call
            # response = client.division.list({{"search": "foo"}})
            ```
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
