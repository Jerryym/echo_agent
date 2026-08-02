"""
内置 MCP Server 连接配置。

对应官方 reference servers：
- Fetch：网页抓取（Python，`uvx mcp-server-fetch`）
- Filesystem：受限目录下的文件操作（Node，`@modelcontextprotocol/server-filesystem`）

参见：https://modelcontextprotocol.io/examples#current-reference-servers
"""

from __future__ import annotations

import sys
from pathlib import Path

from .schema import MCPConnectionConfig

FETCH_SERVER_NAME = "fetch"
FILESYSTEM_SERVER_NAME = "filesystem"


def builtin_fetch_config() -> MCPConnectionConfig:
    """
    内置 Fetch MCP Server 配置（stdio / uvx）。
    """
    return MCPConnectionConfig(
        name=FETCH_SERVER_NAME,
        type="stdio",
        command="uvx",
        args=["mcp-server-fetch"],
    )


def builtin_filesystem_config(
    allowed_directories: str | list[str],
) -> MCPConnectionConfig:
    """
    内置 Filesystem MCP Server 配置（stdio / npx）。

    Args:
        allowed_directories: 允许访问的目录（由调用方传入，至少一个）。
    """
    roots = _normalize_directories(allowed_directories)
    package = "@modelcontextprotocol/server-filesystem"

    if sys.platform == "win32":
        # Windows 上 npx 需经 cmd /c 启动，否则易失败
        return MCPConnectionConfig(
            name=FILESYSTEM_SERVER_NAME,
            type="stdio",
            command="cmd",
            args=["/c", "npx", "-y", package, *roots],
        )

    return MCPConnectionConfig(
        name=FILESYSTEM_SERVER_NAME,
        type="stdio",
        command="npx",
        args=["-y", package, *roots],
    )


def builtin_mcp_servers(
    *,
    allowed_directories: str | list[str],
    enable_fetch: bool = True,
    enable_filesystem: bool = True,
) -> list[MCPConnectionConfig]:
    """
    返回 Agent 默认内置的 MCP Server 配置列表。

    Args:
        allowed_directories: Filesystem 允许访问的目录（由调用方传入）。
        enable_fetch: 是否包含 Fetch。
        enable_filesystem: 是否包含 Filesystem。
    """
    servers: list[MCPConnectionConfig] = []
    if enable_fetch:
        servers.append(builtin_fetch_config())
    if enable_filesystem:
        servers.append(builtin_filesystem_config(allowed_directories))
    return servers


def _normalize_directories(
    allowed_directories: str | list[str],
) -> list[str]:
    if isinstance(allowed_directories, str):
        roots = [allowed_directories]
    else:
        roots = list(allowed_directories)

    if not roots:
        raise ValueError("filesystem MCP requires at least one allowed directory")

    return [str(Path(path).expanduser().resolve()) for path in roots]
