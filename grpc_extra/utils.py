def is_upper_camel_case(s: str) -> bool:
    return s != "" and s[0].isupper() and not any(c in s for c in "_-")


def to_upper_camel_case(value: str) -> str:
    normalized = value.replace("-", "_")
    if "_" in normalized:
        parts = [part for part in normalized.split("_") if part]
        return "".join(part[:1].upper() + part[1:] for part in parts)
    return normalized[:1].upper() + normalized[1:]


def normalize_proto_path(proto_path: str) -> str:
    normalized = proto_path.replace("\\", "/").lstrip("/")
    if not normalized.endswith(".proto"):
        normalized = f"{normalized}.proto"
    return normalized


def proto_path_to_module(app_label: str, proto_path: str) -> str:
    normalized = normalize_proto_path(proto_path)
    without_ext = normalized[:-6]
    module_rel = without_ext.replace("/", ".")
    return f"{app_label}.{module_rel}"


def pb2_module_path(app_label: str, proto_path: str) -> str:
    return f"{proto_path_to_module(app_label, proto_path)}_pb2"


def pb2_grpc_module_path(app_label: str, proto_path: str) -> str:
    return f"{proto_path_to_module(app_label, proto_path)}_pb2_grpc"
