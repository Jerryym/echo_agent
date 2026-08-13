from pydantic import BaseModel, Field


class HttpRequest(BaseModel):
    """
    通用HTTP请求配置

    Attributes:
        url: 请求URL
        headers: 请求头
    """
    url: str | None = None
    headers: dict[str, str] | None = Field(default_factory=dict)
