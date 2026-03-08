# django-grpc-extra

`django-grpc-extra` helps you build gRPC APIs in Django with a decorator-first workflow.

## What You Get

- Decorators for services and RPC methods
- Proto generation from Pydantic schemas
- Runtime conversion (`pb2 <-> pydantic`) and exception mapping
- Built-in server launcher with autodiscovery, health, reflection, reload
- `ModelService` for CRUD-heavy endpoints

## Current Status

The project is in **Beta**.

## Read This First

1. [Quickstart](quickstart.md)
2. [Core Decorators](core/decorators.md)
3. [Authentication](core/authentication.md)
4. [Permissions](core/permissions.md)

## Compatibility

- Python 3.10+
- Django 3.2+

## Next Steps

- Start with one unary RPC and generate `.proto`
- Enable health/reflection only when needed
- Add auth backend and permissions after basic smoke tests
