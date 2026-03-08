# FAQ

## Why do I get `UNAUTHENTICATED` before my `authenticate(...)` method runs?

Most often token extraction failed before custom auth logic:

- wrong metadata key
- wrong scheme prefix
- empty token value

What to do:

1. log incoming metadata keys in auth backend
2. verify `GrpcBearerAuthBase.header` and `scheme`
3. confirm client sends metadata for the same method call

## How do I allow health checks without authentication?

Whitelist health RPC methods in backend:

- `/grpc.health.v1.Health/Check`
- `/grpc.health.v1.Health/Watch`

Return `True` for those methods before token validation.

## Why does client show `invalid wire type` / parsing error?

Usually proto contract mismatch between server and client cache.

What to do:

1. regenerate proto/pb2
2. restart server
3. recreate gRPC connection in client tool
4. verify reflection is enabled if client relies on reflection

## Why does search not change results?

`grpc_searching` requires explicit fields.

Use:

```python
@grpc_searching(search_fields=["name", "sku"])
```

Without fields, decorator raises error or search does nothing depending on configuration/class contract.

## Why does ordering fail with invalid field errors?

Ordering validates fields against configured/available fields.

What to do:

1. pass explicit `ordering_fields`
2. ensure response items expose those fields (`dict` keys/object attrs)
3. for queryset ordering, ensure field exists in model/annotation

## Why do I get `Failed to encode response`?

Response payload doesn't match `response_schema` / proto shape.

Typical causes:

- returned object has missing fields
- type mismatch (`Decimal`, date/time, nested objects)
- wrong top-level shape for unary response

What to do:

1. compare method return payload with schema
2. verify generated proto message fields
3. simplify response to minimal working payload, then add fields back

## Can unary RPC return `list[Schema]`?

Yes. Use:

```python
@grpc_method(response_schema=list[ItemSchema])
```

Runtime wraps returned collection into internal `items` field.

## Do I need to wrap pagination response schema manually?

No. With `@grpc_pagination` or `@grpc_pagination()` you pass item schema only.

Pagination decorator augments request/response schemas automatically.

## Why does pre-commit pass manually but fail on commit?

Usually different environment/path context (e.g. missing activated virtualenv in commit hook shell).

What to do:

1. ensure tools (`ruff`, `mypy`, etc.) are installed in environment used by hooks
2. run `pre-commit run --all-files` in the same shell context used for git commit
3. avoid relying on shell-local state not available in hook subprocess

## What does `ModuleNotFoundError: <name>_pb2` mean?

Generated pb2 files are missing or generated into wrong include/output path.

Fix:

- run `generate_proto` again
- verify app root and proto import/include paths

## Why reflection doesn't show my service?

Possible causes:

- reflection disabled
- service not discovered/registered
- stale client cache

Check:

1. run with `--reflection`
2. inspect server startup logs for discovered/registered services
3. recreate client connection
