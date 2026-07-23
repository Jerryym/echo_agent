"""
MCP Client 手动验证脚本

验证项：
1. stdio MCP Server 连接
2. http (streamable HTTP) MCP Server 连接
3. get_tools() 返回内容
4. register_tools() 注册到 ToolRegistry
5. ToolExecutor.aexecute() 调用 MCP 工具

运行：
  uv run python tests/test_mcp_client.py

http 默认连接：
  http://localhost:8000/mcp
"""

from __future__ import annotations

import asyncio
import uuid

from echo_agent.core.mcp import MCPClient, MCPConnectionConfig
from echo_agent.core.tool import (
    ToolCall,
    ToolDefinition,
    ToolExecutor,
    ToolRegistry,
    ToolType,
)

MCP_HTTP_URL = "http://localhost:8000/mcp"

# 优先用于执行验证的工具及示例参数（存在则优先选用）
PREFERRED_EXECUTE_CASES: dict[str, dict] = {
    "echo": {"message": "hello from echo-agent"},
    "add": {"a": 1, "b": 2},
}


def _print_tools(tools) -> None:
    print(f"tools count: {len(tools)}")
    print(f"tools type: {type(tools).__name__}")
    for i, tool in enumerate(tools, start=1):
        name = getattr(tool, "name", None)
        description = getattr(tool, "description", None)
        args_schema = getattr(tool, "args_schema", None)
        print(f"\n[{i}] name={name}")
        print(f"    type={type(tool).__name__}")
        print(f"    description={description}")
        if args_schema is not None:
            print(f"    args_schema={args_schema}")
        if hasattr(tool, "tool_call_schema"):
            print(f"    tool_call_schema={tool.tool_call_schema}")


def _print_definitions(definitions: list[ToolDefinition]) -> None:
    print(f"registered count: {len(definitions)}")
    for i, definition in enumerate(definitions, start=1):
        print(f"\n[{i}] name={definition.name}")
        print(f"    type={definition.type}")
        print(f"    description={definition.description}")
        print(f"    parameters={definition.parameters}")


def _assert_tools(tools) -> None:
    assert tools is not None, "get_tools() returned None"
    assert isinstance(tools, list), f"expected list, got {type(tools)}"
    assert len(tools) > 0, "get_tools() returned empty list"
    for tool in tools:
        name = getattr(tool, "name", None)
        assert name, f"tool missing name: {tool!r}"
        assert hasattr(tool, "description"), f"tool missing description: {name}"


def _assert_registered(
    definitions: list[ToolDefinition],
    registry: ToolRegistry,
    *,
    server_name: str,
) -> None:
    assert definitions, "register_tools() returned empty definitions"
    assert len(definitions) == len(registry.list_definitions())
    for definition in definitions:
        assert definition.type == ToolType.MCP, (
            f"expected ToolType.MCP, got {definition.type} for {definition.name}"
        )
        assert registry.get(definition.name).type == ToolType.MCP
        assert registry.get_handler(definition.name) is not None
        assert definition.meta_data.get("mcp_server") == server_name
        original = definition.meta_data.get("original_name")
        assert original, f"missing original_name for {definition.name}"
        assert definition.name == f"{server_name}_{original}", (
            f"expected prefixed name {server_name}_{original}, got {definition.name}"
        )


def _pick_execute_case(
    definitions: list[ToolDefinition],
) -> tuple[ToolDefinition, dict]:
    # tool_name_prefix 后 definition.name 为 {server}_{original}，按 original_name 匹配
    by_original = {
        (d.meta_data.get("original_name") or d.name): d for d in definitions
    }
    for name, args in PREFERRED_EXECUTE_CASES.items():
        if name in by_original:
            return by_original[name], args

    definition = definitions[0]
    return definition, {}


async def _execute_one(registry: ToolRegistry, definitions: list[ToolDefinition]) -> None:
    definition, args = _pick_execute_case(definitions)
    tool_call = ToolCall(
        name=definition.name,
        args=args,
        tool_call_id=f"mcp-test-{uuid.uuid4().hex[:8]}",
    )
    print(f"\nexecuting tool: {tool_call.name}")
    print(f"args: {tool_call.args}")

    executor = ToolExecutor(registry)
    result = await executor.aexecute(tool_call)

    print(f"success: {result.success}")
    print(f"result: {result.result}")
    if not result.success:
        print(f"error: {result.error}")

    assert result.success, f"execute failed: {result.error}"
    assert result.tool_call_id == tool_call.tool_call_id


async def _run_transport_case(
    *,
    title: str,
    config: MCPConnectionConfig,
) -> None:
    print("\n==============================")
    print(f"TEST: {title}")
    print("==============================\n")
    if config.type == "http":
        print(f"url: {config.url}")

    # 与 AgentConfig.mcp_servers 同形态：list[MCPConnectionConfig]
    mcp_servers = [config]
    client = MCPClient(mcp_servers)

    # 1) get_tools
    tools = await client.get_tools()
    print("--- get_tools ---")
    _print_tools(tools)
    _assert_tools(tools)
    print("PASS: get_tools")

    # 2) register_tools
    registry = ToolRegistry()
    definitions = await client.register_tools(registry)
    print("\n--- register_tools ---")
    _print_definitions(definitions)
    _assert_registered(definitions, registry, server_name=config.name)
    print("PASS: register_tools")

    # 3) aexecute
    print("\n--- aexecute ---")
    await _execute_one(registry, definitions)
    print("PASS: aexecute")

    print(f"\nPASS: {title}")


async def test_stdio() -> None:
    await _run_transport_case(
        title="stdio MCP Server (get_tools + register + aexecute)",
        config=MCPConnectionConfig(
            name="everything",
            type="stdio",
            command="npx",
            args=["-y", "@modelcontextprotocol/server-everything"],
        ),
    )


async def test_http() -> None:
    await _run_transport_case(
        title="http MCP Server (get_tools + register + aexecute)",
        config=MCPConnectionConfig(
            name="remote",
            type="http",
            url=MCP_HTTP_URL,
        ),
    )


async def main() -> None:
    # 固定同时跑 stdio + http，无需选择
    await test_stdio()
    await test_http()


if __name__ == "__main__":
    asyncio.run(main())
