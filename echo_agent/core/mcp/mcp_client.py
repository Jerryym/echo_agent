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
        self._client = MultiServerMCPClient(
            servers,
            tool_name_prefix=True, # 工具名前缀为 Server 名称
            )
        self._mcp_tools = None

    @property
    def mcp_server_list(self) -> list[MCPConnectionConfig]:
        """获取 MCP 服务器列表"""
        return self._mcp_server_configs

    async def get_tools(self):
        """获取 MCP 工具"""
        if self._mcp_tools is None:
            self._mcp_tools = await self._client.get_tools()
        return self._mcp_tools

    async def register_tools(self, registry: ToolRegistry) -> list[ToolDefinition]:
        """注册 MCP 工具"""
        tool_definitions: list[ToolDefinition] = []
        tools = []
        for config in self._mcp_server_configs:
            # tool.name 已是 f"{config.name}_{original}"（tool_name_prefix=True）
            server_tools = await self._client.get_tools(server_name=config.name)
            tools.extend(server_tools)
            for tool in server_tools:
                original_name = tool.name.removeprefix(f"{config.name}_")
                definition = to_tool_definition(tool, ToolType.MCP)
                definition = definition.model_copy(
                    update={
                        "meta_data": {
                            **definition.meta_data,
                            "mcp_server": config.name,
                            "original_name": original_name,
                        },
                    }
                )
                registry.register(definition, tool)
                tool_definitions.append(definition)
        self._mcp_tools = tools
        return tool_definitions
