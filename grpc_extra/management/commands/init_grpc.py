from __future__ import annotations

from pathlib import Path
from typing import Iterable

from django.apps import apps
from django.core.management.base import BaseCommand, CommandError


class Command(BaseCommand):
    help = "Initialize gRPC module scaffold inside Django apps."

    def add_arguments(self, parser):
        parser.add_argument(
            "--app",
            action="append",
            default=[],
            help="App label to scaffold (repeatable).",
        )
        parser.add_argument(
            "--all",
            action="store_true",
            help="Scaffold for every installed app.",
        )
        parser.add_argument(
            "--force",
            action="store_true",
            help="Overwrite existing grpc files.",
        )

    def handle(self, *args, **options):
        app_labels = options.get("app", [])
        all_flag = options.get("all", False)
        force = options.get("force", False)

        if not all_flag and not app_labels:
            all_flag = True

        if all_flag and app_labels:
            raise CommandError("Use either --all or --app, not both.")

        if all_flag:
            target_configs = list(apps.get_app_configs())
        else:
            target_configs = self._apps_by_label(app_labels)

        if not target_configs:
            raise CommandError("No matching apps found.")

        created = 0
        skipped = 0
        for app_conf in target_configs:
            result = self._init_grpc_for_app(app_conf, force=force)
            created += result["created"]
            skipped += result["skipped"]

        self.stdout.write(
            f"gRPC scaffold complete. created={created} skipped={skipped}"
        )

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

    def _init_grpc_for_app(self, app_conf, force: bool) -> dict:
        app_path = Path(app_conf.path)
        grpc_dir = app_path / "grpc"
        proto_dir = grpc_dir / "proto"

        files = {
            grpc_dir / "__init__.py": self._render_grpc_init(app_conf.label),
            grpc_dir / "services.py": self._render_services_stub(app_conf.label),
            proto_dir / "__init__.py": self._render_proto_init(),
        }

        created = 0
        skipped = 0
        for path, content in files.items():
            if path.exists() and not force:
                self.stdout.write(f"skip {path}")
                skipped += 1
                continue

            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(content, encoding="utf-8")
            self.stdout.write(f"write {path}")
            created += 1

        return {"created": created, "skipped": skipped}

    def _render_grpc_init(self, label: str) -> str:
        return f'"""gRPC module for `{label}` app."""\n__all__ = []\n'

    def _render_proto_init(self) -> str:
        return '"""gRPC proto package."""\n__all__ = []\n'

    def _render_services_stub(self, label: str) -> str:
        return (
            '"""gRPC service implementations."""\n'
            "\n"
            "# TODO: define your services here with @grpc_service and @grpc_method\n"
        )
