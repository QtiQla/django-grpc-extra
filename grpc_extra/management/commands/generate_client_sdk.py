from __future__ import annotations

from pathlib import Path
from typing import Iterable

from django.apps import AppConfig, apps
from django.conf import settings as django_settings
from django.core.management import call_command
from django.core.management.base import BaseCommand, CommandError
from django.utils.module_loading import import_string

from grpc_extra.main import GrpcExtra
from grpc_extra.registry import ServiceDefinition, registry
from grpc_extra.sdk.generators import BaseClientSDKGenerator, SDKGenerationError
from grpc_extra.utils import normalize_proto_path


DEFAULT_SDK_GENERATORS = {
    "python": "grpc_extra.sdk.generators.PythonClientSDKGenerator",
    "php": "grpc_extra.sdk.generators.PhpClientSDKGenerator",
}


class Command(BaseCommand):
    help = "Generate language-specific client SDK from project proto files."

    def add_arguments(self, parser):
        parser.add_argument("--language", required=True, help="Target SDK language.")
        parser.add_argument(
            "--out",
            default="generated-sdks",
            help="Directory where SDK artifact will be generated.",
        )
        parser.add_argument(
            "--name",
            default=None,
            help="SDK package/directory name. Defaults to django-grpc-extra-<language>-client-sdk.",
        )
        parser.add_argument(
            "--app",
            action="append",
            default=[],
            help="App label to include (repeatable).",
        )
        parser.add_argument(
            "--all",
            action="store_true",
            help="Include all installed apps.",
        )
        parser.add_argument(
            "--skip-proto",
            action="store_true",
            help="Skip proto regeneration and use existing proto files.",
        )

    def handle(self, *args, **options):
        language = str(options["language"]).lower()
        out_dir = Path(options["out"])
        name = options.get("name") or f"django-grpc-extra-{language}-client-sdk"
        app_labels = options.get("app", [])
        include_all = options.get("all", False)
        skip_proto = options.get("skip_proto", False)

        if include_all and app_labels:
            raise CommandError("Use either --all or --app, not both.")

        if not include_all and not app_labels:
            include_all = True

        if not skip_proto:
            call_command(
                "generate_proto",
                all=include_all,
                app=app_labels,
                no_compile=True,
            )

        app_configs = (
            list(apps.get_app_configs())
            if include_all
            else [apps.get_app_config(label) for label in app_labels]
        )
        app_by_label = {app.label: app for app in app_configs}

        registry.clear()
        GrpcExtra().auto_discover_services()
        definitions = list(registry.all())
        if not definitions:
            raise CommandError("No decorated services found.")

        proto_files = self._collect_proto_files(definitions, app_by_label)
        if not proto_files:
            raise CommandError("No proto files found for selected apps.")

        include_root = self._include_root(app_configs)
        generator = self._resolve_generator(language)
        try:
            target = generator.generate(
                proto_files=proto_files,
                out_dir=out_dir,
                sdk_name=name,
                include_root=include_root,
            )
        except SDKGenerationError as exc:
            raise CommandError(str(exc)) from exc

        self.stdout.write(f"client sdk generated: {target}")

    def _collect_proto_files(
        self,
        definitions: Iterable[ServiceDefinition],
        app_by_label: dict[str, AppConfig],
    ) -> list[Path]:
        proto_files: list[Path] = []
        seen: set[Path] = set()
        for definition in definitions:
            app_conf = app_by_label.get(definition.meta.app_label)
            if app_conf is None:
                continue
            if not definition.meta.proto_path:
                continue
            proto_rel = normalize_proto_path(definition.meta.proto_path)
            proto_abs = Path(app_conf.path) / proto_rel
            if proto_abs.exists() and proto_abs not in seen:
                proto_files.append(proto_abs)
                seen.add(proto_abs)
        return proto_files

    def _include_root(self, app_configs: list[AppConfig]) -> Path:
        roots = {Path(app.path).parent for app in app_configs}
        if len(roots) != 1:
            raise CommandError(
                "Apps have different include roots; use --app for a single app root."
            )
        return roots.pop()

    def _resolve_generator(self, language: str) -> BaseClientSDKGenerator:
        configured = getattr(django_settings, "GRPC_EXTRA", {}) or {}
        mapping = dict(DEFAULT_SDK_GENERATORS)
        mapping.update(configured.get("SDK_GENERATORS", {}))
        path = mapping.get(language)
        if not path:
            raise CommandError(f"SDK generator is not configured for language '{language}'.")
        value = import_string(path)
        instance = value() if isinstance(value, type) else value
        if not isinstance(instance, BaseClientSDKGenerator):
            raise CommandError(
                f"SDK generator '{path}' must inherit BaseClientSDKGenerator."
            )
        return instance
