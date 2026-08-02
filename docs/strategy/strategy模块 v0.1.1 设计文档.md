# Strategy 模块 v0.1.1 设计文档

## 1. 版本说明


| 项目     | 内容                                                  |
| ---------- | ------------------------------------------------------- |
| 版本     | v0.1.1                                                |
| 状态     | 已实现（ReAct）；Plan-Execute 仍为占位                |
| 依赖     | Graph`SubGraph`、LLM `LLMClient`、Tool `ToolRegistry` |
| 上一版本 | v0.1.0                                                |

> v0.1.0 中未变更的部分（模块定位、职责边界、Prompt 通用原则、Subgraph 封装思想）仍适用，本文档仅描述 v0.1.1 相对 v0.1.0 的实现变更。完整基线参见 `strategy模块 v0.1.0 设计文档.md`。

### 1.1 v0.1.1 变更摘要

v0.1.1 将 Strategy 从抽象设计落地为可运行框架，并完成 ReAct 策略首版实现，核心变化如下：


| 变更项              | v0.1.0（设计）                      | v0.1.1（实现）                                   |
| --------------------- | ------------------------------------- | -------------------------------------------------- |
| `BaseStrategy` 接口 | `build` / `as_node` / `as_subgraph` | 新增`compiled_graph`、`invoke`、State 映射三件套 |
| Factory API         | `StrategyFactory.create()`          | `create_as_subgraph()` / `create_as_node()`      |
| ReAct               | 规划                                | **完整实现**（四节点 + 条件路由）                |
| Plan-Execute        | 规划                                | 占位 stub，未实现                                |
| State 扩展          | TypedDict 继承（设计）              | Pydantic 子类继承（与 Graph v0.1.2 对齐）        |
| 子图挂载            | 概念描述                            | 对接 Graph`add_subgraph()` 与 `StrategyFactory`  |

ReAct 策略详细设计见 [`react/react Strategy v0.1.0 设计文档.md`](react/react%20Strategy%20v0.1.0%20设计文档.md)。

---

## 2. 模块定位（v0.1.1 补充）

Strategy 模块封装 Agent 的 **推理流程（Reasoning Pattern）**，将 ReAct、Plan-Execute 等模式实现为可复用的 LangGraph SubGraph。

**负责：**

- 定义 `BaseStrategy` 统一接口
- 构建 Strategy SubGraph（Node + Edge + 条件路由）
- 定义 Strategy 专属 Schema（Input / State / Output / Context）
- 管理 Strategy Prompt（与业务无关的推理规则）
- 提供 `StrategyFactory` 创建具体策略
- 完成 Parent State ↔ Strategy Input/Output 映射

**不负责：**

- Agent 生命周期与 invoke / stream 入口（Agent 模块）
- Tool 定义与注册（Tool 模块；Strategy 仅消费 `ToolRegistry`）
- LLM 底层适配（LLM 模块；Node 内创建 `LLMClient`）
- Checkpoint / thread 管理（Runtime + Agent）

---

## 3. 设计原则（v0.1.1 补充）

### 3.1 推理与执行分离原则

Strategy 负责 **决策流程**，Tool 模块负责 **工具执行**。Strategy Node 不直接调用业务 handler，而是通过 `ToolNode` + `ToolExecutor` 完成执行。

### 3.2 子图自治原则

每个 Strategy 构建独立的 `SubGraph`，内部 Node / 路由 / Schema 对 Parent Graph 透明。Parent Graph 只需挂载编译后的子图或包装 Node。

### 3.3 Parent-State 映射原则

当 Strategy 以「节点内调用子图」方式接入时，需显式实现 State 映射：

```text
Parent State
    ↓ to_strategy_input()
Strategy Input
    ↓ compiled_graph.invoke()
Strategy Output
    ↓ to_parent_state()
Parent State patch
```

以「子图节点」方式挂载时，LangGraph 直接传递 State，映射由 Schema 兼容性保证。

### 3.4 无状态 Strategy 原则

Strategy 实例在构建期创建，运行期不持有会话状态。步数、重试次数、消息历史等均由 Graph State（Checkpoint）承载。

---

## 4. 模块结构

```text
echo_agent/core/strategy/
├── __init__.py              # 导出 StrategyType, StrategyFactory
├── strategy.py              # BaseStrategy
├── strategy_factory.py      # StrategyFactory
├── emums.py                 # StrategyType
├── react/                   # ReAct 策略实现
│   ├── react_strategy.py
│   ├── schema.py
│   ├── node/
│   └── prompt/
└── plan_execute/            # Plan-Execute 占位
    └── plan_execute_strategy.py
```

对外导出：

```python
from echo_agent.core.strategy import StrategyType, StrategyFactory
```

---

## 5. BaseStrategy

### 5.1 完整接口

```python
class BaseStrategy(ABC):
    state_schema: type[BaseState]
    input_schema: type[BaseInput] | None = None
    output_schema: type[BaseOutput] | None = None
    context_schema: type[BaseContext] | None = None

    def __init__(
        self,
        state_schema: type[BaseState],
        input_schema: type[BaseInput] | None = None,
        output_schema: type[BaseOutput] | None = None,
        context_schema: type[BaseContext] | None = None,
    ): ...

    @cached_property
    def compiled_graph(self) -> CompiledStateGraph: ...

    @abstractmethod
    def build(self) -> SubGraph: ...

    @abstractmethod
    def as_node(self) -> Node: ...

    def as_subgraph(self) -> CompiledStateGraph: ...

    @abstractmethod
    def to_strategy_input(self, state: BaseState, context: BaseContext | None = None) -> BaseInput: ...

    def to_strategy_context(self, context: BaseContext | None = None) -> BaseContext | None: ...

    @abstractmethod
    def to_parent_state(self, output: BaseOutput) -> dict: ...

    def invoke(self, state: BaseState, context: BaseContext | None = None) -> dict: ...
```

### 5.2 v0.1.0 → v0.1.1 接口变更


| 方法                    | v0.1.0                | v0.1.1                                      |
| ------------------------- | ----------------------- | --------------------------------------------- |
| `build()`               | 返回 SubGraph（草案） | 返回未编译`SubGraph`，含完整 Node / Edge    |
| `as_subgraph()`         | abstractmethod        | **默认实现**：`return self.compiled_graph`  |
| `compiled_graph`        | 无                    | `@cached_property`，`build().as_callable()` |
| `to_strategy_input()`   | 无                    | **新增**，Parent → Strategy Input          |
| `to_strategy_context()` | 无                    | **新增**，默认透传                          |
| `to_parent_state()`     | 无                    | **新增**，Strategy Output → Parent patch   |
| `invoke()`              | 无                    | **新增**，完整子图调用 + 映射               |

### 5.3 invoke() 流程

```text
to_strategy_input(state, context)
    ↓
to_strategy_context(context)
    ↓
compiled_graph.invoke(input, context=strategy_context)
    ↓
output_schema(**output)  （若为 dict）
    ↓
to_parent_state(output) → dict patch
```

---

## 6. StrategyFactory

### 6.1 API

```python
class StrategyFactory:
    @staticmethod
    def create_as_subgraph(strategy_type: StrategyType, **kwargs) -> CompiledStateGraph: ...

    @staticmethod
    def create_as_node(strategy_type: StrategyType, **kwargs) -> Node: ...
```


| 方法                   | 对应 LangGraph 模式           | 返回值               | 典型用法                               |
| ------------------------ | ------------------------------- | ---------------------- | ---------------------------------------- |
| `create_as_subgraph()` | Add a subgraph as a node      | `CompiledStateGraph` | `RootGraph.add_subgraph("ReAct", ...)` |
| `create_as_node()`     | Call a subgraph inside a node | `Node`               | `RootGraph.add_node(react_node)`       |

### 6.2 StrategyType

```python
class StrategyType(Enum):
    REACT = "react"
    PLAN_EXECUTE = "plan_execute"
```

### 6.3 创建示例

**子图挂载（当前 ReAct 测试默认方式）：**

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

**节点内调用：**

```python
react_node = StrategyFactory.create_as_node(
    StrategyType.REACT,
    llm_config=config,
    tool_registry=tool_registry,
)

graph.add_node(react_node)
graph.add_edge(START_NODE, react_node.name)
graph.add_edge(react_node.name, END_NODE)
```

v0.1.0 设计中的 `StrategyFactory.create()` **已移除**，由上述两个方法替代。

---

## 7. Schema 约定

每个 Strategy 定义四套 Schema，均继承 Graph 基类：

```text
BaseInput    → StrategyInput    （如 ReActInput）
BaseState    → StrategyState    （如 ReActState）
BaseOutput   → StrategyOutput   （如 ReActOutput）
BaseContext  → StrategyContext  （如 ReActContext）
```

v0.1.1 使用 **Pydantic 子类继承**（Graph v0.1.2），Strategy State 扩展字段通过子类声明默认值。

SubGraph 构建时绑定四套 Schema：

```python
SubGraph(
    name="ReAct",
    state_schema=ReActState,
    context_schema=ReActContext,
    input_schema=ReActInput,
    output_schema=ReActOutput,
)
```

---

## 8. Prompt 组织

Strategy Prompt 存放于各策略目录下的 `prompt/` 子目录，通过 `PromptLoader` 加载：

```python
PromptLoader.load("core/strategy/react/prompt/reasoning.md")
```

Prompt 原则（继承 v0.1.0）：

- 通用、与业务无关
- 描述 Node 职责边界，不描述具体 Tool 实现
- 每个 Node 独立 Prompt，职责不重叠

ReAct 四套 Prompt 详见 ReAct 专文。

---

## 9. 策略实现状态


| Strategy     | 版本   | 状态      | 专文                                                                                       |
| -------------- | -------- | ----------- | -------------------------------------------------------------------------------------------- |
| ReAct        | v0.1.0 | 已实现    | [`react/react Strategy v0.1.0 设计文档.md`](react/react%20Strategy%20v0.1.0%20设计文档.md) |
| Plan-Execute | —     | 占位 stub | 待实现                                                                                     |

---

## 10. 与上层模块的关系

```text
Agent 构建期
    StrategyFactory.create_as_subgraph(REACT, ...)
        ↓
RootGraph.add_subgraph("ReAct", compiled)
        ↓
Agent(agent_config, runtime_config, graph)

Agent 运行期
    agent.invoke(session_id, UserInput)
        ↓
CompiledGraph（含 ReAct SubGraph）
        ↓
Reason → Action → Tool → Final（Strategy 内部）
```


| 模块        | 关系                                                                           |
| ------------- | -------------------------------------------------------------------------------- |
| **Graph**   | Strategy 产出`SubGraph`；Factory 产出 `CompiledStateGraph` 供 `add_subgraph`   |
| **Agent**   | 不感知 Strategy 类型；仅挂载编译结果                                           |
| **LLM**     | Node 内创建`LLMClient`；Reason / Action 使用 `invoke_structured`               |
| **Tool**    | ReAct 注入`ToolRegistry`；Action 选工具、ToolNode 执行                         |
| **Runtime** | Strategy Context（如`ReActContext.max_steps`）由 LangGraph context_schema 注入 |

---

## 11. 已知限制


| 限制                                          | 说明                                                                                           |
| ----------------------------------------------- | ------------------------------------------------------------------------------------------------ |
| Plan-Execute 未实现                           | `PlanExecuteStrategy` 方法均为 `pass`                                                          |
| 无统一 Strategy 注册表                        | 新增策略需修改`StrategyFactory` 分支                                                           |
| ReAct 步数/重试上限硬编码                     | `ReActStrategy` 构造时写死 `_max_steps=10`、`_retry_max_count=3`，与 `ReActContext` 默认值重复 |
| `to_strategy_context()` 未映射 Parent Context | ReAct 始终返回默认`ReActContext()`                                                             |
| 无 Strategy 级 stream 封装                    | 流式输出依赖 Agent + LangGraph 原生 stream                                                     |

---

## 12. 后续版本候选（v0.1.2+）

- [ ]  Plan-Execute 完整实现
- [ ]  Strategy 注册机制（插件式，免改 Factory）
- [ ]  Reflection / Supervisor 策略
- [ ]  Strategy 级集成测试框架

---

## 13. 验证结论

v0.1.1 已通过 ReAct Strategy 手动测试验证（`tests/test_react_agent.py`）：

- `create_as_subgraph` + `RootGraph.add_subgraph` 挂载与执行
- 多轮工具链式调用与任务完成判断
- `invoke` / `stream` 模式均可运行
- Checkpoint 多轮会话状态保持
