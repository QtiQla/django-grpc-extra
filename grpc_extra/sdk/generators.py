from __future__ import annotations

import shutil
import subprocess
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
            from grpc_tools import protoc
        except ImportError as exc:
            raise SDKGenerationError(
                "grpcio-tools is required for Python SDK generation."
            ) from exc

        target_dir = out_dir / sdk_name
        target_dir.mkdir(parents=True, exist_ok=True)
        (target_dir / "__init__.py").touch(exist_ok=True)

        for proto_file in proto_files:
            args = [
                "protoc",
                f"-I{include_root}",
                f"--python_out={target_dir}",
                f"--grpc_python_out={target_dir}",
                str(proto_file),
            ]
            result = protoc.main(args)
            if result != 0:
                raise SDKGenerationError(f"protoc failed for {proto_file}")

        return target_dir


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
