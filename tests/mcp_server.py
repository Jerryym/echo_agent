from __future__ import annotations

from pathlib import Path
import sys

# 保证能 import tools.*
sys.path.insert(0, str(Path(__file__).resolve().parent))

from fastmcp import FastMCP
from tools.business_tools import BUSINESS_TOOLS
from tools.it_operations_tool import IT_OPERATIONS_TOOLS

mcp = FastMCP("EchoAgentTools")


def _register(tool_obj) -> None:
    # LangChain StructuredTool → 取底层函数
    if hasattr(tool_obj, "func"):
        fn = tool_obj.func
        mcp.tool(name=tool_obj.name, description=tool_obj.description or "")(fn)
    else:
        mcp.tool()(tool_obj)


for t in (*BUSINESS_TOOLS, *IT_OPERATIONS_TOOLS):
    _register(t)


if __name__ == "__main__":
    mcp.run(transport="streamable-http")
