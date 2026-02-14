from __future__ import annotations

from typing import Any, TypedDict, cast

from pydantic import BaseModel, create_model

from grpc_extra.decorators import (
    grpc_method,
    grpc_ordering,
    grpc_pagination,
    grpc_searching,
)
from grpc_extra.ordering import resolve_ordering_class
from grpc_extra.pagination import get_default_pagination_class, resolve_pagination_class
from grpc_extra.searching import resolve_searching_class

from .data_helper import DefaultModelDataHelper, ModelDataHelper
from .schemas import AllowedEndpoints, ModelServiceConfig


class EndpointMeta(TypedDict):
    handler_name: str
    rpc_name: str
    request_factory: str
    response_attr: str | None
    response_factory: str | None
    server_streaming: bool
    impl: str
    pagination_supported: bool


class ModelServiceBuilder:
    """Builds CRUD grpc methods on top of a service class from config."""

    ENDPOINT_META: dict[AllowedEndpoints, EndpointMeta] = {
        AllowedEndpoints.STREAM_LIST: {
            "handler_name": "stream_list",
            "rpc_name": "StreamList",
            "request_factory": "_list_request_schema",
            "response_attr": "list_schema",
            "response_factory": None,
            "server_streaming": True,
            "impl": "_stream_list_impl",
            "pagination_supported": False,
        },
        AllowedEndpoints.LIST: {
            "handler_name": "list",
            "rpc_name": "List",
            "request_factory": "_list_request_schema",
            "response_attr": "list_schema",
            "response_factory": None,
            "server_streaming": False,
            "impl": "_list_impl",
            "pagination_supported": True,
        },
        AllowedEndpoints.DETAIL: {
            "handler_name": "detail",
            "rpc_name": "Detail",
            "request_factory": "_lookup_request_schema",
            "response_attr": "detail_schema",
            "response_factory": None,
            "server_streaming": False,
            "impl": "_detail_impl",
            "pagination_supported": False,
        },
        AllowedEndpoints.CREATE: {
            "handler_name": "create",
            "rpc_name": "Create",
            "request_factory": "_create_request_schema",
            "response_attr": "detail_schema",
            "response_factory": None,
            "server_streaming": False,
            "impl": "_create_impl",
            "pagination_supported": False,
        },
        AllowedEndpoints.UPDATE: {
            "handler_name": "update",
            "rpc_name": "Update",
            "request_factory": "_update_request_schema",
            "response_attr": "detail_schema",
            "response_factory": None,
            "server_streaming": False,
            "impl": "_update_impl",
            "pagination_supported": False,
        },
        AllowedEndpoints.PATCH: {
            "handler_name": "patch",
            "rpc_name": "Patch",
            "request_factory": "_patch_request_schema",
            "response_attr": "detail_schema",
            "response_factory": None,
            "server_streaming": False,
            "impl": "_patch_impl",
            "pagination_supported": False,
        },
        AllowedEndpoints.DELETE: {
            "handler_name": "delete",
            "rpc_name": "Delete",
            "request_factory": "_lookup_request_schema",
            "response_attr": None,
            "response_factory": None,
            "server_streaming": False,
            "impl": "_delete_impl",
            "pagination_supported": False,
        },
    }

    def __init__(
        self, service_cls: type["ModelService"], config: ModelServiceConfig
    ) -> None:
        self.service_cls = service_cls
        self.config = config
        self.service_name = service_cls.__name__

    def build(self) -> None:
        for endpoint in self.config.allowed_endpoints:
            self._build_endpoint(endpoint)

    def _build_endpoint(self, endpoint: AllowedEndpoints) -> None:
        meta = self.ENDPOINT_META[endpoint]
        handler_name = meta["handler_name"]
        if handler_name in self.service_cls.__dict__:
            return

        request_schema = cast(Any, getattr(self, meta["request_factory"]))()
        if meta["response_factory"] is not None:
            response_schema = cast(Any, getattr(self, meta["response_factory"]))()
        else:
            response_schema = (
                None
                if meta["response_attr"] is None
                else getattr(self.config, meta["response_attr"])
            )
        impl_name = meta["impl"]

        def handler(self, request, context, *, _impl_name=impl_name):
            impl = getattr(self, _impl_name)
            return impl(request, context)

        handler.__name__ = handler_name
        if self._supports_list_extensions(endpoint):
            searching_class = self._resolve_list_searching_class()
            if searching_class is not None:
                handler = grpc_searching(
                    searching_class,
                    search_fields=list(self.config.list_search_fields),
                )(handler)
            ordering_class = self._resolve_list_ordering_class()
            if ordering_class is not None:
                handler = grpc_ordering(
                    ordering_class,
                    ordering_fields=self.config.list_ordering_fields,
                )(handler)
        if meta["pagination_supported"]:
            pagination_class = self._resolve_list_pagination_class()
            if pagination_class is not None:
                handler = grpc_pagination(pagination_class)(handler)
            else:
                response_schema = self._list_response_schema()
                impl_name = "_list_unpaginated_impl"

                def handler(self, request, context, *, _impl_name=impl_name):
                    impl = getattr(self, _impl_name)
                    return impl(request, context)

                handler.__name__ = handler_name
        wrapped = grpc_method(
            name=meta["rpc_name"],
            request_schema=request_schema,
            response_schema=response_schema,
            server_streaming=meta["server_streaming"],
        )(handler)
        setattr(self.service_cls, handler_name, wrapped)

    def _list_request_schema(self) -> type[BaseModel] | None:
        return self.config.list_filter

    def _list_response_schema(self) -> type[BaseModel]:
        assert self.config.list_schema is not None
        list_schema = self.config.list_schema
        return create_model(
            f"{self.service_name}ListSchema",
            items=(list[list_schema], ...),  # type: ignore[valid-type]
        )

    def _lookup_request_schema(self) -> type[BaseModel]:
        lookup_type = self._lookup_type()
        field_definitions: dict[str, tuple[type, Any]] = {
            self.config.lookup_field: (lookup_type, ...),
        }
        return cast(
            type[BaseModel],
            create_model(
                f"{self.service_name}LookupSchema",
                **field_definitions,  # type: ignore[call-overload]
            ),
        )

    def _create_request_schema(self) -> type[BaseModel]:
        assert self.config.create_schema is not None
        return self.config.create_schema

    def _update_request_schema(self) -> type[BaseModel]:
        assert self.config.update_schema is not None
        lookup_type = self._lookup_type()
        field_definitions: dict[
            str, tuple[type[Any], Any] | tuple[type[BaseModel], Any]
        ] = {
            self.config.lookup_field: (lookup_type, ...),
            "payload": (self.config.update_schema, ...),
        }
        return cast(
            type[BaseModel],
            create_model(
                f"{self.service_name}UpdateSchema",
                **field_definitions,  # type: ignore[call-overload]
            ),
        )

    def _patch_request_schema(self) -> type[BaseModel]:
        assert self.config.patch_schema is not None
        lookup_type = self._lookup_type()
        field_definitions: dict[
            str, tuple[type[Any], Any] | tuple[type[BaseModel], Any]
        ] = {
            self.config.lookup_field: (lookup_type, ...),
            "payload": (self.config.patch_schema, ...),
        }
        return cast(
            type[BaseModel],
            create_model(
                f"{self.service_name}PatchSchema",
                **field_definitions,  # type: ignore[call-overload]
            ),
        )

    def _lookup_type(self) -> type:
        model_field = self.config.model._meta.get_field(self.config.lookup_field)
        python_type = getattr(model_field, "python_type", None)
        if isinstance(python_type, type):
            return python_type
        return int

    def _resolve_list_pagination_class(self):
        value = self.config.list_pagination_class
        if value is None:
            return None
        if value == "default":
            return get_default_pagination_class()
        return resolve_pagination_class(value)

    def _resolve_list_ordering_class(self):
        return resolve_ordering_class(self.config.list_ordering_class)

    def _resolve_list_searching_class(self):
        return resolve_searching_class(self.config.list_searching_class)

    def _supports_list_extensions(self, endpoint: AllowedEndpoints) -> bool:
        return endpoint in {AllowedEndpoints.LIST, AllowedEndpoints.STREAM_LIST}


class ModelService:
    """Base class that auto-builds CRUD grpc methods from `config`."""

    config: ModelServiceConfig
    data_helper_class: type[ModelDataHelper] = DefaultModelDataHelper

    def __init_subclass__(cls, **kwargs):
        super().__init_subclass__(**kwargs)
        if cls is ModelService:
            return
        config = getattr(cls, "config", None)
        if config is None:
            return
        if isinstance(config, dict):
            config = ModelServiceConfig(**config)
        elif not isinstance(config, ModelServiceConfig):
            raise TypeError("ModelService.config must be ModelServiceConfig or dict.")
        cls.config = config
        if not issubclass(cls.data_helper_class, ModelDataHelper):
            raise TypeError(
                "ModelService.data_helper_class must inherit ModelDataHelper."
            )
        ModelServiceBuilder(cls, config).build()

    @property
    def data_helper(self) -> ModelDataHelper:
        return self.data_helper_class(self.config)

    def _list_impl(self, request, context):
        return self.data_helper.list_objects(request)

    def _list_unpaginated_impl(self, request, context):
        return {"items": list(self.data_helper.list_objects(request))}

    def _stream_list_impl(self, request, context):
        return self.data_helper.list_objects(request)

    def _detail_impl(self, request, context):
        return self.data_helper.get_object(request)

    def _create_impl(self, request, context):
        return self.data_helper.create_object(request)

    def _update_impl(self, request, context):
        return self.data_helper.update_object(request)

    def _patch_impl(self, request, context):
        return self.data_helper.patch_object(request)

    def _delete_impl(self, request, context):
        return self.data_helper.delete_object(request)
