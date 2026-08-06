# echo-agent 跨语言 Runtime Adapter 设计文档


| 项目  | 内容                                    |
| --- | ------------------------------------- |
| 版本  | v0.1.0                                |
| 状态  | **部分实现**（见 §14 清单）                    |
| 目标  | 对齐当前`Agent` API，为非 Python 宿主提供进程外接入契约 |


> 本文描述 Runtime Adapter 契约与实现范围。实现清单见 §14。  
> **快速接入**（半页说明）：[快速接入.md](./快速接入.md)。

---

## 1. 背景

echo-agent 定位：

> echo-agent 是可独立运行的智能体运行时库；既可作为独立 Python 库使用，也可作为其他系统的底层执行引擎。
> **不承担**：日志、配置中心、接口服务、可视化编排等系统级职责。

当前实现基于 LangChain / LangGraph，已提供：

- Agent 执行（`invoke` / `ainvoke` / `stream` / `astream`）
- HITL 恢复（`resume` / `aresume` / `stream_resume` / `astream_resume`）
- LangGraph 工作流与 Checkpoint（`session_id` → `thread_id`）
- Tool / MCP / Skill
- Streaming（`stream_mode="messages"`, `subgraphs=True`）

对外 Python 入口为 `Agent` + `AgentConfig` + `RuntimeConfig` + `RootGraph`。

非 Python 宿主（C++ / C# / Java / Go / Rust 等）无法直接依赖本包，需要 **跨语言 Runtime Adapter**：在进程边界上将稳定协议映射到现有 `Agent` API。

---

## 2. 设计目标

### 2.1 核心目标

提供 **Runtime Adapter**，使非 Python 应用通过 gRPC（可选 HTTP）调用 echo-agent Agent Runtime。

```text
+-------------------------+
| Host Application        |
| C++ / C# / Java / Go    |
+-----------+-------------+
            |
     Runtime Adapter
     (gRPC / 可选 HTTP
      + 默认 ReAct 组装)
            |
+-----------v-------------+
| echo-agent 核心库       |
| （积木，不含组装配方）  |
| Agent / LangGraph       |
| Tool / MCP / Skill/HITL |
+-------------------------+
```

### 2.2 非目标

不构建 Agent 平台。不负责：

- Agent 管理平台 / 注册中心
- 用户管理、多租户、权限
- 配置中心、日志平台、服务注册发现
- 可视化编排
- Session 生命周期服务（CreateSession / DeleteSession）

这些属于宿主系统职责。

### 2.3 本阶段明确不做


| 项                 | 说明                                                              |
| ----------------- | --------------------------------------------------------------- |
| **AgentBuilder**  | **暂不新增**。v0.1 在 **Adapter** 内固定组装默认 ReAct Agent                 |
| **侵入核心库**         | **禁止**：不在 `echo_agent.core` 新增组装配方 / CreateAgent / AgentRuntime |
| Knowledge / KB 执行 | `kb_list` 字段保留、**默认空**；透传忽略，不解析不注入                              |
| 自定义 Graph / 多策略   | 仅默认 ReAct；Plan-Execute、自定义图不在本阶段协议暴露                            |
| 本地业务 Tool 注册协议    | `AgentConfig` 无本地 Tool 字段；一阶段工具来源为 MCP（及 Skill 工具）              |


---

## 3. 核心设计原则

### 3.1 Runtime Adapter，而不是 Agent Platform


|                                 | Agent Platform | Runtime Adapter |
| ------------------------------- | -------------- | --------------- |
| Agent 管理 / 用户 / 配置中心            | 是              | 否               |
| 按配置创建可执行 Agent 实例               | 是              | 是（固定 ReAct）     |
| Agent 执行 / Stream / HITL Resume | 是              | 是               |
| Tool / MCP / Skill              | 是              | 复用现有能力          |


### 3.2 对齐现有 Agent API，不另造执行语义

Adapter 是薄映射层，必须对齐当前实现：

```python
Agent(agent_config, runtime_config, graph)

agent.invoke(session_id, input)      # UserInput 或 Graph input_schema
agent.stream(session_id, input)
agent.resume(session_id, values)
# 以及 ainvoke / astream / aresume / stream_resume / astream_resume
```

要点：

- **必须传** `session_id`（映射 LangGraph `thread_id`），多轮与 HITL 依赖 Checkpoint
- 输入对齐 `UserInput`（`text` + 可选 `attachments`），不是裸 `string`
- HITL 为一级能力，协议必须包含 **Resume** 与 **interrupt** 事件
- 当前 `stream` 产出为 LangGraph **messages** 流；协议中的结构化事件由 Adapter **映射/归一化**，非 Agent 原生枚举

### 3.3 复用现有 AgentConfig

跨语言不重新设计 Agent Definition，复用：

```python
class AgentConfig(BaseModel):
    name: str
    description: str | None = None
    llm_config: LLMConfig
    system_prompt: str | None = None
    kb_list: list[str] = []                    # 默认空；当前忽略
    skill_list: dict[str, Any] = {}            # name → path | url
    mcp_allowed_directories: str | list[str]   # 必填；内置 Filesystem 根
    mcp_servers: list[MCPConnectionConfig] = []
```

说明：

- `llm_config` / `system_prompt` 为**能力声明**；由 Adapter 内 ReAct 组装在构建期消费（与现有 Agent 模块一致：Agent 运行期不自动注入）
- `kb_list`：**默认空即可**，CreateAgent 时透传，不做 Knowledge 处理
- 创建时仍合并内置 Fetch / Filesystem（与 `AgentConfig` 校验器行为一致）

### 3.4 构建期仍需 RuntimeConfig

当前构造签名为：

```python
Agent(agent_config: AgentConfig, runtime_config: RuntimeConfig, graph: RootGraph)
```

`RuntimeConfig` 含 `checkpointer` / `store`。多轮与 `resume` **要求** checkpointer 非空。

v0.1 Adapter 策略：

- CreateAgent 时默认使用进程内 `InMemorySaver`（或可配置的持久化实现，宿主通过启动参数指定）
- 协议层可不暴露完整 LangGraph Checkpointer 对象；用 `RuntimeOptions`（可选）描述持久化策略即可

### 3.5 非侵入原则：ReAct 组装只在 Adapter，不进入核心库

**默认 ReAct Agent 的构建逻辑仅存在于 Adapter；不得侵入** `echo_agent.core`**。**


| 层级                   | 职责                                                                                                     | 不做什么                                                       |
| -------------------- | ------------------------------------------------------------------------------------------------------ | ---------------------------------------------------------- |
| `echo_agent.core`    | 提供积木：`Agent` / `AgentConfig` / `RuntimeConfig` / `RootGraph` / `StrategyFactory` / Tool·MCP·Skill·HITL | 不提供 `CreateAgent`、一键创建 ReAct Agent、`AgentRuntime`、gRPC/协议层 |
| `echo_agent.adapter` | 协议适配、`CreateAgent`、**ReAct 组装**（对齐 console 用例）、事件映射、进程入口                                               | 不改 core 执行语义；不把组装逻辑下沉进 core                                |


约束：

- Adapter 是与 `console/case` **同级的消费方**，只调用 core 已有 API 拼装图与 Agent
- **禁止**在 `core/agent`、`core/strategy`、`core/runtime` 等包中新增「默认 ReAct 配方」或把 Adapter 组装代码搬进库
- core 继续保持「配置声明 + 图由调用方构建」；跨语言场景下「调用方」= Adapter

```text
宿主
  → Adapter（协议 + ReAct 组装）
  → 仅调用 core 已有 API
       Agent(...) / StrategyFactory.create_as_subgraph(REACT, ...)
       setup_skills / MCP register_tools / invoke|stream|resume
```

---

## 4. 总体架构

```text
                 Host Application
              C++ / C# / Java / Go
                       |
                AgentConfig (JSON/proto)
                       |
          +------------------------+
          | Runtime Adapter        |
          |  gRPC Adapter          |
          |  HTTP Adapter(optional)|
          |  AgentRuntime（拟新增） |
          |  Create/Invoke/Stream  |
          |  Resume                |
          |  ★ 默认 ReAct 组装     |
          |    （仅此层，不进 core）|
          +------------------------+
                       |
                       │ 只调用已有 API（非侵入）
                       ▼
          +------------------------+
          | echo-agent 核心库      |
          | （积木，不含组装配方）  |
          | Agent / RootGraph      |
          | StrategyFactory(ReAct) |
          | ToolRegistry / MCP     |
          | Skill setup / HITL     |
          +------------------------+
```

命名注意：现有 `echo_agent.core.runtime` 表示 LangGraph Runtime 封装（`RuntimeConfig` / HITL / interrupt）。  
**Adapter 层不要占用** `core/runtime`，建议放在 `echo_agent/adapter/`（或 `gateway/`）。

---

## 5. AgentRuntime（Adapter 侧入口）

> `AgentRuntime` **属于 Adapter 包**，不是 core 模块。

### 5.1 职责

- 接收 `AgentConfig`（+ 可选 `RuntimeOptions`）
- **在 Adapter 内固定组装默认 ReAct Agent**（不引入 `AgentBuilder`，不侵入 core）
- 持有 `agent_id → Agent` 实例表
- 将协议调用转发到 `Agent.invoke` / `stream` / `resume` 等

### 5.2 接口示意（Python，拟议）

```python
class AgentRuntime:
    async def create_agent(
        self,
        config: AgentConfig,
        runtime_options: RuntimeOptions | None = None,
    ) -> str:
        """返回 agent_id。内部组装默认 ReAct Agent。"""
        ...

    async def invoke(
        self,
        agent_id: str,
        session_id: str,
        input: UserInput,
    ) -> AgentInvokeResult:
        ...

    async def stream(
        self,
        agent_id: str,
        session_id: str,
        input: UserInput,
    ):
        """async iterator[AgentEvent]"""
        ...

    async def resume(
        self,
        agent_id: str,
        session_id: str,
        values: dict,
    ) -> AgentInvokeResult:
        ...

    async def stream_resume(
        self,
        agent_id: str,
        session_id: str,
        values: dict,
    ):
        ...
```

### 5.3 默认 ReAct 组装（仅 Adapter；对齐现有用例，无 Builder）

与 `console/case/react_agent_case.py` / MCP 用例同构，逻辑**仅**写在 Adapter 的 `AgentRuntime`（或同目录辅助模块）中，**不进入** `echo_agent.core`：

```text
AgentConfig
    │
    ├─ ToolRegistry
    ├─ MCPClient(config.mcp_servers).register_tools(registry)   # 若有 MCP
    ├─ Agent(..., placeholder_graph) + await setup_skills(registry)
    ├─ StrategyFactory.create_as_subgraph(REACT, llm_config, tool_registry)
    ├─ RootGraph: START → ReAct → END
    └─ Agent 实例（持有 CompiledGraph + RuntimeConfig.checkpointer）
```

约束：

- **不新增** `AgentBuilder` / `DefaultAgentBuilder` / `AgentBuilderRegistry`（无论 adapter 还是 core）
- **不**在 core 中新增 `create_react_agent()` 或等价「一键创建」API
- `kb_list` 不参与组装
- 一阶段不通过协议注册任意 Python 本地 Tool；工具来自 MCP + Skill 工具（`load_skill` / `read_skill_resource`）

后续若需 Supervisor / 自定义 Graph，优先仍在 Adapter 扩展组装路径；是否抽到 core 需单独评审；**不在 v0.1 范围**。

---

## 6. Tool / MCP / Skill 装配

复用现有实现，**无** `ToolResolver`：

```text
AgentConfig.mcp_servers
    → MCPClient
    → register_tools(ToolRegistry)

AgentConfig.skill_list
    → Agent.setup_skills(ToolRegistry)
    → SkillCatalog + load_skill / read_skill_resource

ToolRegistry
    → ReActStrategy / ToolNode
```

`mcp_allowed_directories`：创建 `AgentConfig` 时必填，驱动内置 Filesystem MCP 根目录。

---

## 7. Session 设计原则

**不提供** SessionService（CreateSession / DeleteSession）。

Session 归属宿主（如 `conversation_id`、`ticket_id`）。

但与 §13 旧稿不同：**每次执行必须由宿主传入** `session_id`。

```text
宿主 session_id  ──→  Agent.invoke/stream/resume(..., session_id)
                   ──→  RunnableConfig.configurable.thread_id
```

同一 `agent_id` + 同一 `session_id` 共享 Checkpoint（需 checkpointer 已配置），从而支持多轮与 HITL resume。

---

## 8. Runtime Protocol

推荐：**gRPC + protobuf**（多语言生成、Streaming、类型约束）。
HTTP/SSE 可作为可选第二适配器，语义与 gRPC 一致。

---

## 9. protobuf API

### 9.1 Service

```protobuf
service EchoAgentService {
  rpc CreateAgent(CreateAgentRequest) returns (AgentHandle);
  rpc DeleteAgent(DeleteAgentRequest) returns (DeleteAgentResponse);

  rpc Invoke(InvokeRequest) returns (AgentResponse);

  rpc Stream(InvokeRequest) returns (stream AgentEvent);

  rpc Resume(ResumeRequest) returns (AgentResponse);

  rpc StreamResume(ResumeRequest) returns (stream AgentEvent);

  // 中止当轮图执行（非 HITL resume {"cancelled":true}）
  rpc Cancel(CancelRequest) returns (CancelResponse);
}

message DeleteAgentRequest { string agent_id = 1; }
message DeleteAgentResponse {}
```

### 9.2 CreateAgent

```protobuf
message CreateAgentRequest {
  AgentConfig config = 1;
  RuntimeOptions runtime_options = 2;  // 可选；缺省进程内 Memory checkpointer
}

message AgentHandle {
  string id = 1;
}

message RuntimeOptions {
  // v0.1：例如 "memory" | "sqlite"；具体取值实现期再定
  string checkpointer_kind = 1;
  string checkpointer_uri = 2;  // 可选
}
```

### 9.3 AgentConfig 映射

```protobuf
message AgentConfig {
  string name = 1;
  string description = 2;
  LLMConfig llm_config = 3;
  string system_prompt = 4;
  repeated string kb_list = 5;                 // 默认空；服务端忽略
  map<string, string> skill_list = 6;          // name → path 或 url
  repeated string mcp_allowed_directories = 7; // 对应 Python str | list[str]
  repeated MCPConnectionConfig mcp_servers = 8;
}

message LLMConfig {
  string base_url = 1;
  string api_key = 2;
  string model_name = 3;
  string model_provider = 4;   // 默认 openai
  float temperature = 5;
  int32 max_tokens = 6;
  int32 timeout = 7;
  int32 max_retries = 8;
  bool use_responses_api = 9;
  string output_version = 10;
  // builtin_tools / extra_body：可用 google.protobuf.Struct 或 JSON 字符串扩展
  string extra_json = 11;
}

message MCPConnectionConfig {
  string name = 1;
  string type = 2;             // "stdio" | "http"
  string command = 3;          // stdio
  repeated string args = 4;    // stdio
  string url = 5;              // http
  map<string, string> headers = 6;
}
```

与 Python 对齐注意：

- `skill_list`：实现为 `dict[str, Any]`，当前语义为 name → path|url；proto 用 `map<string,string>` 足够
- `mcp_allowed_directories`：Python 允许单个 `str`；proto 用 `repeated`，单元素即等价
- `kb_list`：可省略或传空；**不做 Knowledge**

### 9.4 Invoke / Stream

```protobuf
message UserInput {
  string text = 1;
  repeated Attachment attachments = 2;  // v0.1 可选；当前 HumanMessage 仅用 text
}

message Attachment {
  string type = 1;  // image | audio | file
  string data = 2;  // base64 或 url
}

message InvokeRequest {
  string agent_id = 1;
  string session_id = 2;   // 必填 → thread_id
  UserInput input = 3;
  // 可选；透传到 RunnableConfig.configurable["metadata"]
  // 保留键 http_headers：JSON object 字符串 → 解析为 dict[str,str]
  map<string, string> metadata = 4;
}

message AgentResponse {
  string output = 1;                 // 最终回复文本（从 state 提取）
  bool interrupted = 2;              // 是否停在 HITL
  string interrupt_json = 3;         // interrupted=true 时的 interrupt payload
}
```

### 9.5 Resume

对齐 `Agent.resume(session_id, values)`：

```protobuf
message ResumeRequest {
  string agent_id = 1;
  string session_id = 2;
  string values_json = 3;  // HITL resume 载荷，如 {"values":{...}} / {"cancelled":true}
  map<string, string> metadata = 4;  // 同 InvokeRequest.metadata
}
```

### 9.6 Cancel

中止指定 `session_id` 上正在进行的当轮执行（Invoke / Stream / Resume / StreamResume）。

```protobuf
message CancelRequest {
  string agent_id = 1;
  string session_id = 2;  // = LangGraph thread_id
}

message CancelResponse {
  // true：找到活跃 turn 并已取消；false：当时无活跃 turn（幂等成功）
  bool cancelled = 1;
}
```

语义：

1. 开跑前记录 tip 的 `checkpoint_id`；当轮执行登记为 `asyncio.Task`。  
2. `Cancel` → `task.cancel()` → `Agent.restore_checkpoint`：用 `update_state` 将 tip **fork** 回开跑前基线（不删历史）。  
3. 首轮无基线（`checkpoint_id is None`）时写成空完成态。  
4. **不是** HITL 的 `Resume({"cancelled":true})`。  
5. 客户端断 Stream 时服务端走同一取消路径；被中止的 RPC status 为 `CANCELLED`。  
6. 同一 `(agent_id, session_id)` 同时只允许一轮，否则 `FAILED_PRECONDITION`。

### 9.7 Streaming 事件

当前 `Agent.stream` 返回 LangGraph messages 流。协议层定义归一化事件，由 Adapter 映射：

```protobuf
message AgentEvent {
  string type = 1;  // message | interrupt | error | done | cancelled
                    // 可选扩展（Adapter 映射目标，非原生）：tool_call | tool_result
  bytes data = 2;   // UTF-8 JSON
}
```

示例：

```json
{"type": "message", "data": {"role": "assistant", "content": "..."}}
{"type": "interrupt", "data": {"id": "...", "type": "approval", "description": "..."}}
{"type": "done", "data": {"output": "..."}}
{"type": "cancelled", "data": {}}
```

说明：`reasoning` / `tool_call` / `tool_result` 等细粒度类型为**可选增强**，依赖 Adapter 从 messages/subgraphs 解析；v0.1 以 `message` + `interrupt` + `done` / `error` / `cancelled` 为最小集合。

---

## 10. 目录结构

避免与 `echo_agent/core/runtime` 冲突：

```text
echo_agent/
├── adapter/                    # 协议适配层（非侵入 core）
│   ├── __init__.py
│   ├── agent_runtime.py        # Create / Delete / Invoke / Stream / Resume / Cancel
│   ├── events.py               # messages → AgentEvent 映射
│   ├── proto/                  # gRPC 契约源（宿主可单独拷贝）
│   │   └── echo_agent.proto
│   └── grpc/
│       ├── generate.py         # proto → pb stubs
│       ├── server.py
│       ├── service.py
│       └── pb/                 # 生成物
└── core/                       # 现有实现，不变；不含组装配方
    ├── agent/
    ├── runtime/                # RuntimeConfig / HITL / interrupt（保持原义）
    ├── strategy/
    ├── tool/
    ├── mcp/
    └── ...
```

> ReAct 等默认组装由集成方注入 `AgentFactory`（见 `examples/integrator_runtime/`），不强制放在 adapter 包内。

入口进程（示例）：`echo-agent-server` → 构造 Adapter 侧 `AgentRuntime` → 启动 gRPC。

---

## 11. 启动方式

```python
from echo_agent.adapter import AgentRuntime  # Adapter，非 core

runtime = AgentRuntime()  # ReAct 组装在 adapter 内；无 AgentBuilder；不侵入 core

grpc_server.start(runtime)
```

---

## 12. 使用流程

```text
1. 宿主构造 AgentConfig（kb_list 可省略/空；填 llm / mcp / skill 等）
2. CreateAgent → agent_id
3. 宿主自管 session_id
4. Invoke / Stream(agent_id, session_id, UserInput)
5. 若 interrupted → 宿主收集人机结果 → Resume / StreamResume
6. 运行中可 Cancel(agent_id, session_id) 中止当轮（tip 回滚）
7. 获取最终 output；业务结束 → DeleteAgent
```

```text
C# / C++
   │
AgentConfig
   │
CreateAgent
   │
AgentRuntime（Adapter：协议 + ReAct 组装）
   │  仅调用 core 已有 API（非侵入）
Agent.invoke / stream / resume / cancel
   │
AgentResponse / AgentEvent
```

---

## 13. 与现有实现差异对照（相对旧稿）


| 旧稿表述                                    | 对齐后                                                     |
| --------------------------------------- | ------------------------------------------------------- |
| `AgentBuilder` / `create_react_agent()` | **不新增 Builder**；**仅在 Adapter** 固定 ReAct 组装，**不侵入 core** |
| `Invoke(agent_id, string input)`        | `agent_id` + `session_id` + `UserInput`                 |
| 无 Resume                                | 增加**Resume / StreamResume**，对齐 HITL                     |
| 无当轮中止                                 | 增加**Cancel** + checkpoint tip 回滚；断 Stream 同路径           |
| Stream = reasoning/tool_* 原生事件          | 原生为 messages；协议事件由 Adapter 映射                           |
| 仅`AgentConfig` 即可构造                     | 还需**`RuntimeConfig`（checkpointer）**                     |
| `ToolResolver`                          | 不存在；用**ToolRegistry + MCP + setup_skills**              |
| 顶层`echo_agent/runtime`                  | 改为**`echo_agent/adapter`**，避免与 `core.runtime` 混淆        |
| §18 全部`[x]`                             | 改为**未实现** `[ ]`                                         |
| Knowledge 可用                            | `kb_list` **默认空并忽略**                                    |


---

## 14. 第一阶段实现范围

实现（计划）：

```text
[x] protobuf 定义（含 session_id / UserInput / Resume / LLMConfig / MCPConnectionConfig）
[x] gRPC Adapter
[x] AgentConfig proto ↔ Pydantic 转换
[x] AgentRuntime（adapter 包）+ 默认 ReAct 组装（仅 adapter，无 AgentBuilder）
[x] CreateAgent（默认 Memory checkpointer）
[x] Invoke / Stream
[x] Resume / StreamResume + interrupt 事件
[x] Cancel（当轮中止 + checkpoint tip 回滚）
[x] messages → AgentEvent 最小映射
[ ] Python 示例 Client
[ ] C# Demo（可选）
```

暂不实现：

```text
[ ] AgentBuilder / BuilderRegistry
[ ] Knowledge（kb_list 仅透传）
[ ] 自定义 Graph / 非 ReAct 策略协议
[ ] 本地业务 Tool 注册 RPC
[ ] Agent 注册中心 / 管理 / 用户 / 权限
[ ] Session 生命周期服务
[ ] 配置中心 / 服务治理
[ ] HTTP Adapter（可作为二期）
```

---

## 15. 最终定位

```text
                 Application
                      |
             Agent Runtime Contract
             (gRPC：Create / Invoke / Stream / Resume / Cancel)
                      |
                 Runtime Adapter
                 （协议 + 默认 ReAct 组装）
                      |
             echo-agent 核心库（积木，非侵入）
             (Agent / StrategyFactory / MCP / Skill / HITL)
```

核心思想：

> echo-agent 不提供 Agent 平台能力，而提供跨语言 Runtime Adapter，使其他语言应用通过稳定接口创建并调用现有 Agent Runtime。  
> v0.1 **不引入 AgentBuilder**；**默认 ReAct 组装仅在 Adapter 实现，不侵入核心库**；`kb_list` **默认空并忽略**；执行契约对齐 `session_id`、`UserInput` 与 HITL `resume`。

