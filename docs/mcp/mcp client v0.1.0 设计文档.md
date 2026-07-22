# echo-agent MCP Client 设计文档

## 1. 背景

echo-agent 作为智能体运行库，需要具备连接外部能力服务的能力。MCP（Model Context Protocol）提供了一套标准化的 Client / Server 通信协议，使 echo-agent 可以接入 MCP Server 提供的能力。

本设计目标：

* echo-agent 实现 MCP Client 能力；
* 不实现 MCP Server；
* 基于 `langchain-mcp-adapters` 完成 MCP Client 接入；
* 支持不同运行环境下的 MCP Server 连接模式。

---

## 2. 设计目标

### 2.1 MCP Client

echo-agent 作为 MCP Client：

```text
echo-agent
    |
MCP Client
    |
MCP Server
```

负责：

* MCP Server 连接；
* MCP Server 配置解析；
* MCP Client 生命周期管理；
* MCP Server 能力发现；
* MCP Server 能力调用。

MCP 协议通信和底层 transport 实现由 MCP SDK 与 `langchain-mcp-adapters` 负责。

---

## 3. MCP Server 运行模式

MCP Server 与 echo-agent 的运行关系决定连接方式。echo-agent 支持三种 MCP Server 运行模式：

### 3.1 Embedded MCP Server

#### 定义

MCP Client 与 MCP Server 位于同一宿主应用程序中。

结构：

```text
+--------------------------------+
| Agent Application              |
|                                |
|   echo-agent                   |
|       |                        |
|       | in-process             |
|       |                        |
|   MCP Server                   |
|                                |
+--------------------------------+
```

特点：

* Client 与 Server 生命周期绑定；
* 无需外部通信 transport；
* 通信成本最低；
* 适用于 Agent 应用与 MCP Server 共同运行在同一宿主应用程序中的场景。

例如：

* Agent 应用程序内部集成 MCP Server；
* Agent SDK 场景；
* 测试环境。

### 3.2 Local MCP Server

#### 定义

MCP Server 与 echo-agent 位于同一机器，但运行于不同进程。

结构：

```text
echo-agent

    |
    |
 stdio

    |
    |

MCP Server Process
```

特点：

* MCP Client 负责 MCP Server 进程管理；
* 使用 stdio transport；
* MCP Server 生命周期通常与 echo-agent 生命周期相关。

适用于：

* 本地工具扩展；
* 桌面 Agent 应用；
* 本机能力调用。

### 3.3 Remote MCP Server

#### 定义

MCP Server 与 echo-agent 位于不同机器。

结构：

```text
 echo-agent
    |
    |
streamable HTTP
    |
    |
 MCP Server
```

特点：

* MCP Server 独立部署；
* 使用网络通信；
* MCP Server 生命周期独立管理。

适用于：

* 云端服务；
* 企业内部服务；
* 远程能力调用。

---

## 4. Transport 支持策略

echo-agent 根据 MCP Server 部署模式选择通信方式。

| MCP Server 模式 | Transport       |
| --------------- | --------------- |
| Embedded        | In-process      |
| Local           | stdio           |
| Remote          | streamable HTTP |

其中，stdio 和 streamable HTTP 基于 `langchain-mcp-adapters` 实现。

---

## 5. MCP Server 配置管理

echo-agent 不负责 MCP Server 注册。MCP Server 信息来源可以包括本地配置、外部提交和上层系统管理。echo-agent 负责解析 MCP Server 描述信息，并创建对应 MCP Client。

流程：

```text
MCP Server Definition
        |
    Config Parser
        |
    MCP Client
        |
    MCP Server
```

示例：

```json
{
  "servers": {
    "filesystem": {
      "transport": "stdio",
      "command": "xxx",
      "args": []
    },

    "weather": {
      "transport": "streamable_http",
      "url": "xxx"
    }
  }
}
```

---

## 6. 技术实现

### 基础实现

基于 `langchain-mcp-adapters` 封装 `MultiServerMCPClient`。

流程：

```text
MCP Server Config
        |
MCP Client Manager
        |
MultiServerMCPClient
        |
    MCP Server
```

---

## 7. 模块设计

建议结构：

```text
echo_agent/
    mcp/
        config.py
        client.py
        manager.py
        connection/
            embedded.py
            stdio.py
            http.py
```

### MCP Client Manager

职责：

* 管理 MCP Server 配置；
* 创建 MCP Client；
* 管理 MCP Server 生命周期；
* 管理连接状态。

### MCP Connection

统一抽象：

```python
class MCPConnection:
    async def connect()
    async def discover()
    async def close()
```

实现：`EmbeddedConnection`、`StdioConnection`、`HTTPConnection`。

---

## 8.生命周期管理

### Local MCP Server

启动流程：

```text
echo-agent start
    |
spawn MCP Server
    |
connect MCP Server
    |
runtime ready
```

关闭流程：

```text
echo-agent shutdown
    |
terminate MCP Server
```

### Remote MCP Server

启动流程：

```text
echo-agent start
    |
connect MCP Server
    |
runtime ready
```

关闭流程：

```text
close connection
    |
echo-agent shutdown
```

---

## 9. v0.1.0 实现范围

### 第一阶段

实现：

* MCP Client；
* stdio transport；
* streamable HTTP transport；
* MCP Server configuration；
* MCP Server discovery。

依赖：`langchain-mcp-adapters`

### 第二阶段

实现：

* Embedded MCP Server support。

重点解决：

* in-process communication；
* Client / Server 生命周期管理；
* 宿主应用程序集成方式。
