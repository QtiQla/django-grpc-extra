# Authentication

This section describes how to plug authentication into gRPC server runtime.

## Auth Backend Contract

Configure backend in settings:

```python
GRPC_EXTRA = {
    "AUTH_BACKEND": "path.to.auth.GrpcBearerAuth",
}
```

Supported backend value types:

- callable
- class (instantiated without constructor arguments)
- import path string

Runtime call signature:

```python
def auth_backend(context, method: str, request=None):
    ...
```

Return semantics:

- `False` or `None` -> request aborted with `UNAUTHENTICATED`
- any truthy value -> request allowed

## `GrpcAuthBase`

Minimal custom backend:

```python
from grpc_extra.auth import GrpcAuthBase


class AllowHealthOnly(GrpcAuthBase):
    PUBLIC = {
        "/grpc.health.v1.Health/Check",
        "/grpc.health.v1.Health/Watch",
    }

    def authenticate(self, context, method: str, request=None):
        if method in self.PUBLIC:
            return True
        return False
```

## `GrpcBearerAuthBase`

Helper base for bearer-like token auth from metadata.

Defaults:

- `header = "Authorization"`
- `scheme = "Bearer"`

Matching is case-insensitive for gRPC metadata/header compatibility.

### Normal bearer mode

```python
from grpc_extra.auth import GrpcBearerAuthBase


class GrpcBearerAuth(GrpcBearerAuthBase):
    def authenticate(self, context, token: str, method: str, request=None):
        # validate token
        user = get_user_from_token(token)
        if user is None:
            return None
        setattr(context, "user", user)
        return user
```

### Raw token mode

If `scheme = ""`, full header value is treated as token.

```python
class RawTokenAuth(GrpcBearerAuthBase):
    scheme = ""

    def authenticate(self, context, token: str, method: str, request=None):
        user = validate_raw_token(token)
        if not user:
            return None
        context.user = user
        return user
```

## OIDC/JWT Example

```python
from grpc_extra.auth import GrpcBearerAuthBase


class OidcGrpcAuth(GrpcBearerAuthBase):
    header = "Authorization"
    scheme = "Bearer"

    PUBLIC_METHODS = {
        "/grpc.health.v1.Health/Check",
        "/grpc.health.v1.Health/Watch",
    }

    def __call__(self, context, method: str, request=None):
        if method in self.PUBLIC_METHODS:
            return True
        return super().__call__(context, method, request)

    def authenticate(self, context, token: str, method: str, request=None):
        client = OidcClient()
        try:
            claims = client.validate_access_token(token)
            profile = client.resolve_profile(claims, token)
            identity = client.resolve_identity(profile, claims)
        except OidcAuthError:
            return None

        setattr(context, "user", identity)
        return identity
```

## Common pitfalls

### 1) Method never reaches `authenticate(...)`

Usually token extraction failed:

- missing header
- wrong scheme prefix
- metadata key mismatch in client tool

Add debug log in `__call__` or in `_extract_token` path.

### 2) TLS certificate errors when validating token/JWKS

If IdP uses internal/self-signed CA, configure CA for all HTTP/JWKS clients.

### 3) Health endpoint requires token

Whitelist health methods explicitly (see examples above).

## Recommended pattern

- Keep backend thin (extract + validate + attach identity).
- Put provider-specific HTTP/JWKS logic into dedicated client class.
- Attach resolved user/principal to `context.user` for permission checks.
