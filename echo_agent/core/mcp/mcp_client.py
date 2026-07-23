from langchain_mcp_adapters.client import MultiServerMCPClient

from ..tool import ToolDefinition, ToolRegistry, ToolType
from ..tool.utils import to_tool_definition
from .schema import MCPConnectionConfig


class MCPClient:
    """
    MCP 客户端
    """
    def __init__(self, mcp_server_configs: list[MCPConnectionConfig]):
        servers = {
            config.name: config.to_adapter_config()
            for config in mcp_server_configs
        }

        self._mcp_server_configs = mcp_server_configs
        self._client = MultiServerMCPClient(servers)
        self._tools = None

    @property
    def mcp_server_list(self) -> list[MCPConnectionConfig]:
        """获取 MCP 服务器列表"""
        return self._mcp_server_configs

    async def get_tools(self):
        """获取 MCP 工具"""
        if self._tools is None:
            self._tools = await self._client.get_tools()
        return self._tools

    async def register_tools(self, registry: ToolRegistry) -> list[ToolDefinition]:
        """注册 MCP 工具"""
        tools = await self.get_tools()
        definitions = []
        for tool in tools:
            definition = to_tool_definition(tool, ToolType.MCP)
            registry.register(definition, tool)
            definitions.append(definition)
        return definitions
