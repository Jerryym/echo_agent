# Graph 模块 v0.1.1 设计文档

## 1. 版本说明

| 项目 | 内容 |
|------|------|
| 版本 | v0.1.1 |
| 状态 | 已实现 |
| 依赖 | LangGraph `StateGraph` / `CompiledStateGraph` |
| 上一版本 | v0.1.0 |

### 1.1 v0.1.1 变更摘要

v0.1.1 在 v0.1.0 的 Schema 抽象基础上，补全了 **图结构构建与编译分层**，核心变化如下：

| 变更项 | v0.1.0 | v0.1.1 |
|--------|--------|--------|
| Graph 类 | 仅结构草案，无 `build()` | 完整实现 `add_node` / `add_edge` / `add_conditional_edges` / `build()` |
| 编译职责 | Graph 模块不负责 compile | 拆分为 `RootGraph.compile()` 与 `SubGraph.compile()` |
| SubGraph | 空抽象 `class SubGraph(ABC)` | 继承 `Graph` 的具体子图，支持 `as_node()` / `as_callable()` |
| 执行入口 | 未定义 | 新增 `RootGraph`，绑定 `RuntimeConfig`（checkpointer / store） |
| BaseState | `BaseModel` 占位 | `TypedDict`，集成 LangGraph `add_messages` reducer |
| 条件路由 | 无 | `add_conditional_edges()` 支持条件边 |
| 子图接入 | `add_subgraph()` 草案 | 通过 `SubGraph.as_node()` 或包装 `Node` + `as_callable()` 接入父图 |

---

## 2. 模块定位

Graph 模块用于对 LangGraph 进行统一抽象与封装，为 Agent 模块和 Strategy 模块提供图结构相关基础数据模型、节点抽象与图构建能力。

**负责：**

- 定义 Graph 结构模型（Schema / Node / Edge）
- 提供 `Graph` 结构描述与 `StateGraph` 构建（`build()`）
- 提供 `RootGraph` / `SubGraph` 编译能力
- 为 Agent 层提供可执行的根图对象
- 为 Strategy 层提供可复用的子图对象

**不负责：**

- Graph 运行（`invoke` / `stream` / `get_state`）—— 由 Agent 模块持有 `CompiledStateGraph` 后执行
- Agent 生命周期管理
- Agent 运行时管理（thread_id 等 RunnableConfig 由 Agent 构建）
- 策略业务逻辑与节点实现
- Tool 调用管理
- Memory 管理
- Checkpoint / Store 的具体实现（仅通过 `RuntimeConfig` 透传给 `RootGraph.compile()`）

---

## 3. 设计原则

### 3.1 LangGraph 解耦原则

echo-agent 基于 LangGraph 构建，但业务层不应直接依赖 LangGraph 的图构建细节。Graph 模块负责定义 echo-agent 自身的图领域模型，并在 `build()` / `compile()` 时适配 LangGraph。

```text
 Agent / Strategy
        ↓
 Graph / RootGraph / SubGraph
        ↓
   build() / compile()
        ↓
    LangGraph
```

### 3.2 结构 / 编译 / 运行 三层分离

v0.1.1 将图的职责拆为三层：

| 层级 | 类 | 职责 |
|------|-----|------|
| 结构层 | `Graph` | 描述节点、边、Schema，输出未编译的 `StateGraph` builder |
| 编译层 | `RootGraph` / `SubGraph` | 将 builder 编译为 `CompiledStateGraph` |
| 运行层 | `Agent` | 持有 `CompiledStateGraph`，执行 invoke / stream |

```text
Graph.build()           → StateGraph（builder）
RootGraph.compile()     → CompiledStateGraph（含 checkpointer / store）
SubGraph.compile()      → CompiledStateGraph（无 runtime 依赖）
Agent.invoke/stream()   → 实际执行
```

### 3.3 最小抽象原则

Graph 模块仅提供图领域最基础的数据结构与抽象能力，不重复封装 LangGraph 的完整能力，不承担 Agent Runtime 的职责。v0.1.1 中仍不提供：

```text
Workflow DSL
Runner 封装
Graph 级 invoke/stream 代理
```

### 3.4 State Patch 原则

Node 返回值采用 **State Patch** 模式：只返回需要更新的状态字段，由 LangGraph Runtime 合并。

```python
# ✅
return {"messages": [...], "response": "..."}

# ❌
return state
```

---

## 4. 模块结构

```text
echo_agent/core/graph/
├── __init__.py          # 对外导出
├── schema.py            # BaseInput / BaseOutput / BaseState / BaseContext
├── graph.py             # Graph 结构层
├── rootgraph.py         # RootGraph 编译层（根图）
├── subgraph.py          # SubGraph 编译层（子图）
└── node/
    ├── __init__.py
    └── node.py          # Node 抽象
```

对外导出（`echo_agent.core.graph`）：

```python
BaseInput, BaseOutput, BaseState, BaseContext
Node, Graph, RootGraph, SubGraph
START_NODE, END_NODE
```

---

## 5. Schema 模型

Graph 模块对 LangGraph 四种 Schema 进行统一抽象。

| Echo-Agent  | LangGraph      | v0.1.1 实现 |
| ----------- | -------------- | ----------- |
| BaseInput   | input_schema   | `BaseModel`，含 `input: UserInput` |
| BaseOutput  | output_schema  | `BaseModel` 占位，子类扩展 |
| BaseState   | state_schema   | `TypedDict`，含 reducer 注解 |
| BaseContext | context_schema | `BaseModel` 占位，子类扩展 |

### 5.1 BaseInput

用于描述 Graph 的输入参数，职责：**Graph 接收到的输入内容**。

```python
class BaseInput(BaseModel):
    input: UserInput
```

### 5.2 BaseOutput

用于描述 Graph 的输出结果，职责：**Graph 运行最终结果**。基类为空，由 Strategy 子类扩展（如 `ReActOutput.response`）。

### 5.3 BaseState

用于描述 Graph 运行过程中的状态，职责：**Graph 当前运行状态**。v0.1.1 使用 `TypedDict` 以兼容 LangGraph 的 reducer 机制。

```python
class BaseState(TypedDict):
    input: UserInput | dict[str, Any] | str
    messages: Annotated[Sequence[BaseMessage], add_messages]
    tool_calls: list[ToolCall]
    tool_results: list[ToolResult]
```

**设计说明：**

- `messages` 使用 LangGraph `add_messages` reducer，支持增量追加
- `tool_calls` / `tool_results` 引用 Tool 模块的 `ToolCall` / `ToolResult`
- Strategy 可通过 `TypedDict` 继承扩展字段（如 `ReActState.reasoning`）

### 5.4 BaseContext

用于描述 Graph 运行上下文，职责：**Graph 运行时共享上下文**。生命周期与单次 Graph 运行周期一致，由 LangGraph `context_schema` 注入各 Node 的 `run()` 方法。

---

## 6. Graph（结构层）

`Graph` 是 LangGraph `StateGraph` 的结构化封装层，**只负责描述图结构，不负责编译与运行**。

### 6.1 职责

- Schema 绑定（state / context / input / output）
- Node 注册
- 普通边注册
- 条件边注册
- 构建未编译的 `StateGraph` builder

### 6.2 公开 API

```python
class Graph(ABC):
    def __init__(
        self,
        state_schema: type[BaseState],
        context_schema: type[BaseContext] | None = None,
        input_schema: type[BaseInput] | None = None,
        output_schema: type[BaseOutput] | None = None,
    ): ...

    def add_node(self, node: Node) -> None: ...
    def add_edge(self, from_node: str, to_node: str) -> None: ...
    def add_conditional_edges(
        self,
        from_node: str,
        condition: Callable[[Any], str],
        path_map: dict[str, str] | None = None,
    ) -> None: ...

    def build(self) -> StateGraph: ...
```

### 6.3 边常量

```python
START_NODE = START   # LangGraph START
END_NODE = END       # LangGraph END
```

`add_edge` / `add_conditional_edges` 中可使用 `START_NODE` / `END_NODE` 作为源或目标节点名，`build()` 时自动映射为 LangGraph 的 `START` / `END`。

### 6.4 build() 流程

```text
绑定 state_schema（必选）
    ↓
可选绑定 context_schema / input_schema / output_schema
    ↓
StateGraph(**kwargs)
    ↓
遍历 _nodes → builder.add_node(name, node.run)
    ↓
遍历 _edges → builder.add_edge(source, target)
    ↓
遍历 _conditional_edges → builder.add_conditional_edges(source, condition, path_map)
    ↓
返回 StateGraph builder（未 compile）
```

---

## 7. RootGraph（根图编译层）

`RootGraph` 是图的执行入口，负责将结构层编译为可运行的 `CompiledStateGraph`，**不负责实际 invoke / stream**。

```python
class RootGraph(Graph):
    def compile(self, runtime_config: RuntimeConfig) -> CompiledStateGraph:
        return self.build().compile(
            checkpointer=runtime_config.checkpointer,
            store=runtime_config.store,
        )
```

### 7.1 使用场景

- Agent 模块持有并编译根图
- 需要 checkpointer / store 等运行时持久化能力
- 简单线性图或包含 Strategy 子图的顶层编排图

### 7.2 典型用法

```python
graph = RootGraph(state_schema=State)
graph.add_node(llm_node)
graph.add_edge(START_NODE, llm_node.name)
graph.add_edge(llm_node.name, END_NODE)

compiled = graph.compile(runtime_config)
```

---

## 8. SubGraph（子图编译层）

`SubGraph` 是一种特殊的 `Graph`，用于 Strategy 模块构建可复用的功能子图。

```python
class SubGraph(Graph):
    def __init__(
        self,
        name: str,
        state_schema: type[BaseState],
        context_schema: type[BaseContext] | None = None,
        input_schema: type[BaseInput] | None = None,
        output_schema: type[BaseOutput] | None = None,
    ): ...

    @property
    def name(self) -> str: ...

    def compile(self) -> CompiledStateGraph: ...
    def as_node(self) -> CompiledStateGraph: ...
    def as_callable(self) -> CompiledStateGraph: ...
```

### 8.1 与 RootGraph 的区别

| 项目 | RootGraph | SubGraph |
|------|-----------|----------|
| 命名 | 无 | 有 `name` 属性 |
| compile 参数 | 需要 `RuntimeConfig` | 无参数 |
| checkpointer / store | 通过 `RuntimeConfig` 注入 | 不注入 |
| 典型持有者 | Agent | Strategy |

### 8.2 子图接入父图的两种方式

LangGraph 支持两种子图接入模式，v0.1.1 通过 `SubGraph` 统一暴露：

**方式一：Add a subgraph as a node**

```python
parent.add_node("react", subgraph.as_node())
```

将编译后的子图直接注册为父图节点。

**方式二：Call a subgraph inside a node**

```python
class ReActNode(Node):
    def run(self, state, context=None):
        return self._subgraph.as_callable().invoke(state, context)
```

在自定义 `Node.run()` 内部调用子图，适合需要额外前后处理的场景。当前 ReAct 策略采用此方式。

---

## 9. 与上层模块的关系

### 9.1 Agent 模块

```text
AgentConfig + RuntimeConfig + RootGraph
        ↓
RootGraph.compile(runtime_config)
        ↓
Agent._compiled_graph
        ↓
invoke() / stream() / get_state()
```

- Agent 构造函数类型为 `graph: RootGraph`
- Agent 通过 `graph.input_schema` 校验输入
- 图的执行（invoke / stream）由 Agent 负责，不在 Graph 模块内

### 9.2 Strategy 模块

```text
BaseStrategy.build() → SubGraph
        ↓
注册 Reason / Action / Tool / Final 等 Node
        ↓
add_edge / add_conditional_edges 编排
        ↓
Strategy.as_node() → 包装 Node（可选）
        ↓
由 RootGraph 挂载到 Agent 根图
```

- `BaseStrategy.build()` 返回 `SubGraph`
- `BaseStrategy.as_node()` 返回包装后的 `Node`，供父图以「节点内调用子图」方式接入
- ReAct 策略示例：含条件路由的循环推理图

```text
START → reason ─┬→ action ─┬→ tool → reason
                │           ├→ reason
                └→ final → END
                            └→ final → END
```

### 9.3 整体架构

```text
┌─────────────────────────────────────┐
│              Agent                  │
│  RootGraph.compile(runtime_config)  │
│  invoke / stream / get_state        │
└──────────────┬──────────────────────┘
               │
    ┌──────────┴──────────┐
    │      RootGraph      │
    │  (简单 Node 编排)    │
    │  (或挂载 Strategy)   │
    └──────────┬──────────┘
               │
    ┌──────────┴──────────┐
    │      SubGraph       │
    │  (Strategy 产出)     │
    │  Reason/Action/...  │
    └─────────────────────┘
```

---

## 10. 已知限制与后续规划

### 10.1 v0.1.1 已知限制

| 限制 | 说明 |
|------|------|
| `Graph` 不可直接 compile | 必须使用 `RootGraph` 或 `SubGraph` |
| `SubGraph.compile()` 无 checkpointer | 子图持久化依赖父图 `RootGraph` 的 runtime 配置 |
| 无 `add_subgraph()` 便捷方法 | 子图接入需手动 `as_node()` 或包装 `Node` |
| `BaseOutput` / `BaseContext` 基类为空 | 具体字段由 Strategy 子类定义 |
| 条件边 `path_map` 可选 | 为 `None` 时依赖 LangGraph 默认路由行为 |
| Schema 跨模块引用 | `BaseState` 引用 `tool.schema`，需注意包入口导入避免循环依赖 |

### 10.2 后续版本候选（v0.1.2+）

- [ ] `Graph.add_subgraph()` 语法糖，简化子图挂载
- [ ] `SubGraph` 编译时支持可选 checkpointer 透传
- [ ] Graph 可视化 / debug 导出（mermaid / png）
- [ ] Node 异步 `run` 支持评估
- [ ] 统一 Strategy → RootGraph 自动组装工具（减少手动编排）
