import dataclasses
from typing import Type

from pydantic import BaseModel


@dataclasses.dataclass
class MethodParameter:
    method_name: str
    request_schema: Type[BaseModel] | None = None
    response_schema: Type[BaseModel] | None = None
    description: str | None = None

    def dict(self) -> dict:
        return dataclasses.asdict(self)


__all__ = ["MethodParameter"]
