# Agent 模块 v0.1.1 设计文档

## 1. 版本说明

| 项目 | 内容 |
|------|------|
| 版本 | v0.1.1 |
| 状态 | 已实现，手动测试通过 |
| 依赖 | LangGraph `CompiledStateGraph`、`langchain_core.runnables.RunnableConfig` |
| 上一版本 | v0.1.0 |

> v0.1.0 中未变更的部分（模块定位、Graph Runtime 封装原则、配置与运行分离原则）仍适用，本文档仅描述 v0.1.1 相对 v0.1.0 的实现变更。完整基线参见 `agent模块 v0.1.0 设计文档.md`。

### 1.1 v0.1.1 变更摘要

v0.1.1 将 Agent 从设计草案落地为可运行的 **CompiledGraph 封装层**，核心变化如下：

| 变更项 | v0.1.0（设计） | v0.1.1（实现） |
|--------|----------------|----------------|
| 模块结构 | `agent.py` / `config.py` / `context.py` / `builder.py` | `agent.py` / `agent_config.py` |
| 构造参数 | `(config, graph)` | `(agent_config, runtime_config, graph: RootGraph)` |
| 图编译时机 | 未明确 | 构造时 `RootGraph.compile(runtime_config)` |
| 运行上下文 | `AgentContext` 模型 | 无独立模型；`session_id` 直接映射 `thread_id` |
| 输入类型 | `Message` | `UserInput` 或 Graph `input_schema` 子类 |
| 调用方式 | `async invoke` / `async stream` | 同步 `invoke` / `stream` |
| 流式参数 | 未定义 | `stream_mode="messages"`, `subgraphs=True`, `version="v2"` |
| 调试 API | 无 | `get_state()` / `get_state_history()` |
| `AgentConfig.strategy` | 策略标识字段 | **已移除**；Strategy 在 Graph 构建期注入 |

---

## 2. 模块定位（v0.1.1 补充）

Agent 模块是 echo-agent 对外的 **运行入口封装层**，连接调用方与 LangGraph CompiledGraph。

**负责：**

- 持有 `AgentConfig`（静态声明）
- 持有 `RuntimeConfig` 并驱动 `RootGraph` 编译
- 提供 `invoke` / `stream` 统一调用入口
- 将 `session_id` 映射为 LangGraph `thread_id`
- 校验并构建 Graph 输入
- 提供 Checkpoint 状态调试接口

**不负责：**

- RootGraph 结构定义（Node / Edge / SubGraph 由调用方或 Strategy 构建）
- Strategy / Tool / LLM 的具体执行逻辑
- `AgentConfig` 字段的运行时自动注入（如 `system_prompt`、`llm_config` 需由 Graph 构建方消费）

---

## 3. 设计原则（v0.1.1 补充）

### 3.1 构建期编译原则

Agent 在 **构造阶段** 完成图编译，运行期只操作 `CompiledStateGraph`：

```text
RootGraph（结构定义）
        ↓ compile(runtime_config)
CompiledStateGraph
        ↓ 持有
Agent._compiled_graph
        ↓
invoke / stream
```

Strategy 子图在 Agent 构造之前完成编译，通过 `RootGraph.add_subgraph()` 挂载。

### 3.2 Session 即 Thread 原则

v0.1.1 不引入独立的 `AgentContext` 模型。调用方传入的 `session_id` 直接写入 LangGraph `RunnableConfig`：

```python
RunnableConfig(configurable={"thread_id": session_id})
```

同一 `session_id` 的多轮调用共享 Checkpoint 状态（需 `RuntimeConfig.checkpointer` 非空）。

### 3.3 配置声明与图构建分离原则

`AgentConfig` 中的 `llm_config`、`system_prompt` 等字段是 **能力声明**，Agent 本身不在运行时读取并注入 Graph Node。Graph 构建方（测试代码、后续 Builder）在创建 Node 时自行消费这些配置。

```text
AgentConfig.llm_config  ──→  Graph 构建方创建 LLMClient / Strategy
AgentConfig.system_prompt ──→ Graph 构建方传入 Node
Agent（运行期）          ──→ 仅转发 invoke / stream 到 CompiledGraph
```

---

## 4. 模块结构

```text
echo_agent/core/agent/
├── __init__.py          # 导出 Agent, AgentConfig
├── agent.py             # Agent 运行实体
└── agent_config.py      # AgentConfig 模型
```

对外导出：

```python
from echo_agent.core.agent import Agent, AgentConfig
# 或
from echo_agent import Agent, AgentConfig
```

v0.1.0 设计中的 `context.py`、`builder.py` 在 v0.1.1 **尚未实现**。

---

## 5. AgentConfig

### 5.1 模型定义

```python
class AgentConfig(BaseModel):
    name: str
    description: str | None = None

    llm_config: LLMConfig
    system_prompt: str | None = None

    kb_list: list[str] = Field(default_factory=list)
    skill_list: list[str] = Field(default_factory=list)
```

### 5.2 字段说明

| 字段 | 说明 |
|------|------|
| `name` | Agent 标识 |
| `description` | Agent 描述 |
| `llm_config` | LLM 运行配置；由 Graph 构建方传递给 Node / Strategy |
| `system_prompt` | 系统提示词声明；由 Graph 构建方传递给 LLM Node |
| `kb_list` | 可访问知识库列表（声明，v0.1.1 无运行时消费） |
| `skill_list` | 可使用技能列表（声明，v0.1.1 无运行时消费） |

### 5.3 v0.1.0 → v0.1.1 字段变更

| 字段 | 变更 |
|------|------|
| `strategy` | **已移除**。Strategy 选择改在 Graph 构建期通过 `StrategyFactory` 完成，不再由 AgentConfig 声明 |

---

## 6. Agent 实体

### 6.1 构造

```python
class Agent:
    def __init__(
        self,
        agent_config: AgentConfig,
        runtime_config: RuntimeConfig,
        graph: RootGraph,
    ):
        self._agent_config = agent_config
        self._runtime_config = runtime_config
        self._graph = graph
        self._compiled_graph = self._graph.compile(runtime_config)
```

| 参数 | 说明 |
|------|------|
| `agent_config` | Agent 静态配置 |
| `runtime_config` | 运行时能力配置（checkpointer / store） |
| `graph` | 未编译的 RootGraph |

构造完成后，`self._compiled_graph` 为 LangGraph `CompiledStateGraph`，后续所有调用均转发至该实例。

### 6.2 内部属性

| 属性 | 类型 | 说明 |
|------|------|------|
| `_agent_config` | `AgentConfig` | 静态配置 |
| `_runtime_config` | `RuntimeConfig` | 编译期注入的运行时能力 |
| `_graph` | `RootGraph` | 原始图结构（保留引用，便于调试） |
| `_compiled_graph` | `CompiledStateGraph` | 编译后可执行图 |

---

## 7. 公开 API

### 7.1 invoke

```python
def invoke(
    self,
    session_id: str,
    input: UserInput | type[BaseInput],
) -> dict:
```

**流程：**

```text
session_id
    ↓
_build_runnable_config() → RunnableConfig(thread_id=session_id)
    ↓
_build_graph_input(input) → graph_input
    ↓
_compiled_graph.invoke(graph_input, runnable_config)
    ↓
返回最终 State dict
```

**输入构建规则：**

| 条件 | graph_input |
|------|-------------|
| `graph.input_schema is None` | `{"input": input}` |
| `isinstance(input, input_schema)` | `input`（BaseInput 实例） |
| 类型不匹配 | 抛出 `TypeError` |

典型调用：

```python
result = agent.invoke("session_001", UserInput(text="查询用户u001"))
print(result["response"])
```

### 7.2 stream

```python
def stream(
    self,
    session_id: str,
    input: UserInput | type[BaseInput],
    version: str = "v2",
) -> Iterator:
```

输入构建规则与 `invoke` 相同。流式调用固定参数：

```python
self._compiled_graph.stream(
    graph_input,
    runnable_config,
    stream_mode="messages",
    subgraphs=True,
    version=version,
)
```

| 参数 | 默认值 | 说明 |
|------|--------|------|
| `stream_mode` | `"messages"` | 按 Message chunk 流式输出 |
| `subgraphs` | `True` | 包含子图（Strategy SubGraph）内的 token 事件 |
| `version` | `"v2"` | LangGraph stream 协议版本 |

**流式事件消费：**

v0.1.1 测试中，stream 产出的事件需上层自行解析。典型结构为 `(AIMessageChunk, metadata)` 或 `{"type": "messages", "data": (message, metadata)}`。ReAct Agent 场景建议按 `metadata["langgraph_node"] == "final"` 过滤，仅输出 FinalNode 的 token（参见 `tests/test_react_agent.py` 的 `extract_stream_text()`）。

### 7.3 get_state（Debug）

```python
def get_state(
    self,
    session_id: str,
    checkpoint_id: str | None = None,
) -> StateSnapshot:
```

读取指定 session 的当前 Checkpoint 状态。可选 `checkpoint_id` 回溯到特定检查点。

### 7.4 get_state_history（Debug）

```python
def get_state_history(self, session_id: str) -> Iterator[StateSnapshot]:
```

读取指定 session 的状态变更历史。

> 两个 Debug API 均标记为调试用途，不参与正常业务调用链路。

---

## 8. RunnableConfig 构建

```python
def _build_runnable_config(self, session_id: str) -> RunnableConfig:
    return RunnableConfig(
        configurable={
            "thread_id": session_id,
        }
    )
```

| configurable 键 | 来源 | 说明 |
|-----------------|------|------|
| `thread_id` | `session_id` 参数 | LangGraph Checkpoint 线程标识 |
| `checkpoint_id` | 仅 `get_state()` 可选传入 | 定位特定检查点 |

v0.1.1 **未** 将 `AgentConfig` 中的 `kb_list` / `skill_list` / `system_prompt` 写入 RunnableConfig。

---

## 9. Agent 构建模式

v0.1.1 无内置 Builder，调用方自行完成 Graph 组装。两种典型模式：

### 9.1 简单 LLM 图

```text
RootGraph
  START → LLMInvokeNode → END

AgentConfig（llm_config, system_prompt）
RuntimeConfig（checkpointer=InMemorySaver）
Agent(agent_config, runtime_config, graph)
```

参见 `tests/test_agent.py`。

### 9.2 Strategy 子图

```text
RootGraph
  START → ReAct(SubGraph) → END

StrategyFactory.create_as_subgraph(REACT, llm_config, tool_registry)
RootGraph.add_subgraph("ReAct", react_subgraph)

AgentConfig（llm_config）
RuntimeConfig（checkpointer=InMemorySaver）
Agent(agent_config, runtime_config, graph)
```

参见 `tests/test_react_agent.py`。

```text
构建期                              运行期
────────────────────────────────────────────────────
ToolRegistry.register(...)          agent.invoke(session_id, UserInput)
StrategyFactory → SubGraph          session_id → thread_id
RootGraph.add_subgraph(...)         CompiledGraph 执行
RootGraph.compile(runtime_config)
Agent(...)
```

---

## 10. 与上层模块的关系

```text
调用方（测试 / 应用）
        ↓
AgentConfig + RuntimeConfig + RootGraph（构建期组装）
        ↓
Agent（运行期封装）
        ↓
CompiledGraph.invoke / stream
        ↓
Graph Node / Strategy SubGraph / Tool / LLM
```

| 模块 | 与 Agent 的关系 |
|------|----------------|
| **Graph** | Agent 持有 `RootGraph`，构造时编译；Agent 不定义 Node / Edge |
| **Runtime** | `RuntimeConfig` 在编译期注入 checkpointer / store |
| **Strategy** | 子图在 Agent 构造前挂载至 RootGraph；Agent 不感知 Strategy 类型 |
| **Model** | `UserInput` 作为默认输入载体；也可传入自定义 `BaseInput` 子类 |
| **LLM** | `AgentConfig.llm_config` 声明配置，由 Graph 构建方传递给 Node |

---

## 11. 已知限制

| 限制 | 说明 |
|------|------|
| 无 Builder | Graph 组装完全由调用方负责，无 `AgentBuilder` 封装 |
| 无 AgentContext | 缺少 `user_id` / `metadata` 等运行上下文传递机制 |
| AgentConfig 字段未自动消费 | `system_prompt`、`kb_list`、`skill_list` 仅声明，Agent 运行期不读取 |
| 同步 API | `invoke` / `stream` 均为同步方法，无异步版本 |
| stream 事件需上层解析 | Agent 不封装 token 提取逻辑，调用方需处理 AIMessageChunk |
| Debug API 无权限隔离 | `get_state` / `get_state_history` 直接暴露完整 State |
| checkpointer 可选 | `RuntimeConfig.checkpointer=None` 时无多轮状态持久化 |

---

## 12. 后续版本候选（v0.1.2+）

- [ ] `AgentBuilder`：从 `AgentConfig` 一键构建 RootGraph + Strategy + ToolRegistry
- [ ] `AgentContext` 模型：承载 `user_id` / `metadata`，写入 RunnableConfig
- [ ] `AgentConfig.strategy` 回归或替代方案（Factory 路由）
- [ ] 异步 `ainvoke` / `astream`
- [ ] stream 事件封装（如 `StreamEvent` 统一模型）
- [ ] `system_prompt` 运行时自动注入 Graph Context

---

## 13. 验证结论

v0.1.1 已通过以下手动场景验证：

- 简单 LLM 图：`invoke` / `stream` 单轮对话（`tests/test_agent.py`）
- ReAct Strategy 子图：`invoke` 多轮工具调用（`tests/test_react_agent.py`）
- ReAct Strategy 子图：`stream` 模式 FinalNode token 输出
- Checkpoint：`get_state()` 读取多轮会话 State
- Session 隔离：不同 `session_id` 对应独立 `thread_id`
