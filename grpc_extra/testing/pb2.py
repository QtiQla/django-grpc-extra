from __future__ import annotations

from types import SimpleNamespace


class _FakePb2Message:
    def __init__(self, **kwargs):
        self.payload = kwargs


def make_pb2_module(service_name: str, methods: dict[str, str]) -> SimpleNamespace:
    """Build a minimal fake pb2 module for use in tests.

    Avoids the need to pre-generate protobuf artifacts when testing service
    logic in isolation.

    Args:
        service_name: The gRPC service name as it appears in the .proto file.
        methods: Mapping of gRPC method name → response message name,
                 e.g. ``{"List": "ListUsersResponse", "Retrieve": "UserResponse"}``.

    Returns:
        A :class:`types.SimpleNamespace` that mimics enough of a real pb2
        module for :class:`~grpc_extra.GrpcTestClient` to work — specifically
        ``DESCRIPTOR.services_by_name`` and the response message classes.

    Example::

        pb2 = make_pb2_module("UserService", {"List": "ListUsersResponse"})
        response = GrpcTestClient().call(UserService, "List", {...}, pb2_module=pb2)
    """
    method_map = {
        name: SimpleNamespace(output_type=SimpleNamespace(name=response_name))
        for name, response_name in methods.items()
    }
    attrs: dict = {
        "__name__": "fake_pb2",
        "DESCRIPTOR": SimpleNamespace(
            services_by_name={
                service_name: SimpleNamespace(methods_by_name=method_map),
            }
        ),
    }
    for response_name in methods.values():
        attrs[response_name] = type(response_name, (_FakePb2Message,), {})
    return SimpleNamespace(**attrs)
