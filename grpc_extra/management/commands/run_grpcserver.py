from __future__ import annotations

import argparse
from collections.abc import Iterable
from contextlib import contextmanager
from typing import Any

from django.conf import settings as django_settings
from django.core.management.base import BaseCommand, CommandError
from django.utils.module_loading import import_string

from grpc_extra.main import GrpcExtra


class Command(BaseCommand):
    help = "Run gRPC server using GrpcExtra runtime."

    def add_arguments(self, parser):
        parser.add_argument("--bind", help="Bind address, e.g. [::]:50051.")
        parser.add_argument("--max-workers", type=int, help="Thread pool size.")
        parser.add_argument("--max-msg-mb", type=int, help="Max message size in MB.")
        parser.add_argument(
            "--health",
            action=argparse.BooleanOptionalAction,
            default=None,
            help="Enable/disable health service.",
        )
        parser.add_argument(
            "--reflection",
            action=argparse.BooleanOptionalAction,
            default=None,
            help="Enable/disable reflection service.",
        )
        parser.add_argument(
            "--reload",
            action=argparse.BooleanOptionalAction,
            default=None,
            help="Enable/disable live reload (requires watchfiles).",
        )
        parser.add_argument(
            "--discover",
            action=argparse.BooleanOptionalAction,
            default=True,
            help="Enable/disable auto-discovery of gRPC services.",
        )
        parser.add_argument(
            "--reload-path",
            action="append",
            default=[],
            help="Path to watch in reload mode (repeatable).",
        )
        parser.add_argument(
            "--auth-backend",
            help="Auth backend import path, e.g. path.to.auth_backend.",
        )
        parser.add_argument(
            "--interceptor",
            action="append",
            default=[],
            help="Interceptor import path (instance or zero-arg class). Repeatable.",
        )
        parser.add_argument(
            "--request-logging",
            action=argparse.BooleanOptionalAction,
            default=None,
            help="Enable/disable request logging interceptor.",
        )
        parser.add_argument(
            "--logger-name",
            help="Logger name for request logging (default: grpc_extra).",
        )

    def handle(self, *args, **options):
        interceptors = self._resolve_interceptors(options.get("interceptor", []))
        runtime_kwargs = {
            "bind": options.get("bind"),
            "max_workers": options.get("max_workers"),
            "max_msg_mb": options.get("max_msg_mb"),
            "enable_health": options.get("health"),
            "enable_reflection": options.get("reflection"),
            "auth_backend": options.get("auth_backend"),
            "interceptors": interceptors if interceptors else None,
            "reload": options.get("reload"),
            "reload_paths": options.get("reload_path") or None,
            "auto_discover": options.get("discover", True),
        }
        runtime_kwargs = {
            key: value for key, value in runtime_kwargs.items() if value is not None
        }

        settings_overrides = {}
        if options.get("request_logging") is not None:
            settings_overrides["ENABLE_REQUEST_LOGGING"] = options["request_logging"]
        if options.get("logger_name"):
            settings_overrides["LOGGER_NAME"] = options["logger_name"]

        with self._override_grpc_settings(**settings_overrides):
            GrpcExtra().run_server(**runtime_kwargs)

    def _resolve_interceptors(self, paths: Iterable[str]) -> list[object]:
        resolved: list[object] = []
        for path in paths:
            try:
                value = import_string(path)
            except Exception as exc:
                raise CommandError(f"Invalid interceptor path '{path}': {exc}") from exc
            if isinstance(value, type):
                try:
                    value = value()
                except Exception as exc:
                    raise CommandError(
                        f"Interceptor class '{path}' must be instantiable without args."
                    ) from exc
            resolved.append(value)
        return resolved

    @contextmanager
    def _override_grpc_settings(self, **patch: Any):
        current = getattr(django_settings, "GRPC_EXTRA", {}) or {}
        merged = dict(current)
        merged.update(patch)
        django_settings.GRPC_EXTRA = merged
        try:
            yield
        finally:
            django_settings.GRPC_EXTRA = current
