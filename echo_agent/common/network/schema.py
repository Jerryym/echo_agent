from pydantic import BaseModel, Field

from typing import Generic, TypeVar

T = TypeVar("T")

class HttpRequest(BaseModel):
    """
    通用HTTP请求配置

    Attributes:
        url: 请求URL
        headers: 请求头
    """
    url: str | None = None
    headers: dict[str, str] | None = Field(default_factory=dict)


class HttpResponse(BaseModel, Generic[T]):
    """
    Standard API response.

    Args:
        code: Business status code.
        msg: Response message.
        data: Response payload.
    """
    code: int
    msg: str = ""
    data: T | None = None
