import json
from typing import Any, Literal

from pydantic import BaseModel, Field, model_validator


class MCPConnectionConfig(BaseModel):
    """
    MCP Client 连接配置

    参数：
        name: MCP 服务器名称
        type: MCP Client 连接类型(stdio: 标准输入输出, http: 即streamable http)
        command: MCP Server 启动命令(仅在 type 为 stdio 时有效)
        args: MCP Server 启动参数(仅在 type 为 stdio 时有效)
        url: MCP Server URL(仅在 type 为 http 时有效, 示例: http://localhost:8080/mcp)
        headers: HTTP 请求头(仅在 type 为 http 时有效)
        auth: HTTP 身份认证(仅在 type 为 http 时有效)
    """
    name: str = Field(default="")
    type: Literal["stdio", "http"] = Field(default="stdio")
    command: str | None = None
    args: list[str] | None = None
    url: str | None = None
    headers: dict[str, str] | None = None
    auth: Any | None = None

    def to_adapter_config(self) -> dict[str, Any]:
        """转换为 MCP 适配器配置"""
        if self.type == "stdio":
            config = {
                "transport": "stdio",
                "command": self.command,
                "args": self.args,
            }
        elif self.type == "http":
            config = {
                "transport": "http",
                "url": self.url,
            }
            if self.headers:
                config["headers"] = self.headers
            if self.auth:
                config["auth"] = self.auth
        else:
            raise ValueError(f"Unsupported MCP type: {self.type}")
        return config

    @model_validator(mode="after")
    def validate_config(self):
        if self.type == "stdio":
            if not self.command:
                raise ValueError("stdio type requires command")
        if self.type == "http":
            if not self.url:
                raise ValueError("http type requires url")
        return self


class MCPConfigLoader:
    """
    MCP 配置加载器
    """
    def load(self, config: str | dict) -> list[MCPConnectionConfig]:
        """加载 MCP 配置"""
        if isinstance(config, str):
            config = json.loads(config)

        if not isinstance(config, dict):
            raise ValueError("Invalid MCP config")

        servers = config.get("mcpServers", {})
        return [
            MCPConnectionConfig(
                name=name,
                **value
            )
            for name, value in servers.items()
        ]
