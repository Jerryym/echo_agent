# echo-agent 跨语言接入（v0.1）设计文档

| 项目 | 内容 |
| --- | --- |
| 版本 | v0.1 |
| 状态 | 设计修订；执行面 gRPC 与必填 Agent 工厂已落地；集成方入口示例已提供 |
| 目标 | 非 Python 宿主传入 `AgentConfig`；集成方用 Python 自定义图构建 Agent；本库提供通信与执行转发 |

> **协议细节**以 `echo_agent/adapter/proto/echo_agent.proto` 为准。  
> **Adapter 实现契约**见 [runtime adapter v0.1.0 设计文档](./runtime%20adapter/runtime%20adapter%20v0.1.0%20设计文档.md)。  
> **集成方入口示例**：`examples/integrator_runtime/`。

---

## 1. 背景

echo-agent Runtime 基于 Python（LangChain / LangGraph）实现。跨语言场景下：

1. **集成方（Python）**：定义智能体的图与组装逻辑（`RootGraph` / Strategy / Tool / Skill / MCP 装配等）。
2. **宿主应用（非 Python）**：提供运行配置（`AgentConfig`，含本机路径、模型、Skill/MCP 列表等），并通过进程外协议调用 Agent。

本库负责稳定的 gRPC 执行面，不内置默认 Agent 组装配方；组装由集成方工厂完成。

---

## 2. 设计目标

### 2.1 核心目标

1. **客户端传递 `AgentConfig`**  
   非 Python 宿主通过 `CreateAgent` 下发配置（含 `mcp_allowed_directories` 等与本机相关的字段）。

2. **集成方自定义图构建 Agent**  
   启动时注入 `factory`；`CreateAgent` 调用工厂消费 `AgentConfig` 并返回 `Agent`。图逻辑不在客户端、不在协议里序列化。

3. **本库提供通信执行面**  
   `EchoAgentService`：CreateAgent / Invoke / Stream / Resume / StreamResume / Cancel，以及事件归一化。

4. **宿主可自启 Runtime**  
   静默拉起集成方入口或 `python -m echo_agent.adapter.grpc.server --factory …`。

### 2.2 非目标

- 本库内置默认 ReAct / 其它默认组装配方  
- Agent Manifest / 配置文件挂载体系  
- 产品化 Registry 作为集成 API  
- 宿主语言侧 Graph DSL 或 Runtime 重实现  
- Agent 管理平台、多租户、Session 生命周期服务  
- 强制集成方自研 gRPC Servicer  

Session 由宿主生成并维护，仅作为调用参数传入。

### 2.3 职责切分


| 职责 | 承担方 |
| --- | --- |
| `AgentConfig`（模型、prompt、skill、MCP、本机目录等） | **非 Python 客户端**经 gRPC 传入 |
| 自定义图与组装（`build_agent(config) → Agent`） | **集成方 Python（必填工厂）** |
| gRPC、句柄表、执行转发、事件映射 | **本库** |
| `session_id`、UI、自启/停 Runtime | **非 Python 宿主** |

---

## 3. 总体架构

```text
+------------------------------------------+
| Host（非 Python）                         |
|  - 构造 AgentConfig（含本机目录等）       |
|  - gRPC Client                            |
|  - session_id / HITL UI / 自启进程        |
+--------------------+---------------------+
                     |
        CreateAgent(AgentConfig)
        Invoke / Stream / Resume / Cancel
                     |
+--------------------v---------------------+
| Runtime 进程                              |
|  EchoAgentService（本库）                 |
|  AgentRuntime(factory=...)（本库）        |
|  factory → Agent（集成方）                |
|  echo_agent.core                          |
+------------------------------------------+
```

---

## 4. 核心原则

### 4.1 配置与拓扑分离

- **配置**：客户端 `AgentConfig`。  
- **拓扑**：集成方工厂（启动时注入，必填）。

### 4.2 Python Runtime 是唯一执行端

编译与运行仅在 Runtime 进程内。

### 4.3 本库提供通信，集成方必须提供工厂

```text
AgentRuntime(factory=build_agent)   # factory 必填
CreateAgent(AgentConfig, RuntimeOptions?)
  → agent = await factory(config, runtime_options)
  → 分配 agent_id
```

无工厂则无法构造 `AgentRuntime`；本库**不**再回退默认 ReAct。

### 4.4 Handle 模型


| 标识 | 含义 | 管理方 |
| --- | --- | --- |
| `agent_id` | CreateAgent 返回的实例句柄 | Runtime（进程内） |
| `session_id` | 多轮 / HITL 会话键 | 宿主 |

### 4.5 非侵入核心库

工厂注入与 gRPC 位于 `echo_agent.adapter`；业务组装在集成方代码中。

---

## 5. Agent 构建与集成方入口

### 5.1 工厂约定

```python
async def build_agent(
    config: AgentConfig,
    runtime_options: RuntimeOptions | None = None,
) -> Agent:
    ...
    return Agent(config, runtime_config, my_root_graph)
```

### 5.2 启动方式

**推荐（集成方入口）：**

```text
uv run python -m examples.integrator_runtime.main --host 127.0.0.1 --port 50051
```

**或 CLI 指定工厂：**

```text
uv run python -m echo_agent.adapter.grpc.server \
  --factory examples.integrator_runtime.build_agent:build_agent \
  --host 127.0.0.1 --port 50051
```

示例代码见 `examples/integrator_runtime/`（`build_agent.py` + `main.py`）。

### 5.3 客户端 CreateAgent

宿主下发 `AgentConfig`（含本机 `mcp_allowed_directories`）与可选 `runtime_options`；服务端校验后调用工厂，返回 `agent_id`。

---

## 6. 通信契约（摘要）

完整定义见 `echo_agent/adapter/proto/echo_agent.proto`。

```protobuf
service EchoAgentService {
  rpc CreateAgent(CreateAgentRequest) returns (AgentHandle);
  rpc DeleteAgent(DeleteAgentRequest) returns (DeleteAgentResponse);
  rpc Invoke(InvokeRequest) returns (AgentResponse);
  rpc Stream(InvokeRequest) returns (stream AgentEvent);
  rpc Resume(ResumeRequest) returns (AgentResponse);
  rpc StreamResume(ResumeRequest) returns (stream AgentEvent);
  rpc Cancel(CancelRequest) returns (CancelResponse);
}
```

调用顺序：启动（已注入工厂）→ CreateAgent → Invoke/Stream →（HITL）Resume/StreamResume →（可选）Cancel 中止当轮 → DeleteAgent。  
`InvokeRequest` / `ResumeRequest` 可选 `metadata`（含保留键 `http_headers`），透传到 `RunnableConfig.configurable["metadata"]`；`Cancel` 与 Stream 事件细节见 [快速接入](./runtime%20adapter/快速接入.md) §5–§7。

---

## 7. Runtime 生命周期与打包

- 宿主可自启集成方入口或带 `--factory` 的 server 模块。  
- 打包时打进本库 + 集成方工厂；CreateAgent 仍由客户端传本机配置。  
- 注意内置 MCP 对 `npx`/`uvx` 的外部依赖。

---

## 8. 实现现状

**已具备：**

- gRPC 执行面与 `AgentConfig` 转换  
- `AgentRuntime(factory=...)`（factory **必填**）  
- `build_runtime_config`（供工厂复用 checkpointer 选项）  
- `--factory module:attr` 与 `examples/integrator_runtime` 入口  
- `Cancel`（当轮中止 + checkpoint tip 回滚）  

**不做：**

- 本库默认 ReAct 组装  
- Agent Manifest / Registry 产品 API / 协议内 Graph DSL  
