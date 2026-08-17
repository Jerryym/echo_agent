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
    通用HTTP响应

    Attributes:
        code: 业务状态码（200-成功）
        msg: 响应消息
        data: 响应数据
    """
    code: int
    msg: str = Field(default="")
    data: T | None = None
