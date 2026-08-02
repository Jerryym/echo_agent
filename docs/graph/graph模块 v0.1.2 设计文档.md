# Graph 模块 v0.1.2 设计文档

## 1. 版本说明

| 项目 | 内容 |
|------|------|
| 版本 | v0.1.2 |
| 状态 | 已实现，ReAct Agent 手动测试通过 |
| 依赖 | LangGraph `StateGraph` / `CompiledStateGraph`、Pydantic v2 |
| 上一版本 | v0.1.1 |

> v0.1.1 中未变更的部分（模块定位、结构/编译/运行三层分离、State Patch 原则、RootGraph / SubGraph 编译职责等）仍适用，本文档仅描述 v0.1.2 新增与变更内容。完整基线参见 `graph模块 v0.1.1 设计文档.md`。

### 1.1 v0.1.2 变更摘要

v0.1.2 修正 Schema 实现方式，并补全子图挂载能力，核心变化如下：

| 变更项 | v0.1.1（文档/设计） | v0.1.2（实现） |
|--------|---------------------|----------------|
| `BaseState` 基类 | `TypedDict` | **Pydantic `BaseModel`** |
| Strategy State 扩展 | `TypedDict` 继承 | **Pydantic 子类继承**（如 `ReActState(BaseState)`） |
| `BaseState.response` | 未定义 | 新增 `response: str \| None` |
| `Graph.add_subgraph()` | 列为后续候选 | **已实现** |
| `build()` 子图注册 | 未描述 | 遍历 `_subgraphs` 注册 CompiledStateGraph |
| `Node.run()` 签名 | `(state, context)` | 新增可选 `config: RunnableConfig` |

---

## 2. 设计原则（v0.1.2 补充）

### 2.1 Pydantic State 原则

v0.1.2 统一使用 **Pydantic `BaseModel`** 作为 Graph State Schema，而非 `TypedDict`。

**原因：**

- Strategy State（如 `ReActState`）需通过 Pydantic 子类继承扩展字段，与 Input / Output / Context 建模方式一致
- LangGraph 支持 Pydantic State Schema，reducer 通过字段级 `Annotated[..., reducer]` 声明
- Node 返回值仍为 State Patch（`dict`），LangGraph 负责合并至 Pydantic State

```text
BaseState (Pydantic)
    ▲
ReActState (Pydantic 子类，扩展 reasoning / task_status 等)
    ↓
Node.run() → dict patch → LangGraph merge
```

### 2.2 子图挂载内置原则

v0.1.2 在 `Graph` 结构层内置 `add_subgraph()`，将已编译的 `CompiledStateGraph` 注册为具名节点，简化 RootGraph 挂载 Strategy 子图的流程。

```text
StrategyFactory.create_as_subgraph(REACT, ...)
        ↓
RootGraph.add_subgraph("ReAct", compiled_subgraph)
        ↓
Graph.build() → builder.add_node("ReAct", compiled_subgraph)
```

---

## 3. Schema 模型（v0.1.2 更新）

### 3.1 Schema 对照表

| Echo-Agent  | LangGraph      | v0.1.2 实现 |
| ------------- | -------------- | ----------- |
| BaseInput   | input_schema   | Pydantic `BaseModel` |
| BaseOutput  | output_schema  | Pydantic `BaseModel` |
| BaseState   | state_schema   | **Pydantic `BaseModel`** + reducer 注解 |
| BaseContext | context_schema | Pydantic `BaseModel` |

### 3.2 BaseState

```python
class BaseState(BaseModel):
    input: UserInput | dict[str, Any] | str | None = None
    messages: Annotated[list[BaseMessage], add_messages] = Field(default_factory=list)
    tool_calls: list[ToolCall] = Field(default_factory=list)
    tool_results: list[ToolResult] = Field(default_factory=list)
    response: str | None = None
```

| 字段 | 说明 |
|------|------|
| `input` | 当前轮用户输入，支持 `UserInput` / dict / str / None |
| `messages` | 会话消息历史；`Annotated[..., add_messages]` 启用增量追加 reducer |
| `tool_calls` | 待执行工具调用列表（Tool 模块 `ToolCall`） |
| `tool_results` | 工具执行结果列表（Tool 模块 `ToolResult`） |
| `response` | Graph 最终响应文本；简单 LLM 图或 Strategy 输出映射 |

**Reducer 说明：**

- 仅 `messages` 字段声明 LangGraph reducer（`add_messages`）
- `tool_calls` / `tool_results` 等列表字段采用 **覆盖式更新**：Node 返回新值时整体替换，而非 append
- 若后续需要 append 语义，需在对应字段上显式声明 reducer

### 3.3 Strategy State 扩展

Strategy 通过 Pydantic 子类继承扩展 State，示例（ReAct）：

```python
class ReActState(BaseState):
    reasoning: str = ""
    task_status: Literal["in_progress", "human_in_the_loop", "completed", "failed"] = "in_progress"
    observations: list[str] = Field(default_factory=list)
    step_count: int = Field(default=0)
    retry_count: int = Field(default=0)
```

调用方可在 RootGraph 层进一步继承：

```python
class State(BaseState):
    pass  # 或扩展顶层字段
```

### 3.4 ReActOutput 中的 reducer

Strategy Output Schema 同样可使用 reducer 注解：

```python
class ReActOutput(BaseOutput):
    response: str
    messages: Annotated[list[BaseMessage], add_messages] = Field(default_factory=list)
```

SubGraph 编译时绑定 `output_schema=ReActOutput`，LangGraph 在子图结束时按 Output Schema 提取结果。

---

## 4. Graph（结构层 v0.1.2 更新）

### 4.1 新增 add_subgraph()

```python
def add_subgraph(self, name: str, subgraph: CompiledStateGraph) -> None:
    self._subgraphs[name] = subgraph
```

| 参数 | 说明 |
|------|------|
| `name` | 子图在父图中的节点名 |
| `subgraph` | 已编译的 `CompiledStateGraph`（通常来自 `StrategyFactory.create_as_subgraph()` 或 `SubGraph.compile()`） |

### 4.2 build() 更新流程

```text
StateGraph(state_schema, [context/input/output schema])
    ↓
注册 _nodes → builder.add_node(name, node.run)
    ↓
注册 _subgraphs → builder.add_node(name, compiled_subgraph)   ← v0.1.2 新增
    ↓
注册 _edges
    ↓
注册 _conditional_edges
    ↓
返回 StateGraph builder
```

Node 与子图在 LangGraph builder 中均为具名节点，边定义中使用相同名称引用。

### 4.3 完整公开 API

```python
class Graph(ABC):
    def __init__(
        self,
        state_schema: type[BaseState],
        context_schema: type[BaseContext] | None = None,
        input_schema: type[BaseInput] | None = None,
        output_schema: type[BaseOutput] | None = None,
    ): ...

    @property
    def state_schema(self) -> type[BaseState]: ...
    @property
    def context_schema(self) -> type[BaseContext] | None: ...
    @property
    def input_schema(self) -> type[BaseInput] | None: ...
    @property
    def output_schema(self) -> type[BaseOutput] | None: ...

    def add_node(self, node: Node) -> None: ...
    def add_subgraph(self, name: str, subgraph: CompiledStateGraph) -> None: ...
    def add_edge(self, from_node: str, to_node: str) -> None: ...
    def add_conditional_edges(
        self,
        from_node: str,
        condition: Callable[[Any], str],
        path_map: dict[str, str] | None = None,
    ) -> None: ...

    def build(self) -> StateGraph: ...
```

---

## 5. Node（v0.1.2 更新）

### 5.1 run() 签名

```python
@abstractmethod
def run(
    self,
    state: BaseState,
    context: BaseContext | None = None,
    config: RunnableConfig | None = None,
) -> dict:
```

| 参数 | 说明 |
|------|------|
| `state` | 当前 Graph State（Pydantic 实例，LangGraph 传入） |
| `context` | Graph Context（绑定 `context_schema` 时可用） |
| `config` | LangChain RunnableConfig；LangGraph 运行时注入，Node 可透传至 LLMClient |

v0.1.2 中 `FinalNode` 已将 `config` 透传至 `LLMClient.invoke(..., config=config)`。多数 Node 可忽略该参数。

### 5.2 State Patch 返回值

Node 仍只返回需更新的字段 dict，不返回完整 State 对象：

```python
return {
    "response": response.content,
    "messages": [AIMessage(content=response.content)],
}
```

LangGraph 将 patch 合并至 Pydantic State，并触发字段级 reducer（如 `add_messages`）。

---

## 6. 子图接入模式（v0.1.2 更新）

v0.1.1 描述的两种子图接入方式均仍有效。v0.1.2 起，**方式一**成为 ReAct Agent 测试中的默认路径。

### 6.1 方式一：Add a subgraph as a node（推荐）

```python
react_subgraph = StrategyFactory.create_as_subgraph(
    StrategyType.REACT,
    llm_config=config,
    tool_registry=tool_registry,
)

graph = RootGraph(state_schema=State)
graph.add_subgraph("ReAct", react_subgraph)
graph.add_edge(START_NODE, "ReAct")
graph.add_edge("ReAct", END_NODE)
```

等价于手动调用 `SubGraph.compile()` 后 `add_subgraph()`。`StrategyFactory.create_as_subgraph()` 内部调用 `strategy.as_subgraph()` → `compiled_graph`。

**特点：**

- 子图作为独立 LangGraph 节点，stream 时可按 `langgraph_node` 过滤事件
- 父图 State Schema 与子图 State Schema 需兼容（通常父图 `State(BaseState)`，子图内部使用 `ReActState`）

### 6.2 方式二：Call a subgraph inside a node

```python
react_node = StrategyFactory.create_as_node(
    StrategyType.REACT,
    llm_config=config,
    tool_registry=tool_registry,
)

graph = RootGraph(state_schema=State)
graph.add_node(react_node)
graph.add_edge(START_NODE, react_node.name)
graph.add_edge(react_node.name, END_NODE)
```

`ReActNode.run()` 内部调用 `strategy.invoke(state, context)`，自行完成 Parent State ↔ Strategy Input/Output 映射。

**特点：**

- 适合需要在子图调用前后做 State 转换或额外处理的场景
- stream 时子图内部节点名可能不可直接过滤

---

## 7. 与上层模块的关系（v0.1.2 补充）

### 7.1 Agent 模块

Agent v0.1.1 构造时调用 `RootGraph.compile(runtime_config)`，依赖 Graph v0.1.2 的：

- `input_schema` property：校验 `invoke` / `stream` 输入
- Pydantic State：Checkpoint 持久化 State 快照
- `add_subgraph()`：挂载 Strategy 编译结果

### 7.2 Strategy 模块

```text
ReActStrategy.build()
    → SubGraph(name="ReAct", state_schema=ReActState, ...)
    → add_node / add_conditional_edges
    → 返回未编译 SubGraph

Strategy.as_subgraph()
    → compiled_graph（SubGraph.compile()）

StrategyFactory.create_as_subgraph()
    → 供 RootGraph.add_subgraph() 使用
```

ReAct 子图内部结构（v0.1.2 验证通过）：

```text
START → reason ─┬→ action ─┬→ tool → reason
                │           ├→ final → END
                └→ final → END
```

### 7.3 Tool 模块

`BaseState.tool_calls` / `tool_results` 引用 Tool 模块模型。`ToolNode` 返回 patch：

```python
{
    "tool_results": tool_results,
    "messages": tool_messages,
}
```

---

## 8. 典型构建示例

### 8.1 简单 LLM 线性图

```python
graph = RootGraph(state_schema=State)
graph.add_node(llm_node)
graph.add_edge(START_NODE, llm_node.name)
graph.add_edge(llm_node.name, END_NODE)

agent = Agent(agent_config, runtime_config, graph)
```

### 8.2 Strategy 子图挂载

```python
react_subgraph = StrategyFactory.create_as_subgraph(
    StrategyType.REACT,
    llm_config=config,
    tool_registry=tool_registry,
)

graph = RootGraph(state_schema=State)
graph.add_subgraph("ReAct", react_subgraph)
graph.add_edge(START_NODE, "ReAct")
graph.add_edge("ReAct", END_NODE)

agent = Agent(agent_config, runtime_config, graph)
```

---

## 9. 已知限制

| 限制 | 说明 |
|------|------|
| `Graph` 不可直接 compile | 仍需通过 `RootGraph` 或 `SubGraph` 编译 |
| `SubGraph.compile()` 无 checkpointer | 子图持久化依赖父图 `RootGraph` 的 RuntimeConfig |
| 列表字段默认覆盖更新 | 除 `messages` 外，`tool_calls` / `tool_results` 等无 append reducer |
| 父子图 State Schema 需协调 | `add_subgraph` 模式下，父图 State 需能承载子图输入/输出 |
| Schema 跨模块引用 | `BaseState` 引用 Tool 模块模型，需注意包入口导入顺序 |
| 条件边 `path_map` 可选 | 为 `None` 时依赖 LangGraph 默认路由（condition 返回值即目标节点名） |

---

## 10. 后续版本候选（v0.1.3+）

- [ ] `SubGraph` 编译时支持可选 checkpointer 透传
- [ ] 为 `tool_calls` / `tool_results` 评估专用 reducer（append / 清空语义）
- [ ] Graph 可视化 / debug 导出（mermaid / png）
- [ ] Node 异步 `arun` 支持评估
- [ ] `add_subgraph` 支持未编译 SubGraph 自动 compile 的重载

---

## 11. 验证结论

v0.1.2 已通过以下手动场景验证：

- Pydantic `BaseState` + `add_messages` reducer 多轮消息追加
- `RootGraph.add_subgraph("ReAct", ...)` 挂载 Strategy 子图并完整执行
- 条件边路由（reason / action 分支）正常运行
- `Node.run(config=...)` 透传至 LLMClient（FinalNode）
- Agent `invoke` / `stream` + Checkpoint 状态读取
- 简单 LLM 线性图（`tests/test_agent.py`）与 ReAct 子图（`tests/test_react_agent.py`）
