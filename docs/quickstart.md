# Quickstart

## 1) Install

```bash
pip install "django-grpc-extra[codegen]"
```

## 2) Add app

```python
INSTALLED_APPS = [
    ...,
    "grpc_extra",
]
```

## 3) Init grpc layout

```bash
python -m django init_grpc --app products
```

## 4) Add service

```python
from pydantic import BaseModel
from grpc_extra import grpc_method, grpc_service


class PingRequest(BaseModel):
    message: str


class PingResponse(BaseModel):
    message: str


@grpc_service(app_label="products", package="products")
class ExampleService:
    @grpc_method(request_schema=PingRequest, response_schema=PingResponse)
    def ping(self, request, context):
        return {"message": f"pong: {request.message}"}
```

## 5) Generate proto/pb2

```bash
python -m django generate_proto --app products
```

## 6) Run server

```bash
python manage.py run_grpcserver --health --reflection
```

## 7) Invoke

Use grpcurl/Postman/BloomRPC and call:

- service: `ExampleService`
- method: `Ping`

Payload example:

```json
{"message": "hello"}
```
