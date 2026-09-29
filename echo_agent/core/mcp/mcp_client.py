from typing import Any

from langchain.mcp import MCPAdapter
from langchain_core.tools import BaseTool

from ...common import get_logger
from ..tool import ToolDefinition, ToolRegistry, ToolType
from ..tool.utils import to_tool_definition
from .schema import MCPConnectionConfig

logger = get_logger("mcp")


class MCPClient:
    """
    MCP 客户端
    """
    def __init__(self, tool_registry: ToolRegistry, mcp_server_configs: list[MCPConnectionConfig]):
        self._tool_registry = tool_registry
        self._mcp_server_configs: list[MCPConnectionConfig] = mcp_server_configs
        self._mcp_tools: list[BaseTool] = None
        self._mcp_tool_names: list[str] = None
        self._is_closed: bool = False
        self._mcp_config: dict[str, Any] = self._build_mcp_config(mcp_server_configs)

    @property
    def mcp_server_list(self) -> list[MCPConnectionConfig]:
        """获取 MCP 服务器列表"""
        return self._mcp_server_configs

    async def get_tools(self):
        """获取 MCP 工具"""
        return await self._ensure_tools()

    async def register_tools(self) -> list[ToolDefinition]:
        """注册 MCP 工具"""
        tools = await self._ensure_tools()
        pending: list[tuple[ToolDefinition, Any]] = []
        for tool in tools:
            logger.debug("register_tools | tool=%s", tool)
            server_name, original_name = self._resolve_server_and_original(tool)
            definition = to_tool_definition(tool, ToolType.MCP)
            definition = definition.model_copy(
                update={
                    "name": f"{server_name}_{original_name}",
                    "meta_data": {
                        **definition.meta_data,
                        "mcp_server": server_name,
                        "original_name": original_name,
                    },
                }
            )
            pending.append((definition, tool))

        registered_names: list[str] = []
        tool_definitions: list[ToolDefinition] = []
        try:
            for definition, tool in pending:
                self._tool_registry.register(definition, tool)
                registered_names.append(definition.name)
                tool_definitions.append(definition)
        except Exception:
            for name in registered_names:
                self._tool_registry.unregister(name)
            raise

        self._mcp_tool_names = registered_names
        return tool_definitions

    async def aclose(self) -> None:
        """卸载 MCP 客户端"""
        if self._is_closed:
            return
        for name in self._mcp_tool_names or []:
            self._tool_registry.unregister(name)
        self._mcp_tool_names = []
        self._mcp_tools = None
        self._is_closed = True

    async def _ensure_tools(self) -> list[BaseTool]:
        """发现 MCP 工具（一次 list_tools，结果缓存）"""
        if self._is_closed:
            raise RuntimeError("MCPClient is closed")
        if self._mcp_tools is None:
            async with MCPAdapter(self._mcp_config) as adapter:
                self._mcp_tools = await adapter.list_tools()
        return self._mcp_tools

    def _resolve_server_and_original(self, tool: Any) -> tuple[str, str]:
        """从工具名 / MCP 元数据解析 server 名与原始工具名"""
        tool_name = getattr(tool, "name", "") or ""
        config_names = {config.name for config in self._mcp_server_configs}
        metadata = getattr(tool, "metadata", None) or {}
        mcp_meta = metadata.get("mcp") if isinstance(metadata, dict) else None
        if isinstance(mcp_meta, dict):
            server_meta = mcp_meta.get("server")
            if isinstance(server_meta, dict):
                meta_name = server_meta.get("name")
                if isinstance(meta_name, str) and meta_name in config_names:
                    prefix = f"{meta_name}_"
                    if tool_name.startswith(prefix):
                        return meta_name, tool_name.removeprefix(prefix)

        matched: str | None = None
        for config in self._mcp_server_configs:
            prefix = f"{config.name}_"
            if tool_name.startswith(prefix) and (
                matched is None or len(config.name) > len(matched)
            ):
                matched = config.name
        if matched is not None:
            return matched, tool_name.removeprefix(f"{matched}_")
        # 单服务时 MCPAdapter 不加 {server}_ 前缀
        if len(self._mcp_server_configs) == 1 and tool_name:
            return self._mcp_server_configs[0].name, tool_name
        raise ValueError(f"unable to resolve MCP server for tool: {tool_name!r}")

    def _build_mcp_config(self, servers: list[MCPConnectionConfig]) -> dict[str, Any]:
        """构建MCP配置"""
        names = [server.name for server in servers]
        if len(names) != len(set(names)):
            raise ValueError(f"MCP服务器名称重复: {names}")
        return {
            "mcpServers": {
                server.name: server.to_adapter_config()
                for server in servers
            }
        }
