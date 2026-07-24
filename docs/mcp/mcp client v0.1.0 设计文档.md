# MCP Client 模块 v0.1.0 设计文档

## 1. 版本说明


| 项目   | 内容                                                                                                       |
| ---- | -------------------------------------------------------------------------------------------------------- |
| 版本   | v0.1.0                                                                                                   |
| 状态   | 已实现；`tests/test_mcp_client.py`、`tests/test_react_agent_mcp.py`、`tests/test_react_agent_hitl_mcp.py` 手动验证 |
| 依赖   | `langchain-mcp-adapters>=0.3.0`（`MultiServerMCPClient`）、Tool 模块、Pydantic                                 |
| 上一版本 | —（首版）                                                                                                    |


---

## 2. 模块定位

MCP 模块是 echo-agent 的 **MCP Client 接入层**：连接外部 MCP Server，发现其 Tools，并注册进 `ToolRegistry`，供 Strategy / ToolNode 走统一工具链路。

**负责：**

- 解析 MCP Server 连接配置（`MCPConnectionConfig` / `MCPConfigLoader`）
- 封装 `MultiServerMCPClient`（`MCPClient`）
- 拉取 MCP Tools（`get_tools`）
- 转换为 `ToolDefinition(type=MCP)` 并注册到 `ToolRegistry`（`register_tools`）

**不负责：**

- MCP Server 实现（测试用 `tests/mcp_server.py` 为验证夹具，非库能力）
- Tools 执行（由 `ToolExecutor.aexecute` / `ToolNode.arun` 完成）
- Resources / Prompts / Sampling 等非 Tool 能力
- Client 进程级生命周期自动托管（stdio 子进程存活依赖调用方持有 `MCPClient` 引用）

---



## 3. 设计原则



### 3.1 Adapter 薄封装原则

协议与 Transport 交给 `langchain-mcp-adapters`；本模块只做配置适配与 Tool 注册桥接。

```text
MCPConnectionConfig
        ↓ to_adapter_config()
MultiServerMCPClient
        ↓ get_tools()
LangChain BaseTool[]
        ↓ to_tool_definition(..., ToolType.MCP)
ToolRegistry
```



### 3.2 Tool 统一承接原则

MCP Tools 与本地 FUNCTION 工具共用 `ToolDefinition` / `ToolRegistry` / `ToolExecutor` / `ToolNode`。MCP 仅将 `ToolDefinition.type` 标为 `ToolType.MCP`；LLM 侧仍以 OpenAI function schema 暴露。

### 3.3 异步主路径原则

MCP handler 通常仅支持 `ainvoke`。含 MCP 工具时必须走异步轨：


| 层级           | 同步轨                  | 异步轨（MCP）               |
| ------------ | -------------------- | ---------------------- |
| Agent        | `invoke` / `stream`  | `ainvoke` / `astream`  |
| ToolExecutor | `execute` → `invoke` | `aexecute` → `ainvoke` |
| ToolNode     | `run`                | `arun`                 |


禁止在 sync 路径用 `asyncio.run(handler.ainvoke(...))` 冒充兼容。

### 3.4 连接持有原则

`MCPClient` 内部缓存 `get_tools()` 结果；stdio 场景下 Server 为子进程，**调用方须在 Agent 运行期间保持对** `MCPClient` **的引用**，避免 GC 导致连接/子进程回收。

---



## 4. 模块结构

```text
echo_agent/core/mcp/
├── __init__.py       # 导出 MCPClient, MCPConnectionConfig, MCPConfigLoader
├── mcp_client.py     # MCPClient
└── schema.py         # MCPConnectionConfig, MCPConfigLoader
```

公开 API：

```python
from echo_agent.core.mcp import MCPClient, MCPConnectionConfig, MCPConfigLoader
```

---



## 5. Transport 与运行模式

v0.1.0 支持两种连接（对应配置字段 `type`）：


| `type`  | 适配器 transport           | 典型场景                | 关键配置                       |
| ------- | ----------------------- | ------------------- | -------------------------- |
| `stdio` | `stdio`                 | 本机子进程 MCP Server    | `command`, `args`          |
| `http`  | `http`（streamable HTTP） | 远程或本机独立 HTTP Server | `url`；可选 `headers`, `auth` |


```text
# stdio
echo-agent ──stdio──▶ MCP Server Process

# http
echo-agent ──streamable HTTP──▶ MCP Server
```

---



## 6. 配置模型



### 6.1 MCPConnectionConfig


| 字段        | 类型                      | 说明                                      |
| --------- | ----------------------- | --------------------------------------- |
| `name`    | `str`                   | Server 名称（`MultiServerMCPClient` 的 key） |
| `type`    | `"stdio" | "http"`      | 连接类型，默认 `stdio`                         |
| `command` | `str | None`            | stdio 启动命令                              |
| `args`    | `list[str] | None`      | stdio 启动参数                              |
| `url`     | `str | None`            | http 端点，如 `http://localhost:8000/mcp`   |
| `headers` | `dict[str, str] | None` | http 请求头                                |
| `auth`    | `Any | None`            | http 认证对象（透传适配器）                        |


校验（`model_validator`）：

- `stdio` 必须有 `command`
- `http` 必须有 `url`

`to_adapter_config()` 输出适配器字典，例如：

```python
# stdio
{"transport": "stdio", "command": "...", "args": [...]}

# http
{"transport": "http", "url": "...", "headers": {...}, "auth": ...}
```



### 6.2 MCPConfigLoader

从 JSON 字符串或 `dict` 加载多 Server 配置，约定根键为 `mcpServers`：

```json
{
  "mcpServers": {
    "everything": {
      "type": "stdio",
      "command": "npx",
      "args": ["-y", "@modelcontextprotocol/server-everything"]
    },
    "remote": {
      "type": "http",
      "url": "http://localhost:8000/mcp"
    }
  }
}
```

每个 entry 的 key → `MCPConnectionConfig.name`，value 展开为其余字段。

> 当前测试多直接构造 `MCPConnectionConfig`；`MCPConfigLoader` 已实现并导出，业务侧可选用。

---



## 7. MCPClient



### 7.1 构造

```python
client = MCPClient([
    MCPConnectionConfig(name="everything", type="stdio", command="npx", args=[...]),
])
```

内部：`name → to_adapter_config()` → `MultiServerMCPClient(servers)`。

### 7.2 API


| 方法 / 属性                          | 说明                                                                                                                       |
| -------------------------------- | ------------------------------------------------------------------------------------------------------------------------ |
| `mcp_server_list`                | 返回构造时的 `list[MCPConnectionConfig]`                                                                                       |
| `async get_tools()`              | 首次调用拉工具并缓存到 `_tools`；之后返回缓存                                                                                              |
| `async register_tools(registry)` | `get_tools` → `to_tool_definition(tool, ToolType.MCP)` → `registry.register(definition, tool)`，返回 `list[ToolDefinition]` |


Handler 即适配器返回的 LangChain `BaseTool`；执行时由 Tool 模块调用 `ainvoke`。

---



## 8. 与 Tool / Agent / Strategy 的集成



### 8.1 注册链路

```text
MCPClient.register_tools(registry)
        ↓
ToolDefinition(type=MCP) + BaseTool handler
        ↓
StrategyFactory.create_as_subgraph(..., tool_registry=registry)
        ↓
ReAct ToolNode.arun → ToolExecutor.aexecute → handler.ainvoke(args)
```



### 8.2 典型用法（异步）

```python
mcp_client, registry = ...  # 保持 mcp_client 引用
agent = build_react_agent(..., tool_registry=registry)
result = await agent.ainvoke(session_id, UserInput(text="..."))
```



### 8.3 与 HITL

MCP 无独立 HITL 通道。注册后可改 `ToolDefinition.meta_data["required_approval"]`，由 ReAct ActionNode 触发 APPROVAL；缺参走 INPUT。验证见 `tests/test_react_agent_hitl_mcp.py`。

### 8.4 LLM 可见性

`ToolRegistry.get_tools()` 将 MCP 工具与 FUNCTION 一样输出为 OpenAI function schema；`type=MCP` 仅供运行时区分，不改变绑定形态。

---



## 9. 生命周期（实现约定）



### stdio

```text
构造 MCPClient
    → MultiServerMCPClient 按需拉起子进程
保持 client 引用 + Agent ainvoke/astream
    → 运行期连接有效
client / 进程退出
    → 子进程随适配器侧关闭回收
```

本模块不提供显式 `connect()` / `close()`；生命周期由适配器与调用方引用管理。

### http

```text
构造 MCPClient → 按需 HTTP 连接远程 Server
Server 由外部独立部署与运维
```

---



## 10. 验证与测试夹具


| 脚本                                   | 内容                                                                |
| ------------------------------------ | ----------------------------------------------------------------- |
| `tests/test_mcp_client.py`           | stdio / http：`get_tools`、`register_tools`、`ToolExecutor.aexecute` |
| `tests/test_react_agent_mcp.py`      | ReAct + MCP：`ainvoke` / `astream`                                 |
| `tests/test_react_agent_hitl_mcp.py` | ReAct + MCP + HITL（INPUT / APPROVAL）                              |
| `tests/mcp_server.py`                | FastMCP + business/it_operations，`streamable-http`，默认 `/mcp`      |


stdio 常用：`npx -y @modelcontextprotocol/server-everything`。  
http 常用：先起 `mcp_server.py`，再连 `http://localhost:8000/mcp`。

---



## 11. v0.1.0 范围



### 已实现

- [x] `MCPClient`（`MultiServerMCPClient` 封装）
- [x] stdio / http（streamable HTTP）
- [x] `MCPConnectionConfig` + 校验 + `to_adapter_config`
- [x] `MCPConfigLoader`（`mcpServers`）
- [x] Tools 发现与注册到 `ToolRegistry`（`ToolType.MCP`）
- [x] 经异步 Tool 链路执行（ReAct 手动验证）



### 本版本不做

- [ ] Resources / Prompts / 非 Tool 能力
- [ ] 显式 connect/close 与连接状态机
- [ ] Agent 内建自动加载 MCP 配置（由调用方组装）
- [ ] sync `invoke` 跑 MCP



### 后续可演进

- 配置热更新 / 多 Server 动态增删
- Resources、Prompts
- 显式生命周期 API
- 混用 FUNCTION+MCP 时的轨选择策略强化

