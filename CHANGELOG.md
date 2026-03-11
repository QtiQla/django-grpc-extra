# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project follows [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [0.2.0] - 2026-03-12

### Added

- Python SDK generation improvements:
  - typed SDK layer (`client.typed.<service>.<method>()`)
  - Pydantic models generated from proto contracts
  - helper module with `message_to_dict(...)` and `extract_results(...)`
- Per-app SDK generated layout to avoid monolithic files:
  - `generated/<app>/services.py`
  - `generated/<app>/typed_services.py`
  - `generated/<app>/models.py`
- SDK command documentation (`generate_client_sdk`) with explicit Experimental status.

### Changed

- Python SDK generator architecture updated:
  - generated and custom-safe files are separated
  - `client.py` and `helpers.py` are preserved if already present
  - generated facades and `generated/<app>/...` are regenerated on each run
- README updated with SDK usage examples (`raw` and `typed`) and generated layout details.
- Project version moved to stable `0.2.0`.

## [0.1.1b1] - 2026-03-08

### Changed

- Release version moved to beta track after initial `0.1.0` publication.
- Added explicit runtime dependency `typing-extensions` for Python 3.10 typing compatibility.
- Added PyPI and documentation badges to `README.md`.

### Fixed

- Python 3.10 compatibility:
  - replaced `StrEnum` usage with a Python 3.10-compatible string enum base
  - replaced `typing.Self` import with `typing_extensions.Self`
- CI typing environment:
  - GitHub test workflow now installs `requirements-tests.txt` before running `mypy`.

## [0.1.0] - 2026-03-08

First public beta release.

### Added

- Decorator-first gRPC API for Django:
  - `@grpc_service`, `@grpc_method`
  - method decorators: `@grpc_pagination`, `@grpc_searching`, `@grpc_ordering`, `@grpc_permissions`
- Service/method metadata registry with validation for decorator-first declaration flow.
- Proto generation command:
  - `python manage.py generate_proto`
  - generation from Pydantic schemas
  - optional pb2/pb2_grpc compilation
  - optional `.pyi` generation
- Proto naming customization settings:
  - `SCHEMA_SUFFIX_STRIP`
  - `REQUEST_SUFFIX`
  - `RESPONSE_SUFFIX`
- Runtime adapter:
  - decode `pb2 -> pydantic`
  - encode Python results (`dict`, pydantic model, dataclass, Django model) -> `pb2`
  - unary/streaming mode support
- Exception mapping pipeline with gRPC status conversion for validation, permission and runtime errors.
- gRPC server runner:
  - `GrpcExtra.run_server(...)`
  - autodiscovery by module pattern
  - optional health and reflection
  - request logging interceptor support
  - live reload support via watchfiles
- Management command:
  - `python manage.py run_grpcserver`
  - flags for bind/workers/message-size/health/reflection/reload/auth/interceptors/discovery
- Scaffold command:
  - `python manage.py init_grpc`
  - per-app or all-app gRPC folder bootstrap
- `ModelService` with endpoint autogeneration:
  - `List`, `StreamList`, `Detail`, `Create`, `Update`, `Patch`, `Delete`
- ModelService filtering:
  - plain pydantic filter schema support
  - `ModelFilterSchema` (`Q`-based) with ops: `exact`, `in`, `not_in`, `lt`, `gt`, `lte`, `gte`
- Searching and ordering integration for querysets and list-like results.
- Pagination integration (default `LimitOffsetPagination`) for unary list endpoints.
- Permission system:
  - abstract base permission with method-level and object-level checks
  - built-in permissions (`AllowAny`, authenticated variants, model-style permission checks)
- Authentication backend interfaces for gRPC metadata-based auth flows (including bearer-style base backend).
- SDK generation command and generator abstraction:
  - `python manage.py generate_client_sdk`
  - base generator interface + Python/PHP generator implementations
- Project documentation site (MkDocs Material), including:
  - quickstart and installation
  - core runtime/decorators/server/auth/permissions
  - model service sections
  - commands reference
  - settings/errors/FAQ

### Changed

- Project maturity classifier lowered to Beta:
  - `Development Status :: 4 - Beta`
- SDK generator behavior tuned for safer regeneration in existing SDK directories (preserve user space where possible, refresh generated segments).
- Request/response naming and schema wrapping behavior improved for decorated list/search/order/pagination combinations.
- Service docs/examples normalized to generic `products` domain for public documentation.

### Fixed

- Protobuf include-path handling for standard Google proto imports in generation flow.
- Duplicate/request-message naming edge cases in proto rendering for combined list decorators.
- Ordering/searching resolver edge cases and validation messaging.
- `ModelService` list/detail queryset customization paths.
- Object-not-found behavior mapped to `NOT_FOUND` semantics for detail retrieval flow.
- Multiple runtime/data encoding edge cases discovered during smoke testing in external Django project.

### Notes

- This is a beta release. Some APIs may still evolve before `1.0.0`.
- Recommended to pin exact beta version in production-like environments.
