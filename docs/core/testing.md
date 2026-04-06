# Testing

`grpc_extra` includes an in-process testing helper for service integration tests.

The testing client is intentionally small:

- it supports `unary-unary` RPC methods;
- it runs in-process without starting a real gRPC server;
- it uses the existing runtime adapter, so request decoding, permissions,
  pagination, searching, ordering, exception mapping, and response encoding are
  exercised in tests.

## Public API

Available helpers:

- `GrpcTestClient`
- `GrpcTestResponse`
- `TestServicerContext`
- `make_pb2_module`

Import them directly from `grpc_extra`:

```python
from grpc_extra import GrpcTestClient, TestServicerContext, make_pb2_module
```

## Fake pb2 Module

`make_pb2_module` builds a minimal in-memory pb2 stub so tests do not require
pre-generated protobuf artifacts.

```python
pb2 = make_pb2_module(
    "UserService",
    {
        "List": "ListUsersResponse",
        "Retrieve": "UserResponse",
    },
)
```

The first argument is the gRPC service name as it appears in the `.proto` file.
The second argument maps each gRPC method name to its response message name.

Pass the result as `pb2_module` when calling `GrpcTestClient.call`:

```python
response = GrpcTestClient().call(UserService, "List", {"limit": 10}, pb2_module=pb2)
```

This is the recommended approach for integration tests that hit a real database —
it keeps your test suite independent of the proto compilation step.

## Basic Usage

```python
from pydantic import BaseModel

from grpc_extra import GrpcTestClient, grpc_method, grpc_service


class EchoRequest(BaseModel):
    value: int


class EchoResponse(BaseModel):
    value: int


@grpc_service(app_label="products", package="products")
class EchoService:
    @grpc_method(request_schema=EchoRequest, response_schema=EchoResponse)
    def echo(self, request, context):
        return {"value": request.value}


client = GrpcTestClient()
response = client.call(EchoService, "Echo", {"value": 7}, pb2_module=pb2_module)

assert response.ok is True
assert response.data == {"value": 7}
assert response.code.name == "OK"
```

## What `call(...)` Accepts

```python
response = client.call(
    service=EchoService,
    method="Echo",
    request={"value": 7},
    metadata=[("authorization", "Bearer token")],
    context=None,
    pb2_module=pb2_module,
    auth_backend=None,
)
```

Arguments:

- `service`
  - decorated service class
  - service instance
  - `ServiceDefinition`
- `method`
  - gRPC method name (`"Echo"`)
  - or Python handler name (`"echo"`)
- `request`
  - `dict`
  - Pydantic model
  - protobuf request object
- `metadata`
  - request metadata for `context.invocation_metadata()`
- `context`
  - custom `TestServicerContext`
- `pb2_module`
  - optional explicit pb2 module override
- `auth_backend`
  - optional backend for this call only

## Response Object

`GrpcTestResponse` gives you both transport information and decoded payload.

```python
response = client.call(...)

response.ok
response.code
response.details
response.message
response.data
response.initial_metadata
response.trailing_metadata
response.json()
response.assert_ok()
```

Notes:

- `response.message` is the raw protobuf response object.
- `response.data` and `response.json()` return a plain Python representation.

## Metadata And Custom Context

Use request metadata:

```python
response = client.call(
    EchoService,
    "Echo",
    {"value": 1},
    metadata=[("x-trace-id", "123")],
    pb2_module=pb2_module,
)
```

Use a prebuilt context when you want to attach custom state:

```python
context = TestServicerContext(user=my_user, tenant_id="acme")

response = client.call(
    EchoService,
    "Echo",
    {"value": 1},
    context=context,
    pb2_module=pb2_module,
)
```

## Testing Auth

`GrpcTestClient` can run an auth backend before the method call.

```python
def auth_backend(context, method, request):
    context.user = user
    return user


client = GrpcTestClient(auth_backend=auth_backend)
response = client.call(SecureService, "List", {"limit": 10}, pb2_module=pb2_module)
```

If the backend returns `None` or `False`, the client returns:

- `code == grpc.StatusCode.UNAUTHENTICATED`
- `details == "Unauthorized"`

## Testing ModelService

This helper is especially useful for `ModelService`, because you can exercise:

- request validation;
- generated CRUD endpoints;
- searching;
- ordering;
- pagination;
- permissions;
- generated choice endpoints.

```python
response = client.call(
    ProductService,
    "List",
    {"limit": 10, "offset": 0},
    pb2_module=pb2_module,
)

assert response.ok
assert response.data["count"] >= 0
assert "results" in response.data
```

## Limitations

Current MVP limitations:

- only `unary-unary` methods are supported;
- it does not start a real gRPC server;
- interceptors are not executed automatically;
- reflection/health endpoints are outside this helper's scope.

For `stream-unary`, `unary-stream`, or `stream-stream`, use direct adapter tests
or a real server/channel setup.
